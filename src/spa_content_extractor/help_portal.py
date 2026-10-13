"""`spa-extract help`: documentos do SAP Help Portal (help.sap.com/docs/<produto>/<documento>/…) para Markdown.

O portal monta a página com duas chamadas JSON dele mesmo, e o extrator usa as mesmas — sem navegador e sem clicar:
- `deliverableMetadata` → id do documento, build e o arquivo do tópico da URL;
- `pagecontent` → o sumário inteiro da coluna da esquerda (`fullToc`: título, arquivo e filhos de cada item) e o HTML
  de um tópico.
O sumário é percorrido em profundidade, sempre do primeiro item; cada item com filhos vira pasta e a página dele vira
`00-<item>.md` dentro dela (no Help Portal os grupos também têm conteúdo). Mesmo layout de saída dos cursos:
output/[NN-<grupo>/]NN-<documento>/<data-hora>/…, com manifest.json.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from bs4 import BeautifulSoup

from .config import Config
from .content import strip_noise, to_markdown
from .extractor import RunReport, course_dir, slugify
from .robots import ensure_allowed

log = logging.getLogger(__name__)

BASE = "https://help.sap.com"
USER_AGENT = "spa-content-extractor (SAP Help Portal)"


@dataclass
class HelpDoc:
    product: str
    deliverable: str
    topic: str
    version: str
    locale: str

    @property
    def url(self) -> str:
        """URL do documento (sem o tópico): identifica o documento nas próximas extrações."""
        return f"{BASE}/docs/{self.product}/{self.deliverable}?version={self.version}&locale={self.locale}"


def parse_url(url: str) -> HelpDoc:
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.hostname != "help.sap.com" or len(parts) < 3 or parts[0] != "docs":
        raise LookupError(
            "use uma URL de documento do Help Portal: https://help.sap.com/docs/<produto>/<documento>[/<tópico>]"
        )
    query = urllib.parse.parse_qs(parsed.query)
    topic = parts[3] if len(parts) > 3 else ""
    return HelpDoc(
        product=parts[1],
        deliverable=parts[2],
        topic=topic.removesuffix(".html"),
        version=query.get("version", ["LATEST"])[0],
        locale=query.get("locale", ["en-US"])[0],
    )


class HelpPortalClient:
    def __init__(self, base: str = BASE, retries: int = 3) -> None:
        self.base = base
        self.retries = retries

    def get(self, path: str, params: dict) -> dict:
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") != "OK":
                    raise LookupError(f"o Help Portal respondeu {payload.get('status')} em {path}")
                return payload["data"]
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == self.retries:
                    raise RuntimeError(f"Help Portal indisponível em {path}: {error}") from error
                log.warning("Help Portal falhou (%s, tentativa %s); tentando de novo", type(error).__name__, attempt)
                time.sleep(3 * attempt)
        raise RuntimeError("inalcançável")


@dataclass
class Deliverable:
    id: int
    build: int
    title: str
    toc: list[dict]
    readable: dict[str, str]  # loio do tópico → trecho legível da URL


def load_deliverable(client: HelpPortalClient, doc: HelpDoc) -> Deliverable:
    meta = client.get(
        "/http.svc/deliverableMetadata",
        {
            "product_url": doc.product,
            "deliverable_url": doc.deliverable,
            "topic_url": doc.topic,
            "version": doc.version,
            "loadlandingpageontopicnotfound": "true",
            "locale": doc.locale,
        },
    )
    deliverable = meta["deliverable"]
    page = client.get(
        "/http.svc/pagecontent",
        {
            "deliverableInfo": 1,
            "deliverable_id": deliverable["id"],
            "buildNo": deliverable["buildNo"],
            "file_path": meta["filePath"],
        },
    )
    mapping = (meta.get("readableUrls") or {}).get("tocReadableUrlMapping") or []
    return Deliverable(
        id=deliverable["id"],
        build=deliverable["buildNo"],
        title=page["deliverable"].get("title") or deliverable.get("productName") or doc.deliverable,
        toc=page["deliverable"].get("fullToc") or [],
        readable={m["loio"]: m["url"] for m in mapping if m.get("loio") and m.get("url")},
    )


@dataclass
class TocItem:
    titles: tuple[str, ...]
    positions: tuple[int, ...]
    file: str
    has_children: bool

    @property
    def path_text(self) -> str:
        return " › ".join(self.titles)

    def relative_file(self) -> PurePosixPath:
        """Mesma regra dos cursos: cada nível numerado pela posição no sumário; item com filhos vira pasta e a página
        dele fica como 00-<item>.md dentro dela."""
        parts = [f"{n:02d}-{slugify(t, 60)}" for n, t in zip(self.positions, self.titles, strict=True)]
        if self.has_children:
            return PurePosixPath(*parts, f"00-{slugify(self.titles[-1], 60)}.md")
        return PurePosixPath(*parts[:-1], f"{parts[-1]}.md")


def walk(toc: list[dict], titles: tuple[str, ...] = (), positions: tuple[int, ...] = ()):
    """Sumário em profundidade, do primeiro item: o grupo antes dos filhos, os filhos antes do irmão seguinte."""
    for number, node in enumerate(toc, 1):
        children = node.get("c") or []
        item = TocItem(
            titles=(*titles, node.get("t") or node.get("u") or "sem título"),
            positions=(*positions, number),
            file=node.get("u") or "",
            has_children=bool(children),
        )
        yield item
        yield from walk(children, item.titles, item.positions)


def body_only(html: str) -> str:
    """O portal devolve o documento HTML inteiro (com <head><title>): só o <body> é conteúdo — senão o <title> vira
    uma linha solta repetindo o título."""
    soup = BeautifulSoup(html, "html.parser")
    return str(soup.body) if soup.body else html


def _front_matter(item: TocItem, source: str) -> str:
    title = item.titles[-1].replace('"', "'")
    module = " › ".join(item.titles[:-1]).replace('"', "'")
    return (
        "---\n"
        f'title: "{title}"\n' + (f'module: "{module}"\n' if module else "") + f"source: {source}\n"
        f"extracted_at: {datetime.now(UTC).isoformat(timespec='seconds')}\n"
        "---\n\n"
    )


def extract_help(
    config: Config,
    url: str,
    *,
    only: str | None = None,
    limit: int | None = None,
    client: HelpPortalClient | None = None,
) -> RunReport:
    ensure_allowed(url, config)
    doc = parse_url(url)
    client = client or HelpPortalClient()
    deliverable = load_deliverable(client, doc)
    log.info(
        "documento: %s (id %s, build %s, %s itens no topo do sumário)",
        deliverable.title,
        deliverable.id,
        deliverable.build,
        len(deliverable.toc),
    )
    course = course_dir(config, doc.url, config.course_name or deliverable.title)
    out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out.mkdir(exist_ok=True)
    log.info("extração em %s", out)
    report = RunReport(url=doc.url, started_at=datetime.now(UTC).isoformat(timespec="seconds"), output=str(out))

    for index, item in enumerate(walk(deliverable.toc), 1):
        if only and not re.search(only, item.path_text, re.IGNORECASE):
            continue
        if limit and len(report.items) >= limit:
            log.info("limite de %s item(ns) atingido", limit)
            break
        entry: dict = {"index": index, "path": item.path_text, "title": item.titles[-1], "status": "pending"}
        try:
            page = client.get(
                "/http.svc/pagecontent",
                {"deliverable_id": deliverable.id, "buildNo": deliverable.build, "file_path": item.file},
            )
            markdown = to_markdown(strip_noise(body_only(page.get("body") or ""), config))
            if not markdown.strip():
                raise ValueError("página sem conteúdo")
            loio = item.file.removesuffix(".html")
            source = f"{BASE}/docs/{doc.product}/{doc.deliverable}/{deliverable.readable.get(loio, loio)}?version={doc.version}"
            relative = item.relative_file()
            target = out / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                _front_matter(item, source)
                + f"# {item.titles[-1]}\n\n" * (not markdown.lstrip().startswith("#"))
                + markdown,
                encoding="utf-8",
            )
            entry.update(status="ok", file=str(relative), chars=len(markdown))
            log.info("✓ %03d %s (%s caracteres)", index, item.path_text, len(markdown))
        except (LookupError, RuntimeError, ValueError, KeyError) as error:
            entry.update(status="error", error=f"{type(error).__name__}: {error}")
            log.warning("✗ %03d %s — %s", index, item.path_text, error)
        report.items.append(entry)
        report.save(out / "manifest.json")
        time.sleep(random.uniform(config.timing.min_delay_s, config.timing.max_delay_s))  # ritmo educado
    return report
