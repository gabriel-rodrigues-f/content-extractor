"""Fontes que não são páginas web: `spa-extract repo` (repositório do GitHub) e `spa-extract pdf` (documento PDF).

- repo: clone raso (`git clone --depth 1`); cada .md vira uma nota e cada .ipynb também — células de texto como estão e
  células de código em blocos ```python, sem as saídas (imagens em base64 e tabelas impressas pesam e não são texto do
  curso). As pastas repetem as do repositório. `--path` limita a uma subpasta.
- pdf: baixa o PDF e extrai o texto página a página (pypdf), numa nota só.

Mesmo layout de saída dos cursos: output/[NN-<grupo>/]NN-<nome>/<data-hora>/…, com manifest.json.
"""

from __future__ import annotations

import io
import json
import logging
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .config import Config
from .extractor import RunReport, course_dir, slugify
from .page import USER_AGENT
from .robots import ensure_allowed

log = logging.getLogger(__name__)

_NOTEBOOK_SKIP = re.compile(r"(^|/)(\.|node_modules/|venv/|__pycache__/)")


def _front(title: str, source: str, module: str = "") -> str:
    safe = title.replace('"', "'")
    return (
        f'---\ntitle: "{safe}"\n'
        + (f'module: "{module}"\n' if module else "")
        + f"source: {source}\nextracted_at: {datetime.now(UTC).isoformat(timespec='seconds')}\n---\n\n"
    )


def notebook_markdown(raw: str) -> str:
    data = json.loads(raw)
    language = (data.get("metadata", {}).get("language_info", {}) or {}).get("name") or "python"
    parts = []
    for cell in data.get("cells", []):
        source = "".join(cell.get("source", [])) if isinstance(cell.get("source"), list) else cell.get("source", "")
        if not source.strip():
            continue
        if cell.get("cell_type") == "markdown":
            # imagens embutidas no markdown da célula (attachment:/data:) viram comentário, como no resto do extrator
            source = re.sub(
                r"!\[([^\]]*)\]\((?:attachment:|data:)[^)]*\)", r"<!-- Imagem presente aqui: \1 -->", source
            )
            parts.append(source.strip())
        elif cell.get("cell_type") == "code":
            parts.append(f"```{language}\n{source.strip()}\n```")
    return "\n\n".join(parts) + "\n"


def _title(markdown: str, fallback: str) -> str:
    heading = re.search(r"(?m)^#{1,2} (.+)$", markdown)
    # tira a ênfase do Markdown (**x**, __x__, *x*, `x`), mas não o "_" dentro de nomes como btp_subaccount
    return re.sub(r"\*\*|__|\*|`", "", heading.group(1)).strip() if heading else fallback


def extract_repo(config: Config, url: str, *, path: str = "", include: str | None = None) -> RunReport:
    parsed = urlparse(url)
    owner_repo = "/".join(parsed.path.strip("/").split("/")[:2])
    if parsed.hostname != "github.com" or owner_repo.count("/") != 1:
        raise LookupError("use a URL de um repositório do GitHub: https://github.com/<dono>/<repositório>")
    clone_url = f"https://github.com/{owner_repo}.git"
    with tempfile.TemporaryDirectory(prefix="spa-repo-") as tmp:
        log.info("clonando %s (raso)", clone_url)
        subprocess.run(["git", "clone", "--depth", "1", "--quiet", clone_url, tmp], check=True, timeout=1800)
        root = Path(tmp)
        branch = subprocess.run(
            ["git", "-C", tmp, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        license_file = next((p for p in root.glob("LICENSE*") if p.is_file()), None)
        license_text = (
            license_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0] if license_file else ""
        )
        base = root / path if path else root
        files = sorted(
            p
            for p in base.rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".md", ".ipynb"}
            and not _NOTEBOOK_SKIP.search(p.relative_to(root).as_posix())
            and (not include or re.search(include, p.relative_to(root).as_posix(), re.IGNORECASE))
        )
        name = config.course_name or owner_repo.replace("/", "-")
        course = course_dir(config, f"https://github.com/{owner_repo}", name)
        out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        out.mkdir(exist_ok=True)
        log.info("extração em %s (%s arquivos; licença: %s)", out, len(files), license_text or "não declarada")
        report = RunReport(
            url=f"https://github.com/{owner_repo}",
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            output=str(out),
        )
        for index, file in enumerate(files, 1):
            relative = PurePosixPath(file.relative_to(root).as_posix())
            entry: dict = {"index": index, "path": str(relative), "status": "pending"}
            try:
                raw = file.read_text(encoding="utf-8", errors="replace")
                markdown = notebook_markdown(raw) if file.suffix.lower() == ".ipynb" else raw.strip() + "\n"
                if not markdown.strip():
                    raise ValueError("arquivo sem conteúdo")
                title = _title(markdown, file.stem.replace("_", " ").replace("-", " "))
                target_rel = PurePosixPath(
                    *[slugify(part, 60) for part in relative.parent.parts], f"{slugify(file.stem, 60)}.md"
                )
                target = out / target_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                source = f"https://github.com/{owner_repo}/blob/{branch}/{relative}"
                module = " › ".join(relative.parent.parts)
                target.write_text(_front(title, source, module) + markdown, encoding="utf-8")
                entry.update(status="ok", title=title, file=str(target_rel), chars=len(markdown))
                log.info("✓ %04d %s (%s caracteres)", index, relative, len(markdown))
            except (OSError, ValueError) as error:
                entry.update(status="error", error=f"{type(error).__name__}: {error}")
                log.warning("✗ %04d %s — %s", index, relative, error)
            report.items.append(entry)
        report.save(out / "manifest.json")
    return report


def extract_pdf(config: Config, url: str) -> RunReport:
    import urllib.request

    from pypdf import PdfReader

    ensure_allowed(url, config)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    reader = PdfReader(io.BytesIO(data))
    meta_title = (reader.metadata.title if reader.metadata else "") or ""
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    first_line = next((line.strip() for text in pages for line in text.splitlines() if line.strip()), "")
    title = config.course_name or meta_title.strip() or first_line or Path(urlparse(url).path).stem
    course = course_dir(config, url, title)
    out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out.mkdir(exist_ok=True)
    report = RunReport(url=url, started_at=datetime.now(UTC).isoformat(timespec="seconds"), output=str(out))
    body = "\n\n".join(f"<!-- página {n} -->\n\n{text}" for n, text in enumerate(pages, 1) if text)
    entry: dict = {"index": 1, "path": title, "title": title, "status": "pending"}
    if body.strip():
        relative = f"01-{slugify(title, 60)}.md"
        (out / relative).write_text(_front(title, url) + f"# {title}\n\n{body}\n", encoding="utf-8")
        entry.update(status="ok", file=relative, chars=len(body), pages=len(pages))
        log.info("✓ %s (%s páginas, %s caracteres)", title, len(pages), len(body))
    else:
        entry.update(status="error", error="ValueError: PDF sem texto extraível (digitalizado?)")
        log.warning("✗ %s — PDF sem texto extraível", title)
    report.items.append(entry)
    report.save(out / "manifest.json")
    return report
