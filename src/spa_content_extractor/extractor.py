"""Fluxo de extração: abrir → ação de entrada → percorrer o menu em profundidade (sempre do primeiro item) e, em cada
tópico, clicar, esperar estabilizar, extrair e salvar — em pastas que repetem os grupos do menu."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from .browser import open_browser, polite_pause, wait_until_stable
from .config import Config
from .content import ContentLocation, content_text, locate_content, serialize, strip_noise, to_markdown
from .entry import run_start_actions
from .navigation import MenuWalker, NavItem
from .robots import ensure_allowed
from .slides import is_slide_player, slides_markdown

log = logging.getLogger(__name__)


def slugify(text: str, limit: int = 70) -> str:
    """Nome de arquivo/pasta: sem acentos, minúsculo, hífens; nomes longos são cortados na última palavra inteira."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(slug) > limit:
        cut = slug[: limit + 1]  # um caractere a mais: se for "-", a palavra do limite está inteira
        slug = cut.rsplit("-", 1)[0] if "-" in cut[limit // 2 :] else slug[:limit]
    return slug.rstrip("-") or "sem-titulo"


def item_file(item: NavItem) -> PurePosixPath:
    """Arquivo do item dentro da pasta do curso: cada grupo do menu vira uma pasta e cada tópico um .md dentro dela, numerados
    pela posição no menu (a ordem do curso aparece em qualquer explorador de arquivos). A página do próprio grupo
    (--include-groups) fica como `00-<grupo>.md` dentro da pasta dele."""
    parts = [f"{number:02d}-{slugify(title, 60)}" for number, title in zip(item.position, item.path, strict=True)]
    if item.is_group:
        return PurePosixPath(*parts, f"00-{slugify(item.title, 60)}.md")
    return PurePosixPath(*parts[:-1], f"{parts[-1]}.md")


@dataclass
class RunReport:
    url: str
    started_at: str
    output: str
    items: list[dict] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


def _extracted_from(folder: Path, url: str) -> bool:
    for manifest_file in folder.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(manifest.get("url", "")).rstrip("/") == url.rstrip("/"):
            return True
    return False


def _numbered(root: Path, name: str, url: str | None = None) -> Path:
    """`NN-<nome>` dentro de root, com NN crescente na ordem de criação (00, 01, 02…). Reaproveita a pasta de mesmo
    nome ou, para um curso, a que já tem uma extração da mesma URL (mesmo que alguém a tenha renomeado)."""
    root.mkdir(parents=True, exist_ok=True)
    slug = slugify(name, 80)
    numbers: list[int] = []
    for folder in sorted(root.iterdir()):
        match = re.match(r"(\d+)-(.*)", folder.name)
        if not folder.is_dir() or not match:
            continue
        numbers.append(int(match.group(1)))
        if match.group(2) == slug or (url and _extracted_from(folder, url)):
            return folder
    path = root / f"{(max(numbers) + 1 if numbers else 0):02d}-{slug}"
    path.mkdir()
    return path


def course_dir(config: Config, url: str, name: str) -> Path:
    """Pasta do curso: output/[NN-<grupo>/]NN-<curso>, numeradas na ordem em que são criadas. O mesmo curso (mesmo
    nome ou mesma URL) volta para a pasta e o número que já tem."""
    root = _numbered(config.output_dir, config.group) if config.group else config.output_dir
    return _numbered(root, name, url)


async def course_name(page: Page, url: str) -> str:
    """Nome do curso pela página de entrada: o título da aba (sem o " | site"), o <h1> ou o fim da URL."""
    try:
        title, heading = await page.evaluate(
            "() => [document.title || '', (document.querySelector('h1') || {}).innerText || '']"
        )
    except PlaywrightError:
        title, heading = "", ""
    for candidate in (str(title).split(" | ")[0], str(heading)):
        if candidate.strip():
            return candidate.strip()
    parsed = urlparse(url)
    return parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.hostname or "curso"


async def parent_name(page: Page, url: str) -> str | None:
    """Nome do curso quando a URL já abriu numa lição: o penúltimo item do caminho de navegação (Cursos › <curso> ›
    <lição>) ou o penúltimo trecho da URL (/courses/<curso>/<lição>)."""
    try:
        crumbs = await page.evaluate(
            "() => Array.from(document.querySelectorAll('nav[aria-label*=readcrumb i] li, [class*=breadcrumb i] li'))"
            ".map((li) => (li.innerText || '').replace(/[\\s/›>»]+$/, '').trim()).filter(Boolean)"
        )
    except PlaywrightError:
        crumbs = []
    if isinstance(crumbs, list) and len(crumbs) >= 2:
        return str(crumbs[-2])
    segments = [s for s in urlparse(url).path.split("/") if s]
    return segments[-2].replace("-", " ") if len(segments) >= 2 else None


class SessionExpiredError(RuntimeError):
    """A URL caiu numa página de login/SSO de outro domínio: a sessão salva expirou ou não existe."""


_LOGIN_HINT = re.compile(r"login|signin|sign-in|sso|saml|oauth|auth|idp|accounts", re.IGNORECASE)


def _check_session(page: Page, url: str) -> None:
    landed = urlparse(page.url)
    if landed.hostname != urlparse(url).hostname and _LOGIN_HINT.search(f"{landed.hostname}{landed.path}"):
        raise SessionExpiredError(
            f"a sessão expirou: a página foi redirecionada para o login ({landed.hostname}). Rode "
            f"`uv run spa-extract login {url}`, entre na janela e tente de novo."
        )


async def _open(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightError:
        pass
    _check_session(page, url)


async def _pause(headed: bool, pause: bool) -> None:
    if headed and pause:
        await asyncio.to_thread(input, "\nNavegador aberto para inspeção. Pressione Enter para fechar…")


async def discover(config: Config, url: str, *, headed: bool, pause: bool = False) -> list[NavItem]:
    """`spa-extract map`: percorre o menu como a extração faria (abrindo cada grupo e clicando em cada tópico, porque
    alguns menus só mostram os subitens depois do clique), sem extrair conteúdo."""
    ensure_allowed(url, config)
    async with open_browser(config, url, headed=headed) as (context, page):
        await _open(page, url)
        page, _ = await run_start_actions(context, page, config, config.start_click)
        _check_session(page, url)
        walker = MenuWalker(page, config)
        items: list[NavItem] = []

        async def record_group(item: NavItem) -> None:
            items.append(item)

        async def record_leaf(item: NavItem) -> None:
            items.append(item)
            await walker.click(item.path)
            await polite_pause((config.timing.min_delay_s, config.timing.max_delay_s))

        try:
            await walker.walk(on_leaf=record_leaf, on_group=record_group)
        except RuntimeError:
            return []
        await _pause(headed, pause)
        return items


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
    page: Page, config: Config, walker: MenuWalker, item: NavItem, previous_hash: str | None
) -> tuple[str, str, ContentLocation | None]:
    target = await walker.locate(item.path)  # reabre o caminho (Módulo › Unidade) se o menu se fechou
    if target is None:
        raise LookupError("item sumiu do menu")
    await target.scroll_into_view_if_needed()
    # o que está na tela antes do clique: o conteúdo novo precisa ser diferente disso (lição anterior ou a que o
    # player abriu sozinho, de cache)
    before = await content_text(await locate_content(page, config, walker.container, walker.frame))
    baseline = hashlib.sha1(before.encode("utf-8")).hexdigest() if before else previous_hash
    await polite_pause(config.timing.pre_click_delay_s)
    await target.click()

    location: ContentLocation | None = None

    async def current_text() -> str:
        nonlocal location
        location = await locate_content(page, config, walker.container, walker.frame)
        return await content_text(location)

    stable_hash = await wait_until_stable(page, config, baseline, current_text)
    if location is None:
        raise LookupError("container de conteúdo não encontrado")
    if await is_slide_player(location.frame):
        # player de slides (Storyline): o texto só existe slide a slide — avança pelo "next" e junta
        markdown = await slides_markdown(location.frame)
    else:
        markdown = to_markdown(strip_noise(await serialize(location), config))
    if not markdown.strip():
        raise ValueError("conteúdo vazio depois da limpeza")
    return markdown, stable_hash, location


class _LimitReached(Exception):
    pass


async def extract(
    config: Config,
    url: str,
    *,
    headed: bool,
    only: str | None = None,
    limit: int | None = None,
    pause: bool = False,
) -> RunReport:
    """`spa-extract extract`: um .md por tópico em output/NN-<curso>/<data-hora>/<módulo>/<unidade>/…, com
    manifest.json — cada extração numa pasta com a data, dentro do curso."""
    ensure_allowed(url, config)
    async with open_browser(config, url, headed=headed) as (context, page):
        await _open(page, url)
        # o nome vem da página de entrada, antes do "Resume Learning" (no player, o título já é o da lição)
        name = config.course_name or await course_name(page, url)
        page, clicked = await run_start_actions(context, page, config, config.start_click)
        _check_session(page, url)
        if config.start_click and not clicked and not config.course_name:
            # a URL já abriu numa lição: o curso está no caminho de navegação
            name = await parent_name(page, url) or name
        course = course_dir(config, url, name)
        out = course / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")  # hora local
        out.mkdir(exist_ok=True)
        log.info("extração em %s", out)
        report = RunReport(url=url, started_at=datetime.now(UTC).isoformat(timespec="seconds"), output=str(out))
        walker = MenuWalker(page, config)
        state: dict[str, object] = {"previous_hash": None}
        entries: dict[tuple[str, ...], dict] = {}  # caminho do item → entrada no manifesto

        async def handle(item: NavItem) -> None:
            path_text = " › ".join(item.path)
            if only and not re.search(only, path_text, re.IGNORECASE):
                return
            if limit and len(report.items) >= limit:
                raise _LimitReached
            entry: dict = {"index": item.index, "path": path_text, "title": item.title, "status": "pending"}
            for attempt in range(1, config.timing.retries + 2):
                try:
                    markdown, digest, location = await _extract_item(
                        page,
                        config,
                        walker,
                        item,
                        state["previous_hash"],  # type: ignore[arg-type]
                    )
                    state["previous_hash"] = digest
                    relative = item_file(item)
                    target = out / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(_front_matter(item, url, location) + markdown, encoding="utf-8")
                    entry.update(status="ok", file=str(relative), chars=len(markdown), attempts=attempt)
                    log.info("✓ %03d %s (%s caracteres)", item.index, path_text, len(markdown))
                    break
                except (PlaywrightError, LookupError, TimeoutError, ValueError) as error:
                    entry.update(status="error", error=f"{type(error).__name__}: {error}", attempts=attempt)
                    log.warning("✗ %03d %s — tentativa %s: %s", item.index, path_text, attempt, error)
                    if attempt <= config.timing.retries:
                        await polite_pause((config.timing.min_delay_s, config.timing.max_delay_s))
            report.items.append(entry)
            entries[item.path] = entry
            report.save(out / "manifest.json")
            await polite_pause((config.timing.min_delay_s, config.timing.max_delay_s))

        async def promoted(item: NavItem) -> None:
            """O "tópico" revelou subitens ao ser clicado: é uma pasta. O arquivo dele vira a página do grupo
            (--include-groups) ou sai do resultado."""
            entry = entries.pop(item.path, None)
            if entry is None:
                return
            old = out / entry["file"] if entry.get("file") else None
            if config.selectors.include_groups and old and old.exists():
                relative = item_file(item)  # agora é grupo: <pasta>/00-<grupo>.md
                (out / relative).parent.mkdir(parents=True, exist_ok=True)
                old.replace(out / relative)
                entry["file"] = str(relative)
            else:
                if old:
                    old.unlink(missing_ok=True)
                report.items.remove(entry)
            report.save(out / "manifest.json")

        try:
            await walker.walk(
                on_leaf=handle,
                on_group=handle if config.selectors.include_groups else None,
                on_promoted=promoted,
            )
        except _LimitReached:
            log.info("limite de %s item(ns) atingido", limit)
        except RuntimeError:
            # sem menu: não deixa pasta vazia do curso para trás
            for empty in (out, course):
                if empty.exists() and not any(empty.iterdir()):
                    empty.rmdir()
            raise
        await _pause(headed, pause)
    return report
