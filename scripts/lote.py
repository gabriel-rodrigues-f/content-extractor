"""Roda as extrações listadas em output/STATUS.md, uma por vez, e marca cada curso no próprio arquivo ao terminar.

Formato do STATUS.md: cada "## <grupo>" vira uma pasta (output/NN-<grupo>/) e cada "- [ ] <url>" um curso dela. Ao
terminar, a linha vira "- [x] <url> — N/M lições · <pasta>" (ou "- [!] <url> — <motivo>" se falhar) e, quando todos os
cursos do grupo terminam, o título ganha " — concluído". Rodar de novo retoma do primeiro curso não concluído (e tenta
de novo os que falharam). Um curso já extraído em outro grupo é copiado, não baixado de novo.

Parâmetros de uma linha vão depois da URL e valem só para ela, ex.: "- [ ] <url> --subtree" ou
"- [ ] <url> --only 'Mapping Role Collections'". O comando sai da URL: help.sap.com/docs → help, learn.microsoft.com →
page, o resto → extract.

Outras marcas são ignoradas pelo lote e ficam no arquivo: "[~]" = na fila, aguardando um adaptador do extrator;
"[-]" = pulado de propósito (o motivo vai depois do " — "); "[>]" = em andamento por um lote (com o pid — se esse
processo não existe mais, o item volta a ser pendente).

Vários ao mesmo tempo: --workers N roda até N itens em paralelo, nunca dois do mesmo site (host) — cada site continua
recebendo uma requisição por vez. --groups REGEX limita aos grupos cujo título bate. O STATUS.md é relido e gravado sob
trava a cada resultado.

Uso, na pasta do projeto:  uv run python scripts/lote.py [--dry] [--workers N] [--groups REGEX]
"""

from __future__ import annotations

import argparse
import fcntl
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from spa_content_extractor.config import load_config
from spa_content_extractor.extractor import _numbered, slugify

DONE = " — concluído"


class SessionExpired(Exception):
    pass


ITEM = re.compile(r"^- \[( |x|!)\] (\S+)(.*)$")
MARK = re.compile(r"^- \[(.)\] ")
CLAIM = re.compile(r"^- \[>\] (\S+)(.*) — em andamento \(pid (\d+)\)$")
RESULT = re.compile(r"(\d+)/(\d+) item\(ns\) extraído\(s\) em (.+)$")


