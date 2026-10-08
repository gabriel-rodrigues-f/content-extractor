"""Fluxo de extração: abrir → mapear o menu → para cada item, clicar, esperar estabilizar, extrair e salvar."""

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
from .navigation import NavItem, NavMap, locate_item, map_navigation, reopen_groups
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
    """`spa-extract map`: só o mapa, para revisar antes de extrair (e ajustar seletores se precisar)."""
    ensure_allowed(url, config)
    async with open_browser(config, url, headed=headed) as (context, page):
        await _open(page, url)
        page = await run_start_actions(context, page, config, config.start_click)
        nav = await map_navigation(page, config)
        await _pause(headed, pause)
        return nav.items if nav else []


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
    page: Page, config: Config, nav: NavMap, item: NavItem, previous_hash: str | None
) -> tuple[str, str, ContentLocation | None]:
    await reopen_groups(nav, config)
    target = await locate_item(page, nav, item)
    if target is None:
        raise LookupError("item sumiu do menu")
    await target.scroll_into_view_if_needed()
    # o que está na tela antes do clique: o conteúdo novo precisa ser diferente disso (lição anterior ou placeholder)
    before = await content_text(await locate_content(page, config, nav.container, nav.frame))
    baseline = hashlib.sha1(before.encode("utf-8")).hexdigest() if before else previous_hash
    await polite_pause(config.timing.pre_click_delay_s)
    await target.click()

    location: ContentLocation | None = None

    async def current_text() -> str:
        nonlocal location
        location = await locate_content(page, config, nav.container, nav.frame)
        return await content_text(location)

    stable_hash = await wait_until_stable(page, config, baseline, current_text)
    if location is None:
        raise LookupError("container de conteúdo não encontrado")
    markdown = to_markdown(strip_noise(await serialize(location), config))
    if not markdown.strip():
        raise ValueError("conteúdo vazio depois da limpeza")
    return markdown, stable_hash, location


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
        nav = await map_navigation(page, config)
        if nav is None:
            raise RuntimeError("nenhum menu encontrado — ajuste selectors.nav_container no extractor.toml")
        items = [
            i
            for i in nav.items
            if (config.selectors.include_groups or not i.is_group)
            and (not only or re.search(only, f"{i.group or ''} {i.title}", re.IGNORECASE))
        ]
        if limit:
            items = items[:limit]
        log.info("menu %s com %s item(ns); extraindo %s", nav.container, len(nav.items), len(items))
        previous_hash: str | None = None
        for item in items:
            entry = {"index": item.index, "title": item.title, "status": "pending"}
            for attempt in range(1, config.timing.retries + 2):
                try:
                    markdown, previous_hash, location = await _extract_item(page, config, nav, item, previous_hash)
                    name = f"{item.index:03d}-{slugify(item.title)}.md"
                    (out / "raw" / name).write_text(_front_matter(item, url, location) + markdown, encoding="utf-8")
                    entry.update(status="ok", file=f"raw/{name}", chars=len(markdown), attempts=attempt)
                    log.info("✓ %03d %s (%s caracteres)", item.index, item.title, len(markdown))
                    break
                except (PlaywrightError, LookupError, TimeoutError, ValueError) as error:
                    entry.update(status="error", error=f"{type(error).__name__}: {error}", attempts=attempt)
                    log.warning("✗ %03d %s — tentativa %s: %s", item.index, item.title, attempt, error)
                    if attempt <= config.timing.retries:
                        # o menu pode ter sido redesenhado: mapeia de novo antes de tentar outra vez
                        refreshed = await map_navigation(page, config)
                        if refreshed:
                            nav = refreshed
                        await polite_pause((config.timing.min_delay_s, config.timing.max_delay_s))
            report.items.append(entry)
            report.save(out / "manifest.json")
            await polite_pause((config.timing.min_delay_s, config.timing.max_delay_s))
        await _pause(headed, pause)
    return report
