"""Ação de entrada: abrir a URL, clicar em botões pelo texto (ex.: "Resume Learning") e só seguir quando a página do
conteúdo tiver de fato aberto. Numa SPA o clique não recarrega a página — a troca é por JavaScript, às vezes depois de
uma chamada ao servidor — então "terminou de carregar" não serve de sinal: o extrator espera uma TRANSIÇÃO (outra
URL, outra aba, ou o botão sumiu e o texto da página mudou) e, depois, o menu do player."""

from __future__ import annotations

import asyncio
import hashlib
import logging

from playwright.async_api import BrowserContext, Locator, Page
from playwright.async_api import Error as PlaywrightError

from .browser import all_frames, polite_pause
from .config import Config

log = logging.getLogger(__name__)

async def _find_clickable(page: Page, text: str) -> Locator | None:
    """Procura em todos os frames: botão, depois link, depois qualquer elemento visível com o texto (sem diferenciar
    maiúsculas)."""
    for frame in all_frames(page):
        for candidate in (
            frame.get_by_role("button", name=text),
            frame.get_by_role("link", name=text),
            frame.get_by_text(text),
        ):
            try:
                count = await candidate.count()
                for i in range(count):
                    if await candidate.nth(i).is_visible():
                        return candidate.nth(i)
            except PlaywrightError:
                continue
    return None


async def _fingerprint(page: Page) -> str:
    try:
        text = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
    except PlaywrightError:
        return ""
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()


async def _settle(page: Page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightError:
        pass


async def _wait_transition(context: BrowserContext, page: Page, target: Locator, text: str, timeout_s: int) -> Page:
    """Clica e espera a página mudar de verdade. Devolve a página onde a extração deve seguir."""
    before_url = page.url
    before_print = await _fingerprint(page)
    pages_before = set(context.pages)
    await target.click()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        opened = [p for p in context.pages if p not in pages_before and not p.is_closed()]
        if opened:
            new_page = opened[-1]
            await new_page.bring_to_front()
            log.info('"%s" abriu uma nova aba: %s', text, new_page.url)
            return new_page
        if page.url != before_url:
            log.info('"%s" levou a outra página: %s', text, page.url)
            return page
        try:
            gone = not await target.is_visible()
        except PlaywrightError:
            gone = True
        if gone and await _fingerprint(page) != before_print:
            log.info('"%s" trocou o conteúdo da página (mesma URL)', text)
            return page
        await asyncio.sleep(0.5)
    raise LookupError(
        f'cliquei em "{text}", mas a página não mudou em {timeout_s} s — '
        "confira se o botão leva ao conteúdo (ou use --headed para ver o que acontece)"
    )


async def _wait_for_marker(page: Page, marker: str, timeout_ms: int) -> None:
    """Espera um texto ou seletor que só existe na página do conteúdo (opção --wait-for / start_wait_for)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000
    while loop.time() < deadline:
        for frame in all_frames(page):
            for candidate in (frame.locator(marker), frame.get_by_text(marker)):
                try:
                    if await candidate.count() and await candidate.first.is_visible():
                        log.info('página do conteúdo reconhecida por "%s"', marker)
                        return
                except PlaywrightError:
                    continue
        await asyncio.sleep(0.5)
    raise LookupError(f'a página do conteúdo não mostrou "{marker}" em {timeout_ms // 1000} s')


async def run_start_actions(context: BrowserContext, page: Page, config: Config, texts: list[str]) -> Page:
    if not texts:
        log.info("sem ação de entrada (--start-click): a extração começa na página que abriu")
    for text in texts:
        target = None
        for _ in range(15):  # o botão pode demorar a aparecer numa SPA
            target = await _find_clickable(page, text)
            if target:
                break
            await page.wait_for_timeout(1_000)
        if target is None:
            raise LookupError(f'botão "{text}" não encontrado na página de entrada')
        await polite_pause(config.timing.pre_click_delay_s)
        log.info('clicando em "%s" e aguardando a página do conteúdo…', text)
        page = await _wait_transition(context, page, target, text, config.timing.transition_timeout_s)
        await _settle(page)
    if config.start_wait_for:
        await _wait_for_marker(page, config.start_wait_for, config.timing.navigation_timeout_ms)
    if texts or config.start_wait_for:
        log.info("página do conteúdo carregada: %s", page.url)
    return page
