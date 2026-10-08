"""Conteúdo: achar o container (em qualquer frame), serializar e limpar o ruído de interface, converter em Markdown."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter
from playwright.async_api import Frame, Page

from . import page_scripts
from .browser import all_frames, safe_eval
from .config import Config


@dataclass
class ContentLocation:
    frame: Frame
    selector: str
    text_length: int
    heading: str | None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip().lower()


async def locate_content(
    page: Page, config: Config, nav_selector: str | None, nav_frame: Frame | None
) -> ContentLocation | None:
    """O container de conteúdo pode estar no documento principal ou em iframes aninhados: avalia todos e fica com o
    de mais texto. O menu é descontado só no frame em que ele mora."""
    best: ContentLocation | None = None
    for frame in all_frames(page):
        found = await safe_eval(
            frame,
            page_scripts.FIND_CONTENT,
            {
                "fixedContainer": config.selectors.content_container,
                "candidates": config.selectors.content_candidates,
                "navSelector": nav_selector if frame == nav_frame else None,
            },
        )
        if not isinstance(found, dict):
            continue
        location = ContentLocation(frame, found["selector"], int(found["textLength"]), found.get("heading"))
        # o frame principal costuma "conter" o iframe só como moldura: um frame filho com texto vence empate
        if best is None or location.text_length > best.text_length:
            best = location
    return best


async def content_text(location: ContentLocation | None) -> str:
    if location is None:
        return ""
    text = await safe_eval(
        location.frame,
        "(s) => { const el = document.querySelector(s); return el ? (el.innerText || el.textContent || '') : '' }",
        location.selector,
    )
    return text if isinstance(text, str) else ""


async def serialize(location: ContentLocation) -> str:
    html = await safe_eval(location.frame, page_scripts.SERIALIZE, location.selector)
    return html if isinstance(html, str) else ""


def strip_noise(html: str, config: Config) -> BeautifulSoup:
    """Remove o que é interface, não conteúdo. AJUSTE `selectors.noise` / `noise_texts` no extractor.toml."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in config.selectors.noise:
        for el in soup.select(selector):
            el.decompose()
    noise_texts = {normalize(t) for t in config.selectors.noise_texts}
    for el in soup.find_all(["a", "span", "div", "p", "li"]):
        is_leaf = isinstance(el, Tag) and not el.find(["h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "pre"])
        if is_leaf and normalize(el.get_text(" ")) in noise_texts:
            el.decompose()
    return soup


class _KnowledgeMarkdown(MarkdownConverter):
    """Markdown para base de conhecimento: imagens viram comentário descritivo (o texto importa, o pixel não) e
    blocos de código levam a linguagem quando a classe indica (language-xxx / lang-xxx)."""

    def convert_img(self, el, text, parent_tags):
        alt = (el.get("alt") or el.get("title") or "").strip()
        return f"\n<!-- Imagem presente aqui: {alt or 'sem descrição'} -->\n"

    def convert_pre(self, el, text, parent_tags):
        code = el.find("code") or el
        classes = " ".join(code.get("class", []) + el.get("class", []))
        match = re.search(r"(?:language|lang)-([\w+#-]+)", classes)
        body = (code.get_text() or "").strip("\n")
        return f"\n```{match.group(1) if match else ''}\n{body}\n```\n"


def to_markdown(soup: BeautifulSoup) -> str:
    markdown = _KnowledgeMarkdown(heading_style="ATX", bullets="-", strip=["span"]).convert_soup(soup)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip() + "\n"
