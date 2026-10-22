"""`spa-extract site`: um site de documentação estático inteiro (ou uma seção dele) para Markdown, sem navegador.

O sumário vem da melhor fonte que o site oferece, nesta ordem:
1. sumário em JSON publicado pelo próprio site — `toc.json` do Microsoft Learn (indicado em <meta name="toc_rel">) ou
   `toc-contents.json` dos guias da AWS: dá títulos e hierarquia na ordem do site;
2. sitemap (as linhas `Sitemap:` do robots.txt ou /sitemap.xml), filtrado pelo prefixo;
3. varredura em largura pelos links das páginas, na ordem em que aparecem (o menu lateral vem primeiro).
Só entram URLs dentro do prefixo (padrão: a pasta da URL inicial) e que o robots.txt permite. Cada página é lida como
no `page` (corpo do artigo, sem ruído de interface). Com o sumário em JSON, cada item com filhos vira pasta e a página
dele `00-<item>.md`, como no Help Portal; sem ele, as pastas repetem o caminho da URL.

Saída: output/[NN-<grupo>/]NN-<site>/<data-hora>/…, com manifest.json. `--resume` continua a extração mais recente,
pulando o que já está ok — para sites de milhares de páginas.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Self
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .config import Config
from .content import strip_noise, to_markdown
from .extractor import RunReport, course_dir, slugify
from .page import article, fetch
from .robots import USER_AGENT, RobotsRules

log = logging.getLogger(__name__)

SKIP_EXT = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ico|pdf|zip|gz|tgz|ipynb|py|json|xml|txt|csv|mp4|css|js)$", re.IGNORECASE
)
_RUN = re.compile(r"\d{8}-\d{6}")


@dataclass
class Entry:
    titles: tuple[str, ...]
    positions: tuple[int, ...]
    url: str  # vazio = título do sumário sem página
    has_children: bool = False

    @property
    def path_text(self) -> str:
        return " › ".join(self.titles)

    def relative_file(self) -> PurePosixPath:
        parts = [f"{n:02d}-{slugify(t, 60)}" for n, t in zip(self.positions, self.titles, strict=True)]
        if self.has_children:
            return PurePosixPath(*parts, f"00-{slugify(self.titles[-1], 60)}.md")
        return PurePosixPath(*parts[:-1], f"{parts[-1]}.md")


def default_prefix(url: str) -> str:
    """A pasta da URL inicial: …/userguide/what-is.html → …/userguide/; …/ai-foundry/ → …/ai-foundry/."""
    clean = urldefrag(url)[0].split("?", 1)[0]
    return clean if clean.endswith("/") else clean.rsplit("/", 1)[0] + "/"


def normalize(url: str) -> str:
    return urldefrag(url)[0].split("?", 1)[0]


@dataclass
class Scope:
    """O que entra na extração: URLs que começam com o prefixo, não são arquivos e não batem com --exclude."""

    prefix: str
    exclude: re.Pattern | None = None

    def __contains__(self, url: str) -> bool:
        return (
            url.startswith(self.prefix)
            and not SKIP_EXT.search(urlparse(url).path)
            and not (self.exclude and self.exclude.search(url))
        )


# --- sumário em JSON ----------------------------------------------------------------------------------------------

_TITLE_KEYS = ("toc_title", "title", "name")
_CHILD_KEYS = ("children", "contents", "items")


def _walk_toc(nodes: list, base: str, scope: Scope, titles=(), positions=()) -> Iterator[Entry]:
    number = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        title = next((str(node[k]).strip() for k in _TITLE_KEYS if node.get(k)), "")
        children = next((node[k] for k in _CHILD_KEYS if isinstance(node.get(k), list)), [])
        href = node.get("href") or ""
        url = normalize(urljoin(base, href)) if href else ""
        if url and url not in scope:
            url = ""  # aponta para fora da seção: fica só o título (e os filhos que estiverem dentro)
        sub = list(_walk_toc(children, base, scope, (*titles, title or "sem título"), (*positions, number + 1)))
        if not url and not sub:
            continue  # nada desta ramificação está dentro do prefixo
        number += 1
        yield Entry((*titles, title or "sem título"), (*positions, number), url, has_children=bool(sub))
        yield from sub


def toc_from_json(data: object, base: str, scope: Scope) -> list[Entry]:
    nodes = data
    if isinstance(data, dict):
        nodes = next((data[k] for k in _CHILD_KEYS if isinstance(data.get(k), list)), [])
    entries = list(_walk_toc(nodes if isinstance(nodes, list) else [], base, scope))
    # números dos filhos foram calculados antes de saber se o irmão anterior ficou de fora: renumera por nível
    return _renumber(entries)


def _renumber(entries: list[Entry]) -> list[Entry]:
    counters: dict[tuple[int, ...], int] = {}
    mapping: dict[tuple[int, ...], tuple[int, ...]] = {}
    fixed = []
    for entry in entries:
        parent_old = entry.positions[:-1]
        parent_new = mapping.get(parent_old, ())
        counters[parent_new] = counters.get(parent_new, 0) + 1
        new = (*parent_new, counters[parent_new])
        mapping[entry.positions] = new
        fixed.append(Entry(entry.titles, new, entry.url, entry.has_children))
    return fixed


def json_toc_urls(start: str, html: str) -> list[str]:
    """Onde o site publica o sumário em JSON: <meta name="toc_rel"> (Microsoft Learn) e toc-contents.json (AWS)."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    meta = soup.find("meta", attrs={"name": "toc_rel"})
    if meta and meta.get("content"):
        found.append(urljoin(start, meta["content"]))
    if urlparse(start).hostname == "docs.aws.amazon.com":
        found.append(urljoin(default_prefix(start), "toc-contents.json"))
    return found


