"""`spa-extract login`: a pessoa faz o login no navegador visível; a sessão (cookies + storage) fica salva para as
próximas execuções. O extrator nunca digita nem lê credenciais."""

from __future__ import annotations

import asyncio
import os

from .browser import open_browser, session_file
from .config import Config


async def login(config: Config, url: str) -> str:
    state = session_file(config, url)
    state.parent.mkdir(parents=True, exist_ok=True)
    async with open_browser(config, url, headed=True, use_session=False) as (context, page):
        await page.goto(url)
        print(
            "\nFaça o login na janela do navegador e abra a página inicial do conteúdo.\n"
            "Quando terminar, volte aqui e pressione Enter para salvar a sessão…",
            flush=True,
        )
        await asyncio.to_thread(input)
        await context.storage_state(path=str(state))
    os.chmod(state, 0o600)  # sessão = credencial: só o dono lê
    return str(state)
