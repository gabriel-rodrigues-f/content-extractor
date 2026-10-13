"""Roda as extrações listadas em output/STATUS.md, uma por vez, e marca cada curso no próprio arquivo ao terminar.

Formato do STATUS.md: cada "## <grupo>" vira uma pasta (output/NN-<grupo>/) e cada "- [ ] <url>" um curso dela. Ao
terminar, a linha vira "- [x] <url> — N/M lições · <pasta>" (ou "- [!] <url> — <motivo>" se falhar) e, quando todos os
cursos do grupo terminam, o título ganha " — concluído". Rodar de novo retoma do primeiro curso não concluído (e tenta
de novo os que falharam). Um curso já extraído em outro grupo é copiado, não baixado de novo.

Uso, na pasta do projeto:  uv run python scripts/lote.py [--dry]
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from spa_content_extractor.config import load_config
from spa_content_extractor.extractor import _numbered

DONE = " — concluído"


class SessionExpired(Exception):
    pass


ITEM = re.compile(r"^- \[( |x|!)\] (\S+)")
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
    return "help" if "://help.sap.com/docs/" in url else "extract"


def extract(output: Path, url: str, group: str) -> tuple[bool, str]:
    logs = output / ".logs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{url.rstrip('/').rsplit('/', 1)[-1]}.log"
    with log.open("w", encoding="utf-8") as handle:
        code = subprocess.run(
            # documento do SAP Help Portal: comando próprio (sumário pela API do portal); o resto, curso
            [sys.executable, "-m", "spa_content_extractor.cli", command_for(url), url, "--group", group],
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


def main() -> int:
    dry = "--dry" in sys.argv
    output = load_config(None).output_dir
    status = output / "STATUS.md"
    lines = status.read_text(encoding="utf-8").splitlines()

    def save() -> None:
        status.write_text("\n".join(lines) + "\n", encoding="utf-8")

    group, header_at, pending = None, None, 0
    for index in range(len(lines) + 1):
        line = lines[index] if index < len(lines) else "## "
        if line.startswith("## "):
            if group is not None and header_at is not None and not dry:
                items = [ITEM.match(x) for x in lines[header_at + 1 : index]]
                states = [m.group(1) for m in items if m]
                if states and all(s == "x" for s in states) and not lines[header_at].endswith(DONE):
                    lines[header_at] += DONE
                    save()
                    print(f"■ grupo concluído: {group}", flush=True)
            group = line[3:].removesuffix(DONE).strip() or None
            header_at = index
            continue
        match = ITEM.match(line)
        if not match or group is None or match.group(1) == "x":
            continue
        url = match.group(2)
        pending += 1
        if dry:
            print(f"{group} · {url}")
            continue
        group_dir = _numbered(output, group)
        source = latest_extraction(output, url)
        if source is not None and source.parent.parent != group_dir:
            target = copy_into(output, source, group_dir)
            ok, note = True, f"copiado de {source.relative_to(output)} → {target.relative_to(output)}"
        elif source is not None:
            ok, note = True, f"já extraído · {source.relative_to(output)}"
        else:
            try:
                ok, note = extract(output, url, group)
            except SessionExpired as error:
                # todo o resto falharia igual: para o lote sem marcar nada; depois do login, rodar de novo retoma daqui
                print(f"■ lote parado: {error}", flush=True)
                return 4
        lines[index] = f"- [{'x' if ok else '!'}] {url} — {note}"
        save()
        print(f"{'✓' if ok else '✗'} {group} · {url.rsplit('/', 1)[-1]} · {note}", flush=True)
    print(f"{'pendentes' if dry else 'processados'}: {pending}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
