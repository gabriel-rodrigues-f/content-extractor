"""Navegador, sessão salva e utilidades de frames (iframes aninhados e de outra origem)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Frame, Page, async_playwright
from playwright.async_api import Error as PlaywrightError

from . import page_scripts
from .config import Config

log = logging.getLogger(__name__)


def session_file(config: Config, url: str) -> Path:
    """Sessão (cookies + storage) por host, gravada pelo `spa-extract login`. Contém credenciais de sessão: fica
    fora do git (.auth/ no .gitignore) e com permissão 600."""
    host = urlparse(url).netloc.replace(":", "_") or "local"
    return config.auth_dir / f"{host}.json"


@asynccontextmanager
async def open_browser(
    config: Config, url: str, *, headed: bool, use_session: bool = True
) -> AsyncIterator[tuple[BrowserContext, Page]]:
    state = session_file(config, url)
    async with async_playwright() as pw:
        launch = {"headless": not headed}
        if config.browser_channel and config.browser_channel != "chromium":
            launch["channel"] = config.browser_channel
        browser = await pw.chromium.launch(**launch)
        context = await browser.new_context(
            storage_state=str(state) if use_session and state.exists() else None,
            locale=config.locale,
            viewport={"width": config.viewport[0], "height": config.viewport[1]},
        )
        context.set_default_timeout(config.timing.navigation_timeout_ms)
        page = await context.new_page()
        try:
            yield context, page
        finally:
            await context.close()
            await browser.close()


def all_frames(page: Page) -> list[Frame]:
    """Frame principal + todos os iframes (inclusive aninhados e de outra origem), ignorando os desanexados."""
    return [f for f in page.frames if not f.is_detached()]


async def safe_eval(frame: Frame, script: str, arg: object = None) -> object | None:
    """Avalia num frame sem derrubar a extração: frames somem e mudam no meio de uma SPA."""
    try:
        return await frame.evaluate(script, arg)
    except PlaywrightError as error:
        log.debug("frame %s ignorado: %s", frame.url, error)
        return None


async def polite_pause(bounds: tuple[float, float]) -> None:
    """Pausa aleatória entre ações: ritmo humano e carga baixa no servidor (não é técnica de evasão)."""
    await asyncio.sleep(random.uniform(*bounds))


async def wait_until_stable(page: Page, config: Config, previous_hash: str | None, content_text) -> str:
    """Espera o conteúdo estar renderizado de verdade, não só carregado:
    1. rede ociosa (best effort — SPAs com polling nunca ficam ociosas);
    2. nenhum indicador de carregamento visível em nenhum frame;
    3. `quiet_ms` sem mutações no DOM em todos os frames;
    4. o texto do conteúdo diferente do item anterior (evita salvar a lição velha) e igual em duas leituras seguidas.
    Devolve o hash do texto estável."""
    timing = config.timing
    deadline = asyncio.get_running_loop().time() + timing.stable_timeout_ms / 1000
    try:
        await page.wait_for_load_state("networkidle", timeout=min(5_000, timing.stable_timeout_ms))
    except PlaywrightError:
        pass
    last_hash = None
    while True:
        remaining_ms = max(200, int((deadline - asyncio.get_running_loop().time()) * 1000))
        loading = await asyncio.gather(
            *(safe_eval(f, page_scripts.IS_LOADING, config.selectors.loading) for f in all_frames(page))
        )
        if not any(loading):
            await asyncio.gather(
                *(
                    safe_eval(
                        f, page_scripts.WAIT_QUIET, {"quietMs": timing.quiet_ms, "timeoutMs": min(remaining_ms, 5_000)}
                    )
                    for f in all_frames(page)
                )
            )
            text = await content_text()
            current = hashlib.sha1(text.encode("utf-8")).hexdigest() if text else None
            if current and current != previous_hash and current == last_hash:
                return current
            last_hash = current
        if asyncio.get_running_loop().time() >= deadline:
            if last_hash:
                log.warning(
                    "conteúdo não estabilizou em %s ms; seguindo com a última leitura", timing.stable_timeout_ms
                )
                return last_hash
            raise TimeoutError("o conteúdo não apareceu dentro do tempo limite")
        await asyncio.sleep(0.3)
