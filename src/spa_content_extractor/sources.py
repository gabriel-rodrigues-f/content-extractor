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


def extract_repo(
    config: Config, url: str, *, path: str = "", include: str | None = None, assets: str | None = None
) -> RunReport:
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
        suffix = f"-{PurePosixPath(path.strip('/')).name}" if path else ""
        name = config.course_name or owner_repo.replace("/", "-") + suffix
        # com --path, a fonte é a subpasta: dois trechos do mesmo repositório (ex.: RA0009 e RA0018 do Architecture
        # Center) não podem cair na mesma pasta
        identity = f"https://github.com/{owner_repo}" + (f"/tree/HEAD/{path.strip('/')}" if path else "")
        course = course_dir(config, identity, name)
        out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        out.mkdir(exist_ok=True)
        log.info("extração em %s (%s arquivos; licença: %s)", out, len(files), license_text or "não declarada")
        report = RunReport(
            url=identity,
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
        if assets:
            # arquivos que não viram nota mas acompanham o conteúdo (ex.: diagramas .drawio): copiados como estão
            for asset in sorted(p for p in base.rglob("*") if p.is_file() and re.search(assets, p.name, re.IGNORECASE)):
                relative = PurePosixPath(asset.relative_to(root).as_posix())
                target = out / PurePosixPath(*[slugify(part, 60) for part in relative.parent.parts], asset.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(asset.read_bytes())
                report.items.append(
                    {"index": len(report.items) + 1, "path": str(relative), "status": "ok", "asset": True}
                )
                log.info("✓ anexo %s", relative)
        report.save(out / "manifest.json")
    return report


def pdf_sections(reader, pages: list[str], max_depth: int) -> list[tuple[tuple[str, ...], tuple[int, ...], str]]:
    """Seções do PDF pelos marcadores (sumário embutido) até max_depth: (títulos, posições, texto). Vários marcadores
    podem começar na mesma página, então o corte é feito onde o título aparece no texto, não no início da página."""
    flat: list[tuple[int, str, int]] = []

    def walk(items, depth):
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
            elif depth <= max_depth:
                try:
                    flat.append((depth, item.title.strip(), reader.get_destination_page_number(item)))
                except Exception as error:  # noqa: BLE001 — marcador sem destino válido
                    log.debug("marcador ignorado (%s): %s", type(error).__name__, getattr(item, "title", "?"))

    walk(reader.outline, 0)
    flat = [f for f in flat if f[1].lower() not in {"contents", "table of contents", "sumário"}]
    offsets, text = [], ""
    for page in pages:
        offsets.append(len(text))
        text += page + "\n\n"
    cuts = []
    for depth, title, page in flat:
        begin = offsets[page] if page < len(offsets) else len(text)
        found = text.lower().find(title.lower()[:60], begin, begin + 6000 if page < len(offsets) else begin)
        cuts.append(max(found if found >= 0 else begin, cuts[-1] if cuts else 0))
    sections, stack, counters = [], [], {}
    for i, (depth, title, _) in enumerate(flat):
        stack = stack[:depth]
        parent = tuple(n for _, n in stack)
        counters[parent] = counters.get(parent, 0) + 1
        stack.append((title, counters[parent]))
        body = text[cuts[i] : cuts[i + 1] if i + 1 < len(cuts) else len(text)].strip()
        sections.append((tuple(t for t, _ in stack), tuple(n for _, n in stack), body))
    return sections


def extract_pdf(config: Config, url: str, *, split_depth: int | None = None) -> RunReport:
    """Texto do PDF numa nota; com split_depth, uma nota por seção do sumário embutido (até esse nível), em pastas por
    capítulo — para guias de centenas de páginas."""
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
    sections = pdf_sections(reader, pages, split_depth) if split_depth is not None and reader.outline else []
    if sections:
        has_children = {titles[:-1] for titles, _, _ in sections if len(titles) > 1}
        for index, (titles, positions, body) in enumerate(sections, 1):
            entry: dict = {"index": index, "path": " › ".join(titles), "title": titles[-1]}
            parts = [f"{n:02d}-{slugify(t, 50)}" for n, t in zip(positions, titles, strict=True)]
            relative = (
                PurePosixPath(*parts, f"00-{slugify(titles[-1], 50)}.md")
                if titles in has_children
                else PurePosixPath(*parts[:-1], f"{parts[-1]}.md")
            )
            if len(body.split()) < 3:
                entry.update(status="error", error="ValueError: seção sem texto")
            else:
                (out / relative).parent.mkdir(parents=True, exist_ok=True)
                (out / relative).write_text(
                    _front(titles[-1], url, " › ".join(titles[:-1])) + f"# {titles[-1]}\n\n{body}\n", encoding="utf-8"
                )
                entry.update(status="ok", file=str(relative), chars=len(body))
            report.items.append(entry)
        log.info("✓ %s: %s seções do sumário (%s páginas)", title, len(sections), len(pages))
        report.save(out / "manifest.json")
        return report
    body = "\n\n".join(f"<!-- página {n} -->\n\n{text}" for n, text in enumerate(pages, 1) if text)
    entry = {"index": 1, "path": title, "title": title, "status": "pending"}
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


def _zendesk_get(url: str) -> dict:
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _zendesk_all(url: str, key: str, pause: float) -> list[dict]:
    """Todas as páginas de uma listagem da API do Zendesk (segue next_page)."""
    import time

    items: list[dict] = []
    while url:
        data = _zendesk_get(url)
        items.extend(data.get(key, []))
        url = data.get("next_page")
        if url:
            time.sleep(pause)
    return items


def extract_zendesk(
    config: Config, url: str, *, sections: str | None = None, list_only: bool = False, pause: float = 1.5
) -> RunReport | None:
    """Central de ajuda Zendesk (…/hc/<idioma>) pela API JSON pública do Help Center — útil quando o HTML está atrás
    de desafio anti-bot e o robots.txt libera /api/v2/help_center. `sections` filtra as seções pelo nome."""
    import time

    from .content import strip_noise, to_markdown

    parsed = urlparse(url)
    match = re.search(r"/hc/([^/]+)", parsed.path)
    locale = match.group(1) if match else "en-us"
    api = f"{parsed.scheme}://{parsed.netloc}/api/v2/help_center/{locale}"
    ensure_allowed(f"{api}/sections.json", config)
    categories = {c["id"]: c["name"] for c in _zendesk_all(f"{api}/categories.json?per_page=100", "categories", pause)}
    all_sections = _zendesk_all(f"{api}/sections.json?per_page=100", "sections", pause)
    chosen = [s for s in all_sections if not sections or re.search(sections, s["name"], re.IGNORECASE)]
    if list_only:
        for s in chosen:
            print(f"{categories.get(s.get('category_id'), '?')} › {s['name']}  ({s['html_url']})")
        print(f"{len(chosen)} de {len(all_sections)} seções")
        return None
    name = config.course_name or parsed.netloc
    course = course_dir(config, url, name)
    out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out.mkdir(exist_ok=True)
    report = RunReport(url=url, started_at=datetime.now(UTC).isoformat(timespec="seconds"), output=str(out))
    category_numbers: dict[int, int] = {}
    for section_number, section in enumerate(chosen, 1):
        time.sleep(pause)
        articles = _zendesk_all(f"{api}/sections/{section['id']}/articles.json?per_page=100", "articles", pause)
        category = categories.get(section.get("category_id"), "geral")
        number = category_numbers.setdefault(section.get("category_id"), len(category_numbers) + 1)
        folder = PurePosixPath(
            f"{number:02d}-{slugify(category, 50)}", f"{section_number:02d}-{slugify(section['name'], 60)}"
        )
        for index, article in enumerate(sorted(articles, key=lambda a: a.get("position", 0)), 1):
            entry: dict = {
                "index": len(report.items) + 1,
                "path": f"{category} › {section['name']} › {article['title']}",
            }
            markdown = to_markdown(strip_noise(article.get("body") or "", config))
            if not markdown.strip():
                entry.update(status="error", error="ValueError: artigo sem conteúdo")
            else:
                relative = folder / f"{index:02d}-{slugify(article['title'], 60)}.md"
                (out / relative).parent.mkdir(parents=True, exist_ok=True)
                (out / relative).write_text(
                    _front(article["title"], article["html_url"], f"{category} › {section['name']}")
                    + f"# {article['title']}\n\n{markdown}",
                    encoding="utf-8",
                )
                entry.update(status="ok", file=str(relative), chars=len(markdown))
                log.info("✓ %s", entry["path"])
            report.items.append(entry)
        report.save(out / "manifest.json")
    report.save(out / "manifest.json")
    return report
