"""CLI `spa-extract`: login · map · extract · help · page · site · format."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .config import load_config


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--start-click",
        action="append",
        default=[],
        metavar="TEXTO",
        help='clica num botão pelo texto logo ao abrir (ex.: "Start learning|Resume learning" = um ou outro); '
        "repita para vários em sequência; substitui o start_click do extractor.toml",
    )
    parser.add_argument(
        "--wait-for",
        metavar="TEXTO_OU_SELETOR",
        help="só começa quando isto aparecer na página do conteúdo (ex.: um título do player)",
    )
    parser.add_argument("--pause", action="store_true", help="com --headed, deixa o navegador aberto até o Enter")
    parser.add_argument("--include-groups", action="store_true", help="extrai também a página dos módulos/grupos")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spa-extract", description="Extrai o conteúdo de uma SPA para Markdown.")
    parser.add_argument("--config", type=Path, help="extractor.toml (padrão: ./extractor.toml se existir)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="abre o navegador para você fazer login e salva a sessão")
    login.add_argument("url")

    map_ = sub.add_parser("map", help="mostra os itens de navegação encontrados (sem extrair)")
    map_.add_argument("url")
    map_.add_argument("--headed", action="store_true", help="mostra o navegador")
    _common(map_)

    ext = sub.add_parser("extract", help="extrai cada tópico do menu para um .md, numa pasta por grupo")
    ext.add_argument("url")
    ext.add_argument("--headed", action="store_true", help="mostra o navegador")
    ext.add_argument("--only", help="regex no título dos itens a extrair")
    ext.add_argument("--limit", type=int, help="no máximo N itens (teste)")
    ext.add_argument("--name", help="nome da pasta do curso (padrão: título da página de entrada)")
    ext.add_argument("--group", help='pasta que agrupa cursos (ex.: "signavio" → output/00-signavio/00-<curso>/)')
    _common(ext)

    hlp = sub.add_parser(
        "help", help="extrai um documento do SAP Help Portal (help.sap.com/docs/…) pelo sumário da coluna da esquerda"
    )
    hlp.add_argument("url", help="https://help.sap.com/docs/<produto>/<documento>[/<tópico>]")
    hlp.add_argument("--only", help="regex no caminho dos itens do sumário")
    hlp.add_argument("--limit", type=int, help="no máximo N páginas (teste)")
    hlp.add_argument("--name", help="nome da pasta do documento (padrão: título do documento no portal)")
    hlp.add_argument("--group", help='pasta que agrupa documentos (ex.: "ai-core" → output/NN-ai-core/NN-<documento>/)')
    hlp.add_argument(
        "--subtree",
        action="store_true",
        help="só o tópico da URL e os que estão abaixo dele no sumário (padrão: o documento inteiro)",
    )

    pg = sub.add_parser(
        "page", help="extrai uma página de artigo estática (ex.: learn.microsoft.com), sem navegador e sem menu"
    )
    pg.add_argument("url")
    pg.add_argument("--name", help="nome da pasta (padrão: título da página)")
    pg.add_argument("--group", help='pasta que agrupa páginas (ex.: "entra-id" → output/NN-entra-id/NN-<página>/)')

    st = sub.add_parser(
        "site", help="extrai um site de documentação estático (ou uma seção), pelo sumário em JSON, sitemap ou links"
    )
    st.add_argument("url", help="página inicial; o prefixo padrão é a pasta dela")
    st.add_argument("--prefix", help="só URLs que começam com isto (padrão: a pasta da URL inicial)")
    st.add_argument("--only", help="regex no caminho/URL das páginas a gravar")
    st.add_argument("--limit", type=int, help="no máximo N páginas novas (teste)")
    st.add_argument("--max-pages", type=int, default=20000, help="teto de segurança (padrão 20000)")
    st.add_argument("--delay", type=float, help="pausa média entre páginas em segundos (padrão: [timing] do toml)")
    st.add_argument("--resume", action="store_true", help="continua a extração mais recente, pulando o que está ok")
    st.add_argument("--content", help="seletor CSS do corpo do artigo (padrão: detecção automática)")
    st.add_argument("--name", help="nome da pasta (padrão: título da página inicial)")
    st.add_argument("--group", help="pasta que agrupa sites")

    fmt = sub.add_parser("format", help="formata os .md brutos de uma execução com Claude no SAP AI Core")
    fmt.add_argument(
        "run", type=Path, help="pasta do curso (output/NN-<curso>: a extração mais recente) ou de uma extração"
    )
    fmt.add_argument("--only", help="regex no caminho dos arquivos (pasta/arquivo)")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except (PermissionError, LookupError, RuntimeError) as error:
        # robots.txt, botão de entrada ou menu não encontrados: mensagem clara em vez de rastro de erro
        print(f"\nNão foi possível continuar: {error}", file=sys.stderr)
        return 3


def _run(argv: list[str] | None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    config = load_config(args.config)
    if getattr(args, "start_click", None):
        config.start_click = args.start_click
    if getattr(args, "include_groups", False):
        config.selectors.include_groups = True
    if getattr(args, "wait_for", None):
        config.start_wait_for = args.wait_for
    if getattr(args, "name", None):
        config.course_name = args.name
    if getattr(args, "group", None):
        config.group = args.group

    if args.command == "login":
        from .auth import login

        print(f"sessão salva em {asyncio.run(login(config, args.url))}")
        return 0

    if args.command == "map":
        from .extractor import discover

        items = asyncio.run(discover(config, args.url, headed=args.headed, pause=args.pause))
        if not items:
            print("nenhum menu encontrado — ajuste selectors.nav_container no extractor.toml", file=sys.stderr)
            return 1
        for item in items:
            marker = "▸ " if item.is_group else "  "
            print(f"{item.index:03d} {'  ' * item.depth}{marker}{item.title}")
        return 0

    if args.command == "extract":
        from .extractor import extract

        report = asyncio.run(
            extract(config, args.url, headed=args.headed, only=args.only, limit=args.limit, pause=args.pause)
        )
        ok = sum(1 for i in report.items if i["status"] == "ok")
        print(f"\n{ok}/{len(report.items)} item(ns) extraído(s) em {report.output}")
        return 0 if ok == len(report.items) else 2

    if args.command == "help":
        from .help_portal import extract_help

        report = extract_help(config, args.url, only=args.only, limit=args.limit, subtree_only=args.subtree)
        ok = sum(1 for i in report.items if i["status"] == "ok")
        print(f"\n{ok}/{len(report.items)} item(ns) extraído(s) em {report.output}")
        return 0 if ok == len(report.items) else 2

    if args.command == "page":
        from .page import extract_page

        report = extract_page(config, args.url)
        ok = sum(1 for i in report.items if i["status"] == "ok")
        print(f"\n{ok}/{len(report.items)} item(ns) extraído(s) em {report.output}")
        return 0 if ok == len(report.items) else 2

    if args.command == "site":
        from .site import extract_site

        report = extract_site(
            config,
            args.url,
            prefix=args.prefix,
            only=args.only,
            limit=args.limit,
            max_pages=args.max_pages,
            delay=args.delay,
            resume=args.resume,
            content=args.content,
        )
        ok = sum(1 for i in report.items if i["status"] == "ok")
        print(f"\n{ok}/{len(report.items)} item(ns) extraído(s) em {report.output}")
        return 0 if ok == len(report.items) else 2

    if args.command == "format":
        from .formatter import format_run

        results = format_run(args.run, Path.cwd(), only=args.only, knowledge_dir=config.knowledge_dir)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0 if all(isinstance(r, int) for _, r in results) else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
