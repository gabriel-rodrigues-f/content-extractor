"""Navegação em profundidade pelo menu: sempre do primeiro item, abrindo cada grupo (módulo → unidade → …) e visitando
seus tópicos antes de passar ao próximo — como uma pessoa faria. Funciona com menus "sanfona" (abrir um módulo fecha
o outro) e com players que abrem na última lição acessada: a ordem vem do menu, não de onde o player parou.

Cada item é identificado pelo CAMINHO de títulos (Módulo › Unidade › Lição): reencontrado a cada passo, porque o DOM
de uma SPA é redesenhado o tempo todo e títulos se repetem entre módulos ("Resumo", "Quiz")."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame, Locator, Page

from . import page_scripts
from .browser import all_frames, polite_pause, safe_eval
from .config import Config

log = logging.getLogger(__name__)

Path = tuple[str, ...]


@dataclass
class NavItem:
    index: int
    title: str
    selector: str
    depth: int
    href: str | None
    frame_url: str
    # grupo = cabeçalho que abre/fecha subitens: vira contexto ("Módulo › Unidade"); só é extraído com include_groups
    is_group: bool = False
    group: str | None = None
    path: Path = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Entry:
    title: str
    selector: str
    depth: int
    href: str | None
    is_group: bool
    path: Path


@dataclass
class _Snapshot:
    frame: Frame
    container: str
    entries: list[_Entry]

    def find(self, path: Path) -> _Entry | None:
        return next((e for e in self.entries if e.path == path), None)

    def children(self, path: Path) -> list[_Entry]:
        return [e for e in self.entries if e.path[:-1] == path]


def _with_paths(raw: list[dict]) -> list[_Entry]:
    """Caminho de cada item pela profundidade e pela ordem no DOM: o grupo aberto mais próximo acima é o pai."""
    stack: list[_Entry] = []
    entries: list[_Entry] = []
    for item in raw:
        while stack and stack[-1].depth >= item["depth"]:
            stack.pop()
        entry = _Entry(
            title=item["title"],
            selector=item["selector"],
            depth=item["depth"],
            href=item.get("href"),
            is_group=bool(item.get("group")),
            path=(*(s.title for s in stack), item["title"]),
        )
        entries.append(entry)
        if entry.is_group:
            stack.append(entry)
    return entries


class MenuWalker:
    """Percorre o menu em profundidade. `walk` chama `on_group` ao entrar num grupo e `on_leaf` em cada tópico; quem
    trata o tópico usa `locate(path)` para obter o item com o caminho já aberto, pronto para clicar."""

    def __init__(self, page: Page, config: Config) -> None:
        self.page = page
        self.config = config
        self.container: str | None = config.selectors.nav_container or None
        self.frame: Frame | None = None  # frame onde o menu mora (o conteúdo é procurado fora dele)
        self.visits = 0

    async def snapshot(self) -> _Snapshot | None:
        selectors = self.config.selectors
        best: tuple[Frame, dict] | None = None
        for frame in all_frames(self.page):
            found = await safe_eval(
                frame,
                page_scripts.DISCOVER_NAV,
                {
                    # depois da primeira leitura o menu fica fixo: sem isso, um submenu aberto podia "virar" o menu
                    "fixedContainer": self.container or "",
                    "candidates": selectors.nav_container_candidates,
                    "itemSelector": selectors.nav_item,
                    "noiseTexts": list(selectors.noise_texts),
                },
            )
            if isinstance(found, dict) and (best is None or found["score"] > best[1]["score"]):
                best = (frame, found)
        if best is None:
            return None
        frame, data = best
        self.container = data["container"]
        self.frame = frame
        return _Snapshot(frame=frame, container=data["container"], entries=_with_paths(data["items"]))

    async def _settle(self, frame: Frame) -> None:
        await polite_pause((0.4, 0.8))
        await safe_eval(frame, page_scripts.WAIT_QUIET, {"quietMs": 500, "timeoutMs": 5_000})

    async def ensure_open(self, path: Path) -> _Snapshot | None:
        """Abre, de cima para baixo, cada grupo do caminho que estiver fechado (o menu pode ter se fechado sozinho)."""
        snap = await self.snapshot()
        for k in range(1, len(path) + 1):
            if snap is None:
                return None
            entry = snap.find(path[:k])
            if entry is None:
                log.warning("grupo não encontrado no menu: %s", " › ".join(path[:k]))
                return snap
            if not entry.is_group:
                continue
            state = await safe_eval(snap.frame, page_scripts.GROUP_STATE, entry.selector)
            if state == "closed" or (state == "unknown" and not snap.children(entry.path)):
                try:
                    await snap.frame.locator(entry.selector).first.click()
                except PlaywrightError as error:
                    log.warning("não abriu o grupo %s: %s", entry.title, error)
                    continue
                await self._settle(snap.frame)
                snap = await self.snapshot()
        return snap

    async def locate(self, path: Path) -> Locator | None:
        """O item do caminho, com os grupos acima dele abertos, pronto para clicar."""
        snap = await self.ensure_open(path[:-1])
        entry = snap.find(path) if snap else None
        if snap is None or entry is None:
            return None
        locator = snap.frame.locator(entry.selector)
        try:
            if await locator.count() == 1:
                return locator
            return snap.frame.locator(snap.container).get_by_text(entry.title, exact=True).first
        except PlaywrightError:
            return None

    async def walk(
        self,
        on_leaf: Callable[[NavItem], Awaitable[None]],
        on_group: Callable[[NavItem], Awaitable[None]] | None = None,
        max_visits: int = 2_000,
    ) -> None:
        async def visit(path: Path) -> None:
            snap = await self.ensure_open(path) if path else await self.snapshot()
            if snap is None:
                raise RuntimeError("nenhum menu encontrado — ajuste selectors.nav_container no extractor.toml")
            for child in snap.children(path):
                if self.visits >= max_visits:
                    log.warning("limite de %s itens atingido; parando", max_visits)
                    return
                self.visits += 1
                item = NavItem(
                    index=self.visits,
                    title=child.title,
                    selector=child.selector,
                    depth=child.depth,
                    href=child.href,
                    frame_url=snap.frame.url,
                    is_group=child.is_group,
                    group=" › ".join(child.path[:-1]) or None,
                    path=child.path,
                )
                if child.is_group:
                    if on_group:
                        await on_group(item)
                    await visit(child.path)  # entra no grupo antes de seguir para o irmão seguinte
                else:
                    await on_leaf(item)

        await visit(())
