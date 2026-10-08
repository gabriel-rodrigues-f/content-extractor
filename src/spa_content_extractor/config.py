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
        "li[tabindex], [onclick], summary, [aria-expanded], [data-state]"
    )
    # Abrir grupos recolhidos (módulos → unidades → lições), nível por nível, até não aparecer item novo.
    expand_collapsed: bool = True
    # Marca extra de grupo (cabeçalho que abre subitens = pasta na saída), no próprio item ou num ícone dentro dele.
    # Os grupos já são reconhecidos por aria-expanded, data-state, <details>, sublista no mesmo <li> e pelo clique que
    # revela subitens. AJUSTE acrescentando a classe do alvo (ex.: ".chevron-right") se um módulo virar arquivo.
    expanders: str = "[aria-expanded=false], [data-state=closed], .collapsed, .is-collapsed"
    max_expand_rounds: int = 10
    # Também extrair a página do próprio grupo (quando o módulo tem uma visão geral própria).
    include_groups: bool = False

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
            # classes geradas por CSS Modules / styled-components (ex.: "LessonPage_content__x1Y2z")
            '[class*="content" i], [class*="lesson" i], [class*="article" i]',
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
            "proxima licao",
            "licao anterior",
            "proxima aula",
            "aula anterior",
            "next lesson",
            "previous lesson",
            "esta licao foi util?",
            "was this lesson helpful?",
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
    # Depois do clique de entrada ("Resume Learning"): quanto esperar a página do conteúdo aparecer.
    transition_timeout_s: int = 30
    retries: int = 2


@dataclass
class Config:
    selectors: Selectors = field(default_factory=Selectors)
    timing: Timing = field(default_factory=Timing)
    # Botões clicados em sequência logo depois de abrir a URL, pelo texto visível (ex.: ["Resume learning"]).
    # AJUSTE aqui ou passe --start-click na linha de comando.
    start_click: list[str] = field(default_factory=list)
    # Opcional: texto ou seletor que só existe na página do conteúdo (ex.: "Lesson 1" ou "nav.course-outline"). O
    # extrator espera ele aparecer antes de começar. Equivale a --wait-for.
    start_wait_for: str = ""
    # O extrator respeita o robots.txt. Site seu ou com permissão por escrito que bloqueia robôs: cadastre o host com a
    # autorização (fica registrada no log de cada execução). Ex.: {"treinamento.minhaempresa.com" = "site próprio"}
    authorized_hosts: dict[str, str] = field(default_factory=dict)
    # Cada curso vira output/NN-<curso>/ (NN crescente); a formatação com IA grava em knowledge/NN-<curso>/.
    output_dir: Path = Path("output")
    knowledge_dir: Path = Path("knowledge")
    # Nome da pasta do curso. Vazio = título da página de entrada. Equivale a --name.
    course_name: str = ""
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
