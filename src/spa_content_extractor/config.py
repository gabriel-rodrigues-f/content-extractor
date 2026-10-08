"""Configuração do extrator: seletores, esperas e ritmo.

>>> AJUSTE AQUI quando a aplicação-alvo mudar de estrutura. <<<
Os valores padrão funcionam por heurística (detecção automática); para um alvo específico, crie um
`extractor.toml` (veja `extractor.example.toml`) e sobrescreva só o que precisar — sem mexer no código.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Selectors:
    # Navegação (barra lateral, árvore, menu, lista de tópicos). Se `nav_container` estiver vazio, o extrator
    # escolhe sozinho o candidato com mais itens clicáveis. AJUSTE `nav_container` para fixar o menu certo.
    nav_container: str = ""
    nav_container_candidates: list[str] = field(
        default_factory=lambda: [
            "nav",
            "[role=navigation]",
            "[role=tree]",
            "[role=menu]",
            "[role=tablist]",
            "aside",
            ".sidebar, .side-nav, .sidenav, .toc, .table-of-contents, .outline, .course-outline",
            "ul, ol",
        ]
    )
    # Itens clicáveis dentro do menu. AJUSTE se os itens forem <div>s sem papel acessível.
    nav_item: str = (
        "a, button, [role=treeitem], [role=menuitem], [role=tab], [role=link], [role=option], "
        "li[tabindex], [onclick], summary"
    )
    # Abrir grupos recolhidos (módulos com lições dentro) antes de mapear.
    expand_collapsed: bool = True

    # Container do conteúdo. Se `content_container` estiver vazio, vence o candidato com mais texto (em
    # qualquer frame, inclusive iframes aninhados) que não seja o menu. AJUSTE para fixar o container.
    content_container: str = ""
    content_candidates: list[str] = field(
        default_factory=lambda: [
            "main",
            "[role=main]",
            "article",
            "[role=document]",
            "#content, #main-content, .content, .main-content, .page-content, .lesson, .lesson-content",
            ".topic, .module-content, .reader, .markdown-body, .doc-content",
        ]
    )
    # Ruído de interface removido do conteúdo. AJUSTE acrescentando classes do alvo (ex.: ".btn-next").
    noise: list[str] = field(
        default_factory=lambda: [
            "nav",
            "header",
            "footer",
            "aside",
            "form",
            "button",
            "input",
            "select",
            "textarea",
            "[role=navigation]",
            "[role=banner]",
            "[role=contentinfo]",
            "[role=button]",
            "[role=toolbar]",
            "[role=dialog]",
            "[aria-hidden=true]",
            ".breadcrumb, .breadcrumbs, .pagination, .pager, .toolbar, .cookie, .cookies, .skip-link",
        ]
    )
    # Textos de controle que nunca são conteúdo (comparação sem acento e sem maiúsculas, texto exato).
    noise_texts: list[str] = field(
        default_factory=lambda: [
            "proximo",
            "anterior",
            "voltar",
            "avancar",
            "continuar",
            "next",
            "previous",
            "back",
            "continue",
            "marcar como concluido",
            "mark as complete",
            "clique aqui",
            "saiba mais",
            "menu",
            "sair",
            "logout",
        ]
    )
    # Indicadores de carregamento: o extrator espera sumirem.
    loading: str = "[aria-busy=true], .spinner, .loading, .loader, .skeleton, [role=progressbar]"


@dataclass
class Timing:
    # Ritmo educado (não é técnica de evasão): uma aba, uma ação por vez, pausas aleatórias entre itens.
    min_delay_s: float = 1.5
    max_delay_s: float = 4.0
    pre_click_delay_s: tuple[float, float] = (0.3, 0.9)
    # Estabilidade: o conteúdo só é lido depois de `quiet_ms` sem mutações no DOM (em todos os frames).
    quiet_ms: int = 800
    stable_timeout_ms: int = 20_000
    navigation_timeout_ms: int = 45_000
    retries: int = 2


@dataclass
class Config:
    selectors: Selectors = field(default_factory=Selectors)
    timing: Timing = field(default_factory=Timing)
    output_dir: Path = Path("output")
    auth_dir: Path = Path(".auth")
    # "chromium" (o do Playwright) ou "chrome" (o Google Chrome instalado).
    browser_channel: str = "chromium"
    locale: str = "pt-BR"
    viewport: tuple[int, int] = (1440, 900)


def _merge(target: object, data: dict) -> None:
    names = {f.name for f in fields(target)}  # type: ignore[arg-type]
    for key, value in data.items():
        if key not in names:
            raise ValueError(f"opção desconhecida no extractor.toml: {key}")
        current = getattr(target, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge(current, value)
        elif isinstance(current, Path):
            setattr(target, key, Path(value))
        elif isinstance(current, tuple):
            setattr(target, key, tuple(value))
        else:
            setattr(target, key, value)


def load_config(path: Path | None) -> Config:
    config = Config()
    candidate = path or Path("extractor.toml")
    if candidate.exists():
        with candidate.open("rb") as handle:
            _merge(config, tomllib.load(handle))
    elif path is not None:
        raise FileNotFoundError(f"configuração não encontrada: {path}")
    return config