# --- sitemap e varredura ------------------------------------------------------------------------------------------


def sitemap_urls(start: str, scope: Scope, robots_txt: str, limit: int = 20000) -> list[str]:
    parsed = urlparse(start)
    pending = [line.split(":", 1)[1].strip() for line in robots_txt.splitlines() if line.lower().startswith("sitemap:")]
    pending = pending or [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
    seen_maps, urls = set(), []
    while pending and len(seen_maps) < 50 and len(urls) < limit:
        sitemap = pending.pop(0)
        if sitemap in seen_maps:
            continue
        seen_maps.add(sitemap)
        try:
            root = ET.fromstring(fetch(sitemap, retries=1))
        except (RuntimeError, ET.ParseError):
            continue
        for loc in root.iter():
            if not loc.tag.endswith("loc") or not loc.text:
                continue
            url = loc.text.strip()
            if url.endswith((".xml", ".xml.gz")):
                # índice de sitemaps: só segue os que podem ter o prefixo
                if urlparse(url).netloc == parsed.netloc:
                    pending.append(url)
            elif normalize(url) in scope:
                urls.append(normalize(url))
    return list(dict.fromkeys(urls))


def page_links(url: str, html: str, scope: Scope) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = (normalize(urljoin(url, a["href"])) for a in soup.find_all("a", href=True))
    return list(dict.fromkeys(link for link in links if link in scope))


def url_entries(urls: list[str], prefix: str, titles: dict[str, str]) -> list[Entry]:
    """Sem sumário em JSON: pastas pelo caminho da URL, na ordem em que as páginas apareceram."""
    entries, positions_by_dir = [], {}

    def position(parent: tuple[str, ...], name: str) -> int:
        siblings = positions_by_dir.setdefault(parent, {})
        return siblings.setdefault(name, len(siblings) + 1)

    for url in urls:
        rest = url[len(prefix) :] if url.startswith(prefix) else urlparse(url).path.rsplit("/", 1)[-1]
        parts = (rest.strip("/") or "index").split("/")
        names, positions = [], []
        for depth, part in enumerate(parts):
            positions.append(position(tuple(parts[:depth]), part))
            names.append(re.sub(r"\.(html?|aspx|md)$", "", part) or "index")
        names[-1] = titles.get(url) or names[-1]
        entries.append(Entry(tuple(names), tuple(positions), url))
    return entries


# --- versão em Markdown publicada pelo site ------------------------------------------------------------------------

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def markdown_url(url: str, template: str) -> str:
    """--markdown "{url}?accept=text/markdown" (Microsoft Learn) ou "{url}.md" (Mintlify, GitBook, Hugging Face)."""
    return template.replace("{url}", url.rstrip("/"))


def clean_markdown(text: str) -> tuple[str, str]:
    """(título, corpo) da versão em Markdown: sem o front matter YAML, sem o aviso de índice para LLMs no topo
    (MCP) e sem as âncoras [[...]] nos títulos (Hugging Face)."""
    title = ""
    front = _FRONT.match(text)
    if front:
        found = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", front.group(1), re.MULTILINE)
        title = found.group(1).strip() if found else ""
        text = text[front.end() :]
    lines = text.lstrip().splitlines()
    while (
        lines and lines[0].startswith(">") and re.search(r"llms(-full)?\.txt|Documentation Index", "\n".join(lines[:6]))
    ):
        lines.pop(0)  # bloco de citação "Documentation Index … llms.txt" do topo
    body = re.sub(r"(?m)^(#{1,6} .*?)\s*\[\[[^\]]+\]\]\s*$", r"\1", "\n".join(lines)).strip() + "\n"
    if not title:
        heading = re.search(r"(?m)^# (.+)$", body)
        title = heading.group(1).strip() if heading else ""
    return title, body


# --- extração -----------------------------------------------------------------------------------------------------


class _Robots:
    def __init__(self, start: str, config: Config) -> None:
        parsed = urlparse(start)
        self.authorized = config.authorized_hosts.get(parsed.hostname or "")
        try:
            self.text = fetch(f"{parsed.scheme}://{parsed.netloc}/robots.txt", retries=1)
        except RuntimeError:  # 4xx: sem restrições (RFC 9309); falha de rede: segue com ritmo educado
            self.text = ""
        if self.text.lstrip().lower().startswith(("<!doctype", "<html")):
            self.text = ""  # site que devolve uma página no lugar do robots.txt (ex.: d2l.ai)
        self.rules = RobotsRules.parse(self.text)
        self.crawl_delay = self.rules.crawl_delay  # ex.: a AWS e o SAP Community pedem 5 s

    def allowed(self, url: str) -> bool:
        return bool(self.authorized) or self.rules.allowed(url)


def _latest_run(course: Path) -> Path | None:
    runs = sorted(d for d in course.iterdir() if d.is_dir() and _RUN.fullmatch(d.name)) if course.is_dir() else []
    return runs[-1] if runs else None


def _pause(config: Config, delay: float | None, floor: float = 0.0) -> None:
    """Pausa entre páginas: --delay (±50%) ou o [timing] do toml, nunca abaixo do Crawl-delay do robots.txt."""
    if delay is not None:
        wait = random.uniform(delay * 0.5, delay * 1.5)
    else:
        wait = random.uniform(config.timing.min_delay_s, config.timing.max_delay_s)
    time.sleep(max(wait, floor))


def _extract_site(
    config: Config,
    url: str,
    fetch_page,
    *,
    prefix: str | None = None,
    only: str | None = None,
    limit: int | None = None,
    max_pages: int = 20000,
    delay: float | None = None,
    resume: bool = False,
    content: str | None = None,
    exclude: str | None = None,
    depth: int | None = None,
    drop: list[str] | None = None,
    markdown: str | None = None,
) -> RunReport:
    scope = Scope(prefix or default_prefix(url), re.compile(exclude, re.IGNORECASE) if exclude else None)
    prefix = scope.prefix
    robots = _Robots(url, config)
    if robots.authorized:
        log.warning("%s: execução autorizada (%s)", urlparse(url).hostname, robots.authorized)
    elif not robots.allowed(url):
        raise PermissionError(f"O robots.txt de {urlparse(url).hostname} não permite robôs em {url}.")
    if content:
        config.selectors.content_container = content
    if drop:
        config.selectors.noise = [*config.selectors.noise, *drop]
    if robots.crawl_delay:
        log.info("o robots.txt pede %ss entre requisições: respeitando", robots.crawl_delay)

    start = normalize(url)
    start_html = fetch_page(url)
    start_title, _ = article(start_html, config)
    entries: list[Entry] = []
    for toc_url in json_toc_urls(url, start_html):
        try:
            entries = toc_from_json(json.loads(fetch(toc_url, retries=1)), toc_url, scope)
        except (RuntimeError, ValueError):
            continue
        if any(e.url for e in entries):
            log.info("sumário em JSON: %s (%s itens)", toc_url, len(entries))
            break
        entries = []
    crawl = not entries
    if crawl and depth is None:
        urls = sitemap_urls(url, scope, robots.text)
        if urls:
            log.info("sitemap: %s páginas dentro de %s", len(urls), prefix)
            first = [start] if start in scope and start not in urls else []
            entries = url_entries([*first, *urls], prefix, {start: start_title})
            crawl = False
    if crawl:
        log.info("varredura pelos links dentro de %s%s", prefix, f" (até {depth} nível(is))" if depth else "")

    name = config.course_name or start_title
    course = course_dir(config, prefix, name)
    previous = _latest_run(course) if resume else None
    done: dict[str, dict] = {}
    if previous and (previous / "manifest.json").exists():
        old = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
        done = {i["url"]: i for i in old.get("items", []) if i.get("status") == "ok" and i.get("url")}
        out = previous
        log.info("retomando %s (%s páginas já ok)", out, len(done))
    else:
        out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        out.mkdir(exist_ok=True)
    log.info("extração em %s", out)
    report = RunReport(url=prefix, started_at=datetime.now(UTC).isoformat(timespec="seconds"), output=str(out))
    report.items.extend(done.values())

    toc_mode = bool(entries) and not crawl and any(len(e.positions) > 1 or e.has_children for e in entries)
    seen: set[str] = set()
    levels = {start: 0}
    queue = [start]
    crawled: list[str] = []
    titles: dict[str, str] = {}
    planned = iter(entries)
    cache = {start: start_html}
    index = 0

    def next_entry() -> Entry | None:
        if not crawl:
            return next(planned, None)
        while queue:
            candidate = queue.pop(0)
            if candidate not in seen:
                return Entry((candidate,), (0,), candidate)
        return None

    def get(page_url: str) -> str:
        html = cache.pop(page_url, None)
        if html is None:
            html = fetch_page(page_url)
            _pause(config, delay, robots.crawl_delay)
        return html

    def read(page_url: str, html: str | None) -> tuple[str, str]:
        """(título, Markdown) da página: a versão em Markdown do site, se pedida e disponível; senão, o HTML."""
        if markdown:
            try:
                text = fetch(markdown_url(page_url, markdown))
                _pause(config, delay, robots.crawl_delay)
                if not text.lstrip().lower().startswith(("<!doctype", "<html")):
                    title, body = clean_markdown(text)
                    if body.strip():
                        return title, body
            except RuntimeError as error:
                log.info("sem versão em Markdown de %s (%s); usando o HTML", page_url, error)
        title, body = article(html if html is not None else get(page_url), config)
        return title, to_markdown(strip_noise(body, config))

    while (entry := next_entry()) is not None:
        index += 1
        if not entry.url:
            log.info("· %04d %s (só título no sumário)", index, entry.path_text)
            continue
        if entry.url in seen:
            continue  # a mesma página em dois lugares do sumário: uma cópia só
        seen.add(entry.url)
        if not robots.allowed(entry.url):
            log.info("· %04d %s (o robots.txt não permite)", index, entry.url)
            continue
        if entry.url in done and not crawl:
            continue
        if limit and len(report.items) - len(done) >= limit:
            log.info("limite de %s página(s) atingido", limit)
            break
        if len(report.items) >= max_pages:
            log.warning("teto de %s páginas atingido; aumente --max-pages se o site for maior", max_pages)
            break
        item: dict = {"index": index, "url": entry.url, "status": "pending"}
        try:
            html = None
            if crawl:
                # na varredura, toda página lida (mesmo já extraída, fora do --only ou fora do prefixo, como uma
                # página inicial de trilha) alimenta a fila e a numeração
                html = get(entry.url)
                level = levels.get(entry.url, 0)
                if depth is None or level < depth:
                    for link in page_links(entry.url, html, scope):
                        if link not in seen:
                            queue.append(link)
                            levels.setdefault(link, level + 1)
                if entry.url not in scope:
                    continue
                crawled.append(entry.url)
                titles[entry.url] = done.get(entry.url, {}).get("title") or article(html, config)[0]
                entry = url_entries(crawled, prefix, titles)[-1]
                if entry.url in done:
                    continue
            if only and not re.search(only, f"{entry.path_text} {entry.url}", re.IGNORECASE):
                continue
            title, text = read(entry.url, html)
            page_title = entry.titles[-1] if toc_mode else (title or entry.titles[-1])
            if not text.strip():
                raise ValueError("página sem conteúdo")
            relative = entry.relative_file()
            target = out / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            module = " › ".join(entry.titles[:-1]).replace('"', "'")
            target.write_text(
                f'---\ntitle: "{page_title.replace(chr(34), chr(39))}"\n'
                + (f'module: "{module}"\n' if module and toc_mode else "")
                + f"source: {entry.url}\nextracted_at: {datetime.now(UTC).isoformat(timespec='seconds')}\n---\n\n"
                + f"# {page_title}\n\n" * (not text.lstrip().startswith("#"))
                + text,
                encoding="utf-8",
            )
            item.update(status="ok", path=entry.path_text, title=page_title, file=str(relative), chars=len(text))
            log.info("✓ %04d %s (%s caracteres)", index, entry.path_text, len(text))
        except (RuntimeError, ValueError, OSError) as error:
            item.update(status="error", path=entry.path_text, error=f"{type(error).__name__}: {error}")
            log.warning("✗ %04d %s — %s", index, entry.url, error)
        report.items.append(item)
        report.save(out / "manifest.json")
    report.save(out / "manifest.json")
    return report


class _Renderer:
    """Páginas montadas por JavaScript (SPA, ex.: academy.claude.com): abre cada uma no Chromium headless e devolve o
    HTML já renderizado. Uma aba, uma página por vez; robots.txt, sitemap e sumários continuam sem navegador."""

    def __init__(self, wait_for: str) -> None:
        self.wait_for = wait_for

    def __enter__(self) -> Self:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._page = self._browser.new_context(user_agent=USER_AGENT).new_page()
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._playwright.stop()

    def __call__(self, url: str) -> str:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        for attempt in range(1, 4):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                try:
                    self._page.wait_for_selector(self.wait_for, timeout=15000)
                    self._page.wait_for_load_state("networkidle", timeout=8000)
                except PlaywrightTimeout:
                    pass  # sem o seletor ou com rede sempre ativa: usa o que já renderizou
                return self._page.content()
            except PlaywrightError as error:
                if attempt == 3:
                    raise RuntimeError(f"página indisponível ({url}): {error}") from error
                log.warning("render falhou (%s, tentativa %s); tentando de novo", type(error).__name__, attempt)
                time.sleep(3 * attempt)
        raise RuntimeError("inalcançável")


def extract_site(config: Config, url: str, *, render: bool = False, **options) -> RunReport:
    """Ver o docstring do módulo. render=True abre as páginas no navegador (SPA); senão, HTML estático."""
    if not render:
        return _extract_site(config, url, fetch, **options)
    with _Renderer(options.get("content") or "article, main") as renderer:
        return _extract_site(config, url, renderer, **options)
