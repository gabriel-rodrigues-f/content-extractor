"""Mapeamento da navegação: acha o menu (em qualquer frame), abre grupos recolhidos e lista os itens; depois
reencontra cada item para clicar, mesmo que o DOM tenha sido redesenhado entre um clique e outro."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Locator, Page

from . import page_scripts
from .browser import all_frames, polite_pause, safe_eval
from .config import Config

log = logging.getLogger(__name__)


@dataclass
class NavItem:
    index: int
    title: str
    selector: str
    depth: int
    href: str | None
    frame_url: str
    # grupo = cabeçalho que abre/fecha subitens: vira contexto (caminho "Módulo › Unidade"); só é extraído com
    # include_groups
    is_group: bool = False
    group: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NavMap:
    container: str
    frame: Frame
    items: list[NavItem]


async def _discover_in_frames(page: Page, config: Config) -> tuple[Frame, dict] | None:
    selectors = config.selectors
    best: tuple[Frame, dict] | None = None
    for frame in all_frames(page):
        found = await safe_eval(
            frame,
            page_scripts.DISCOVER_NAV,
            {
                "fixedContainer": selectors.nav_container,
                "candidates": selectors.nav_container_candidates,
                "itemSelector": selectors.nav_item,
                "noiseTexts": [t for t in selectors.noise_texts],
            },
        )
        if isinstance(found, dict) and (best is None or found["score"] > best[1]["score"]):
            best = (frame, found)
    return best


def _expand_arg(container: str, config: Config) -> dict:
    return {"containerSelector": container, "expanders": config.selectors.expanders}


async def map_navigation(page: Page, config: Config) -> NavMap | None:
    found = await _discover_in_frames(page, config)
    if found is None:
        return None
    frame, data = found
    if config.selectors.expand_collapsed:
        # abre o menu nível por nível (módulo → unidade → lição) até não aparecer item novo
        seen = len(data["items"])
        for round_ in range(1, config.selectors.max_expand_rounds + 1):
            opened = await safe_eval(frame, page_scripts.EXPAND_COLLAPSED, _expand_arg(data["container"], config))
            if not opened:
                break
            await polite_pause((0.5, 1.0))
            await safe_eval(frame, page_scripts.WAIT_QUIET, {"quietMs": 500, "timeoutMs": 5_000})  # filhos sob demanda
            refreshed = await _discover_in_frames(page, config)
            if refreshed is None:
                break
            frame, data = refreshed
            log.info("rodada %s: abri %s grupo(s); %s item(ns) no menu", round_, opened, len(data["items"]))
            if len(data["items"]) == seen:
                break
            seen = len(data["items"])
    items: list[NavItem] = []
    groups: dict[int, str] = {}  # profundidade → título do grupo aberto mais recente nessa profundidade
    for i, raw in enumerate(data["items"]):
        is_group = bool(raw.get("group"))
        path = " › ".join(groups[d] for d in sorted(groups) if d < raw["depth"]) or None
        items.append(
            NavItem(
                index=i + 1,
                title=raw["title"],
                selector=raw["selector"],
                depth=raw["depth"],
                href=raw.get("href"),
                frame_url=frame.url,
                is_group=is_group,
                group=path,
            )
        )
        if is_group:
            groups = {d: t for d, t in groups.items() if d < raw["depth"]}
            groups[raw["depth"]] = raw["title"]
    return NavMap(container=data["container"], frame=frame, items=items)


async def reopen_groups(nav: NavMap, config: Config) -> None:
    """Clicar numa lição pode recolher o módulo em alguns menus: reabre antes de procurar o próximo item."""
    if not config.selectors.expand_collapsed or nav.frame.is_detached():
        return
    if await safe_eval(nav.frame, page_scripts.EXPAND_COLLAPSED, _expand_arg(nav.container, config)):
        await polite_pause((0.3, 0.6))


async def locate_item(page: Page, nav: NavMap, item: NavItem) -> Locator | None:
    """Reencontra o item: pelo caminho CSS gravado se o texto ainda bate; senão pelo texto dentro do menu (classes e
    posições mudam em SPAs). Se o frame do menu foi recriado, procura de novo pelo mesmo endereço."""
    frame = nav.frame
    if frame.is_detached():
        frame = next((f for f in all_frames(page) if f.url == item.frame_url), page.main_frame)
        nav.frame = frame
    try:
        by_path = frame.locator(item.selector)
        if await by_path.count() == 1 and (await by_path.inner_text()).strip() == item.title:
            return by_path
    except PlaywrightError:
        pass
    try:
        by_text = frame.locator(nav.container).get_by_text(item.title, exact=True)
        if await by_text.count() >= 1:
            return by_text.first
    except PlaywrightError:
        pass
    log.warning("item %s (%s) não encontrado no menu", item.index, item.title)
    return None
