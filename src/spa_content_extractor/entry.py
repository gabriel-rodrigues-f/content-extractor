"""Ação de entrada: depois de abrir a URL, clicar em botões pelo texto (ex.: "Resume learning") até chegar ao player.
O clique pode navegar na mesma aba ou abrir outra — nos dois casos a extração segue na página certa."""

from __future__ import annotations

import logging

from playwright.async_api import BrowserContext, Locator, Page
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .browser import all_frames, polite_pause
from .config import Config

log = logging.getLogger(__name__)


async def _find_clickable(page: Page, text: str) -> Locator | None:
    """Procura em todos os frames: botão, depois link, depois qualquer elemento visível com o texto."""
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


async def _settle(page: Page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightError:
        pass


async def run_start_actions(context: BrowserContext, page: Page, config: Config, texts: list[str]) -> Page:
    for text in texts:
        target = None
        for _ in range(10):  # o botão pode demorar a aparecer numa SPA
            target = await _find_clickable(page, text)
            if target:
                break
            await page.wait_for_timeout(1_000)
        if target is None:
            raise LookupError(f'botão "{text}" não encontrado na página de entrada')
        await polite_pause(config.timing.pre_click_delay_s)
        try:
            async with context.expect_page(timeout=4_000) as new_page:
                await target.click()
            page = await new_page.value  # abriu em outra aba
            log.info('"%s" abriu uma nova aba: %s', text, page.url)
        except PlaywrightTimeoutError:
            log.info('"%s" clicado; seguindo na mesma aba (%s)', text, page.url)
        await _settle(page)
    return page