def latest_extraction(output: Path, url: str) -> Path | None:
    """A extração completa mais recente da URL em qualquer grupo (output/<grupo>/<curso>/<data>/)."""
    found: list[Path] = []
    for manifest in output.glob("*/*/*/manifest.json"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("items", [])
        if (
            str(data.get("url", "")).rstrip("/") == url.rstrip("/")
            and items
            and all(i["status"] == "ok" for i in items)
        ):
            found.append(manifest.parent)
    return max(found, key=lambda p: p.name) if found else None


def copy_into(output: Path, source: Path, group_dir: Path) -> Path:
    course = _numbered(group_dir, source.parent.name.split("-", 1)[1])
    target = course / source.name
    if not target.exists():
        shutil.copytree(source, target)
        manifest = target / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["output"] = str(target)
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def command_for(url: str) -> str:
    if "://help.sap.com/docs/" in url or "://help.sap.com/viewer/" in url:
        return "help"  # documento do SAP Help Portal: sumário pela API do portal
    if "://github.com/" in url:
        return "repo"  # repositório: clone raso, .md e notebooks
    if urlparse(url).path.lower().endswith(".pdf"):
        return "pdf"
    if "://learn.microsoft.com/" in url or "://learning.sap.com/live-sessions/" in url:
        return "page"  # artigo (ou descrição de sessão ao vivo) estático, uma página por linha
    return "extract"


def line_args(rest: str) -> str:
    """Parâmetros escritos depois da URL, antes do " — <resultado>"."""
    return rest.split(" — ", 1)[0].strip()


COMMANDS = {"extract", "help", "page", "site", "repo", "pdf"}


def extract(output: Path, url: str, group: str, args: str = "") -> tuple[bool, str]:
    logs = output / ".logs"
    logs.mkdir(exist_ok=True)
    parsed = urlparse(url)
    log = logs / f"{slugify(parsed.netloc + parsed.path, 120)}.log"
    tokens = shlex.split(args)
    # o comando sai da URL, a menos que a linha diga qual (ex.: "<url> site --delay 1")
    command = tokens.pop(0) if tokens and tokens[0] in COMMANDS else command_for(url)
    with log.open("w", encoding="utf-8") as handle:
        code = subprocess.run(
            [sys.executable, "-m", "spa_content_extractor.cli", command, url, "--group", group, *tokens],
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode
    text = log.read_text(encoding="utf-8")
    match = RESULT.search(text)
    if match:
        ok, total, path = match.groups()
        folder = Path(path.strip()).relative_to(output) if path.strip().startswith(str(output)) else path.strip()
        return code == 0, f"{ok}/{total} lições · {folder}"
    reason = re.search(r"Não foi possível continuar: (.+)", text)
    if reason and "sessão expirou" in reason.group(1):
        raise SessionExpired(reason.group(1))
    return False, (reason.group(1) if reason else f"saída {code}, veja {log.relative_to(output)}")[:200]


class Status:
    """O STATUS.md compartilhado pelos workers: cada gravação relê o arquivo sob trava e troca só a linha do item."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def read(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines()

    def update(self, old: str, new: str) -> None:
        with self.lock, self.path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            lines = handle.read().splitlines()
            if old in lines:
                lines[lines.index(old)] = new
            lines = mark_groups(lines)
            handle.seek(0)
            handle.write("\n".join(lines) + "\n")
            handle.truncate()


def mark_groups(lines: list[str]) -> list[str]:
    """Põe " — concluído" no título do grupo cujos itens estão todos resolvidos: [x] ou [-] (pulado de propósito).
    Item na fila [~], pendente ou com falha deixa o grupo aberto."""
    headers = [i for i, line in enumerate(lines) if line.startswith("## ")] + [len(lines)]
    for start, end in itertools.pairwise(headers):
        states = [m.group(1) for m in (MARK.match(x) for x in lines[start + 1 : end]) if m]
        if "x" in states and all(s in "x-" for s in states) and not lines[start].endswith(DONE):
            lines[start] += DONE
            print(f"■ grupo concluído: {lines[start][3:].removesuffix(DONE)}", flush=True)
    return lines


def pending_items(lines: list[str], groups: str | None) -> list[tuple[str, str, str, str]]:
    """(grupo, linha, url, parâmetros) de cada item a fazer, na ordem do arquivo."""
    items, group = [], None
    for line in lines:
        if line.startswith("## "):
            group = line[3:].removesuffix(DONE).strip() or None
            continue
        if groups and group and not re.search(groups, group, re.IGNORECASE):
            continue
        claim = CLAIM.match(line)
        if claim and group and not alive(int(claim.group(3))):
            items.append((group, line, claim.group(1), claim.group(2).strip()))  # lote que morreu no meio: refaz
            continue
        match = ITEM.match(line)
        if not match or group is None or match.group(1) == "x":
            continue
        items.append((group, line, match.group(2), line_args(match.group(3))))
    return items


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_item(output: Path, group: str, url: str, args: str) -> tuple[bool, str]:
    group_dir = _numbered(output, group)
    # com parâmetros (--only, --subtree…) a extração é parcial: não vale como cópia de outra
    source = None if args else latest_extraction(output, url)
    if source is not None and source.parent.parent != group_dir:
        target = copy_into(output, source, group_dir)
        return True, f"copiado de {source.relative_to(output)} → {target.relative_to(output)}"
    if source is not None:
        return True, f"já extraído · {source.relative_to(output)}"
    return extract(output, url, group, args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Roda as extrações pendentes do STATUS.md.")
    parser.add_argument("--dry", action="store_true", help="só lista o que está pendente")
    parser.add_argument("--workers", type=int, default=1, help="itens em paralelo, nunca dois do mesmo site")
    parser.add_argument("--groups", help="regex no título dos grupos a rodar")
    options = parser.parse_args()
    output = load_config(None).output_dir
    status = Status(output / "STATUS.md")
    queue = pending_items(status.read(), options.groups)
    if options.dry:
        for group, _, url, args in queue:
            print(f"{group} · {url}{' ' + args if args else ''}")
        print(f"pendentes: {len(queue)}", flush=True)
        return 0

    for group in dict.fromkeys(item[0] for item in queue):
        _numbered(output, group)  # pastas dos grupos antes dos workers: dois ao mesmo tempo não disputam o número
    busy: set[str] = set()
    stopped: dict[str, str] = {}  # host → motivo (sessão expirada: o resto daquele site falharia igual)
    changed = threading.Condition()
    processed = 0

    def take() -> tuple[str, str, str, str] | None:
        with changed:
            while True:
                queue[:] = [item for item in queue if urlparse(item[2]).netloc not in stopped]
                free = next((item for item in queue if urlparse(item[2]).netloc not in busy), None)
                if free is not None:
                    queue.remove(free)
                    busy.add(urlparse(free[2]).netloc)
                    return free
                if not queue:
                    return None
                changed.wait()

    def worker() -> None:
        nonlocal processed
        while (item := take()) is not None:
            group, line, url, args = item
            host = urlparse(url).netloc
            claimed = f"- [>] {url}{' ' + args if args else ''} — em andamento (pid {os.getpid()})"
            status.update(line, claimed)  # outro lote rodando ao mesmo tempo não pega este item
            line = claimed
            try:
                ok, note = run_item(output, group, url, args)
                status.update(line, f"- [{'x' if ok else '!'}] {url}{' ' + args if args else ''} — {note}")
                print(f"{'✓' if ok else '✗'} {group} · {url} · {note}", flush=True)
            except SessionExpired as error:
                # volta a pendente: depois do login, rodar de novo retoma daqui
                status.update(line, f"- [ ] {url}{' ' + args if args else ''}")
                stopped[host] = str(error)
                print(f"■ {host} parado: {error}", flush=True)
            except Exception as error:  # noqa: BLE001 — um item com erro inesperado não derruba os outros workers
                status.update(line, f"- [!] {url}{' ' + args if args else ''} — erro no lote: {type(error).__name__}")
                print(f"✗ {group} · {url} · erro no lote: {error}", flush=True)
            finally:
                with changed:
                    busy.discard(host)
                    processed += 1
                    changed.notify_all()

    threads = [threading.Thread(target=worker) for _ in range(max(1, options.workers))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    print(f"processados: {processed}", flush=True)
    return 4 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
