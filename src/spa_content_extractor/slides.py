"""Lições em player de slides (Articulate Storyline: story.html com botões #prev/#next). O texto de cada slide só existe
enquanto ele está na tela, numa camada de acessibilidade invisível — por isso o HTML serializado sai vazio. Aqui o
extrator avança pelo "next" até o fim e junta o texto de cada slide numa seção."""

from __future__ import annotations

import asyncio
import re
from collections import Counter

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame

_STORY = re.compile(r"/story(_html5)?\.html", re.IGNORECASE)
NOTE = "<!-- Lição interativa (player de slides): texto coletado slide a slide. -->"


async def is_slide_player(frame: Frame) -> bool:
    if _STORY.search(frame.url):
        return True
    try:
        return await frame.locator("button#next.cs-button").count() > 0
    except PlaywrightError:
        return False


async def _text(frame: Frame) -> str:
    try:
        text = await frame.evaluate("() => (document.body && document.body.innerText) || ''")
    except PlaywrightError:
        return ""
    return text if isinstance(text, str) else ""


async def _next_enabled(frame: Frame) -> bool:
    button = frame.locator("#next").first
    try:
        if not await button.count() or not await button.is_visible() or await button.is_disabled():
            return False
        classes = await button.get_attribute("class") or ""
        return "cs-disabled" not in classes and await button.get_attribute("aria-disabled") != "true"
    except PlaywrightError:
        return False


async def _wait_change(frame: Frame, before: str, timeout_s: float = 10) -> str | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        await asyncio.sleep(0.4)
        now = await _text(frame)
        if now.strip() and now != before:
            await asyncio.sleep(0.8)  # o slide termina de montar
            return await _text(frame)
    return None


def compose(slides: list[str]) -> str:
    """Uma seção por slide ("slide: <título>" vira o título). Linhas que aparecem em quase todos os slides são do
    player (menu lateral, "Back to top", rótulos de botão), não do conteúdo."""
    pages = [[line.strip() for line in slide.splitlines() if line.strip()] for slide in slides]
    pages = [page for page in pages if page]
    if not pages:
        return ""
    counts = Counter(line for page in pages for line in set(page))
    chrome = {line for line, n in counts.items() if len(pages) > 1 and n >= max(2, 0.8 * len(pages))}
    sections = []
    for number, lines in enumerate(pages, 1):
        title = next((line[6:].strip() for line in lines if line.lower().startswith("slide:")), f"Slide {number}")
        body = [line for line in dict.fromkeys(lines) if line not in chrome and not line.lower().startswith("slide:")]
        sections.append(f"## {title}\n\n" + "\n\n".join(body))
    return NOTE + "\n\n" + "\n\n".join(sections) + "\n"


async def slides_markdown(frame: Frame, max_slides: int = 200) -> str:
    text = await _text(frame)
    slides = [text]
    for _ in range(max_slides - 1):
        if not await _next_enabled(frame):
            break
        try:
            await frame.locator("#next").first.click()
        except PlaywrightError:
            break
        text = await _wait_change(frame, text)
        if text is None:  # o "next" não trocou o slide (exige interação no slide): para aqui
            break
        slides.append(text)
    return compose(slides)
