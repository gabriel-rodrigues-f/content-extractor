"""`spa-extract page`: uma página de artigo estática (ex.: learn.microsoft.com) para Markdown, sem navegador.

Baixa o HTML, escolhe o corpo do artigo — o menor bloco que ainda tem quase todo o texto (no Microsoft Learn, o
`div.content` do artigo em vez do `main` com migalhas e metadados) —, remove o ruído de interface e grava no mesmo
layout dos cursos: output/[NN-<grupo>/]NN-<página>/<data-hora>/01-<página>.md, com manifest.json.
"""

from __future__ import annotations

import http.client
import logging
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from .config import Config
from .content import strip_noise, to_markdown
from .extractor import RunReport, course_dir, slugify
from .robots import ensure_allowed

log = logging.getLogger(__name__)

USER_AGENT = "spa-content-extractor"
# Onde costuma estar o artigo; vence o menor que tem ao menos SHARE do texto do maior. selectors.content_container no
# extractor.toml substitui a lista.
# #main-col-body: guias da AWS; .devsite-article-body: developers.google.com e docs.cloud.google.com
CANDIDATES = "article, [role=main], main, main div.content, #main-col-body, .devsite-article-body"
SHARE = 0.6


def fetch(url: str, retries: int = 3) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as error:
            if attempt == retries:
                raise RuntimeError(f"página indisponível ({url}): {error}") from error
            log.warning("página falhou (%s, tentativa %s); tentando de novo", type(error).__name__, attempt)
            time.sleep(3 * attempt)
    raise RuntimeError("inalcançável")


def article(html: str, config: Config) -> tuple[str, str]:
    """(título, HTML do corpo do artigo)."""
    soup = BeautifulSoup(html, "html.parser")
    for permalink in soup.select("a.headerlink"):
        permalink.decompose()  # "¶" do Sphinx ao lado de cada título (d2l.ai, scikit-learn)
    candidates = soup.select(config.selectors.content_container or CANDIDATES) or [soup.body or soup]
    sizes = [(len(c.get_text(" ", strip=True)), c) for c in candidates]
    biggest = max(size for size, _ in sizes)
    body = min((c for size, c in sizes if size >= SHARE * biggest), key=lambda c: len(c.get_text(" ", strip=True)))
    heading = soup.find("h1")
    title = " ".join(heading.get_text(" ").split()) if heading else ""
    if not title and soup.title:
        title = soup.title.get_text().split(" | ")[0].strip()
    return title or "página", str(body)


def extract_page(config: Config, url: str) -> RunReport:
    ensure_allowed(url, config)
    title, body = article(fetch(url), config)
    course = course_dir(config, url, config.course_name or title)
    out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out.mkdir(exist_ok=True)
    log.info("página: %s → %s", title, out)
    report = RunReport(url=url, started_at=datetime.now(UTC).isoformat(timespec="seconds"), output=str(out))
    entry: dict = {"index": 1, "path": title, "title": title, "status": "pending"}
    markdown = to_markdown(strip_noise(body, config))
    if markdown.strip():
        relative = f"01-{slugify(title, 60)}.md"
        safe_title = title.replace('"', "'")
        (out / relative).write_text(
            f'---\ntitle: "{safe_title}"\nsource: {url}\n'
            f"extracted_at: {datetime.now(UTC).isoformat(timespec='seconds')}\n---\n\n"
            + f"# {title}\n\n" * (not markdown.lstrip().startswith("#"))
            + markdown,
            encoding="utf-8",
        )
        entry.update(status="ok", file=relative, chars=len(markdown))
        log.info("✓ %s (%s caracteres)", title, len(markdown))
    else:
        entry.update(status="error", error="ValueError: página sem conteúdo")
        log.warning("✗ %s — página sem conteúdo", title)
    report.items.append(entry)
    report.save(out / "manifest.json")
    return report
