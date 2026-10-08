"""Navegação em profundidade pelo menu: sempre do primeiro item, abrindo cada grupo (módulo → unidade → …) e visitando
seus tópicos antes de passar ao próximo — como uma pessoa faria. Funciona com menus "sanfona" (abrir um módulo fecha
o outro) e com players que abrem na última lição acessada: a ordem vem do menu, não de onde o player parou.

Cada item é identificado pelo CAMINHO de títulos (Módulo › Unidade › Lição): reencontrado a cada passo, porque o DOM
de uma SPA é redesenhado o tempo todo e títulos se repetem entre módulos ("Resumo", "Quiz").

O grupo de cada item vem do DOM (o painel do módulo que contém a lição) e, quando o menu não marca nada, do próprio
clique: um tópico que, ao ser aberto, revela subitens passa a ser grupo (pasta)."""

from __future__ import annotations

import asyncio
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
    # posição de cada nível entre os irmãos no menu (1, 3, 2 = 1º módulo › 3ª unidade › 2º tópico): nomeia as pastas
    position: tuple[int, ...] = ()

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
    in_page: bool = False  # âncora para uma seção da página aberta (sumário da lição), não um tópico


@dataclass
class _Snapshot:
    frame: Frame
    container: str
    entries: list[_Entry]

    def find(self, path: Path) -> _Entry | None:
        return next((e for e in self.entries if e.path == path), None)

    def children(self, path: Path) -> list[_Entry]:
        return [e for e in self.entries if e.path[:-1] == path and not (path and e.in_page)]


def _with_paths(raw: list[dict], known_groups: set[Path]) -> list[_Entry]:
    """Caminho de cada item pela cadeia de pais que o JS apontou (Módulo › Unidade › Lição). É grupo quem o menu marca,
    quem tem filhos visíveis ou quem já se revelou grupo ao ser clicado (`known_groups`)."""

    def path_of(index: int) -> Path:
        chain: list[str] = []
        seen: set[int] = set()
        current: int | None = index
        while current is not None and current not in seen and 0 <= current < len(raw):
            seen.add(current)
            chain.append(raw[current]["title"])
            current = raw[current].get("parent")
        return tuple(reversed(chain))

    parents = {item.get("parent") for item in raw}
    entries: list[_Entry] = []
    for index, item in enumerate(raw):
        path = path_of(index)
        entries.append(
            _Entry(
                title=item["title"],
                selector=item["selector"],
                depth=len(path) - 1,
                href=item.get("href"),
                is_group=bool(item.get("group")) or index in parents or path in known_groups,
                path=path,
                in_page=bool(item.get("inPage")),
            )
        )
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
        # tópicos que revelaram subitens ao serem clicados: continuam grupos mesmo quando o menu os fecha de novo
        self.known_groups: set[Path] = set()

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
                    "groupSelector": selectors.expanders,
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
        return _Snapshot(
            frame=frame, container=data["container"], entries=_with_paths(data["items"], self.known_groups)
        )

    async def _first_snapshot(self) -> _Snapshot | None:
        """O menu do player pode aparecer (ou terminar de ser desenhado) segundos depois da página: só fixa o menu quando
        três leituras seguidas concordam (mesmo container, mesmos itens), até o tempo de navegação."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.timing.navigation_timeout_ms / 1000
        readings: list[tuple[str, int] | None] = []
        while True:
            self.container = self.config.selectors.nav_container or None  # ainda não fixado: reavalia a cada leitura
            snap = await self.snapshot()
            readings.append((snap.container, len(snap.entries)) if snap and snap.entries else None)
            stable = len(readings) >= 3 and readings[-1] is not None and len(set(readings[-3:])) == 1
            if stable or loop.time() >= deadline:
                if snap:
                    log.info("menu encontrado (%s) com %s item(ns) visível(is)", snap.container, len(snap.entries))
                return snap
            await asyncio.sleep(1)

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
                toggle = snap.frame.locator(entry.selector)
                summary = toggle.locator(":scope > summary")  # <details>: quem abre é o <summary>
                try:
                    if await summary.count():
                        toggle = summary
                    await toggle.first.click()
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
            if await locator.count() != 1:
                return snap.frame.locator(snap.container).get_by_text(entry.title, exact=True).first
            # item que embrulha um único link (ex.: <li> com caixa de progresso + <a>): clica no link, não no meio do <li>
            link = locator.locator("a[href]")
            return link if await link.count() == 1 else locator
        except PlaywrightError:
            return None

    async def click(self, path: Path) -> bool:
        """Clica no item sem extrair e espera o menu reagir (o `map` usa para achar subitens que só aparecem depois)."""
        target = await self.locate(path)
        if target is None:
            return False
        try:
            await target.scroll_into_view_if_needed()
            await polite_pause(self.config.timing.pre_click_delay_s)
            await target.click()
        except PlaywrightError as error:
            log.warning("não clicou em %s: %s", " › ".join(path), error)
            return False
        if self.frame:
            await self._settle(self.frame)
        return True

    async def _has_children(self, path: Path, *, open_group: bool) -> bool:
        snap = await self.ensure_open(path) if open_group else await self.snapshot()
        return bool(snap and snap.children(path))

    async def walk(
        self,
        on_leaf: Callable[[NavItem], Awaitable[None]],
        on_group: Callable[[NavItem], Awaitable[None]] | None = None,
        on_promoted: Callable[[NavItem], Awaitable[None]] | None = None,
        max_visits: int = 2_000,
    ) -> None:
        """`on_promoted` é chamado quando um item tratado como tópico revela subitens ao ser clicado: ele vira grupo e
        os subitens são visitados em seguida."""

        async def visit(path: Path, position: tuple[int, ...]) -> None:
            snap = await self.ensure_open(path) if path else await self._first_snapshot()
            if snap is None:
                raise RuntimeError("nenhum menu encontrado — ajuste selectors.nav_container no extractor.toml")
            for number, child in enumerate(snap.children(path), 1):
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
                    position=(*position, number),
                )
                if child.is_group and await self._has_children(child.path, open_group=True):
                    if on_group:
                        await on_group(item)
                    await visit(child.path, item.position)  # entra no grupo antes de seguir para o irmão seguinte
                    continue
                item.is_group = False  # tópico (ou grupo que abriu vazio): extraído como arquivo
                await on_leaf(item)
                if await self._has_children(child.path, open_group=False):
                    # o clique revelou subitens que o menu não anunciava (lista carregada sob demanda): vira pasta
                    self.known_groups.add(child.path)
                    item.is_group = True
                    log.info("%s revelou subitens: tratado como grupo", " › ".join(child.path))
                    if on_promoted:
                        await on_promoted(item)
                    await visit(child.path, item.position)

        await visit((), ())
