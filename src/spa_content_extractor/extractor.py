"""Fluxo de extração: abrir → ação de entrada → percorrer o menu em profundidade (sempre do primeiro item) e, em cada
tópico, clicar, esperar estabilizar, extrair e salvar."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from .browser import open_browser, polite_pause, wait_until_stable
from .config import Config
from .content import ContentLocation, content_text, locate_content, serialize, strip_noise, to_markdown
from .entry import run_start_actions
from .navigation import MenuWalker, NavItem
from .robots import ensure_allowed

log = logging.getLogger(__name__)


def slugify(text: str, limit: int = 70) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return (re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:limit].rstrip("-")) or "sem-titulo"


@dataclass
class RunReport:
    url: str
    started_at: str
    output: str
    items: list[dict] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def run_dir(config: Config, url: str) -> Path:
    host = urlparse(url).netloc.replace(":", "_") or "local"
    path = (
        config.output_dir / host / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    )  # hora local no nome da pasta
    (path / "raw").mkdir(parents=True, exist_ok=True)
    return path


async def _open(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightError:
        pass


async def _pause(headed: bool, pause: bool) -> None:
    if headed and pause:
        await asyncio.to_thread(input, "\nNavegador aberto para inspeção. Pressione Enter para fechar…")


async def discover(config: Config, url: str, *, headed: bool, pause: bool = False) -> list[NavItem]:
    """`spa-extract map`: percorre o menu como a extração faria (abrindo cada grupo), sem extrair conteúdo."""
    ensure_allowed(url, config)
    async with open_browser(config, url, headed=headed) as (context, page):
        await _open(page, url)
        page = await run_start_actions(context, page, config, config.start_click)
        items: list[NavItem] = []

        async def record(item: NavItem) -> None:
            items.append(item)

        try:
            await MenuWalker(page, config).walk(on_leaf=record, on_group=record)
        except RuntimeError:
            return []
        await _pause(headed, pause)
        return items


def _front_matter(item: NavItem, url: str, location: ContentLocation | None) -> str:
    title = item.title.replace('"', "'")
    module = f'module: "{item.group.replace(chr(34), chr(39))}"\n' if item.group else ""
    return (
        "---\n"
        f'title: "{title}"\n'
        f"{module}"
        f"source: {url}\n"
        f"nav_index: {item.index}\n"
        f"nav_depth: {item.depth}\n"
        f"frame: {location.frame.url if location else ''}\n"
        f"extracted_at: {datetime.now(UTC).isoformat(timespec='seconds')}\n"
        "---\n\n"
    )


async def _extract_item(
    page: Page, config: Config, walker: MenuWalker, item: NavItem, previous_hash: str | None
) -> tuple[str, str, ContentLocation | None]:
    target = await walker.locate(item.path)  # reabre o caminho (Módulo › Unidade) se o menu se fechou
    if target is None:
        raise LookupError("item sumiu do menu")
    await target.scroll_into_view_if_needed()
    # o que está na tela antes do clique: o conteúdo novo precisa ser diferente disso (lição anterior ou a que o
    # player abriu sozinho, de cache)
    before = await content_text(await locate_content(page, config, walker.container, walker.frame))
    baseline = hashlib.sha1(before.encode("utf-8")).hexdigest() if before else previous_hash
    await polite_pause(config.timing.pre_click_delay_s)
    await target.click()

    location: ContentLocation | None = None

    async def current_text() -> str:
        nonlocal location
        location = await locate_content(page, config, walker.container, walker.frame)
        return await content_text(location)

    stable_hash = await wait_until_stable(page, config, baseline, current_text)
    if location is None:
        raise LookupError("container de conteúdo não encontrado")
    markdown = to_markdown(strip_noise(await serialize(location), config))
    if not markdown.strip():
        raise ValueError("conteúdo vazio depois da limpeza")
    return markdown, stable_hash, location


class _LimitReached(Exception):
    pass


async def extract(
    config: Config,
    url: str,
    *,
    headed: bool,
    only: str | None = None,
    limit: int | None = None,
    pause: bool = False,
) -> RunReport:
    """`spa-extract extract`: um .md por item do menu em output/<host>/<data>/raw, com manifesto e log."""
    out = run_dir(config, url)
    report = RunReport(url=url, started_at=datetime.now(UTC).isoformat(timespec="seconds"), output=str(out))
    ensure_allowed(url, config)
    async with open_browser(config, url, headed=headed) as (context, page):
        await _open(page, url)
        page = await run_start_actions(context, page, config, config.start_click)
        walker = MenuWalker(page, config)
        state: dict[str, object] = {"previous_hash": None}

        async def handle(item: NavItem) -> None:
            path_text = " › ".join(item.path)
            if only and not re.search(only, path_text, re.IGNORECASE):
                return
            if limit and len(report.items) >= limit:
                raise _LimitReached
            entry: dict = {"index": item.index, "path": path_text, "title": item.title, "status": "pending"}
            for attempt in range(1, config.timing.retries + 2):
                try:
                    markdown, digest, location = await _extract_item(
                        page,
                        config,
                        walker,
                        item,
                        state["previous_hash"],  # type: ignore[arg-type]
                    )
                    state["previous_hash"] = digest
                    name = f"{item.index:03d}-{slugify(item.title)}.md"
                    (out / "raw" / name).write_text(_front_matter(item, url, location) + markdown, encoding="utf-8")
                    entry.update(status="ok", file=f"raw/{name}", chars=len(markdown), attempts=attempt)
                    log.info("✓ %03d %s (%s caracteres)", item.index, path_text, len(markdown))
                    break
                except (PlaywrightError, LookupError, TimeoutError, ValueError) as error:
                    entry.update(status="error", error=f"{type(error).__name__}: {error}", attempts=attempt)
                    log.warning("✗ %03d %s — tentativa %s: %s", item.index, path_text, attempt, error)
                    if attempt <= config.timing.retries:
                        await polite_pause((config.timing.min_delay_s, config.timing.max_delay_s))
            report.items.append(entry)
            report.save(out / "manifest.json")
            await polite_pause((config.timing.min_delay_s, config.timing.max_delay_s))

        try:
            await walker.walk(on_leaf=handle, on_group=handle if config.selectors.include_groups else None)
        except _LimitReached:
            log.info("limite de %s item(ns) atingido", limit)
        await _pause(headed, pause)
    return report
