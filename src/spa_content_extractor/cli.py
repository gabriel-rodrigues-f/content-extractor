"""CLI `spa-extract`: login · map · extract · format."""

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
        help='clica num botão pelo texto logo ao abrir (ex.: "Resume learning"); repita para vários',
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

    ext = sub.add_parser("extract", help="extrai cada item do menu para um .md")
    ext.add_argument("url")
    ext.add_argument("--headed", action="store_true", help="mostra o navegador")
    ext.add_argument("--only", help="regex no título dos itens a extrair")
    ext.add_argument("--limit", type=int, help="no máximo N itens (teste)")
    _common(ext)

    fmt = sub.add_parser("format", help="formata os .md brutos de uma execução com Claude no SAP AI Core")
    fmt.add_argument("run", type=Path, help="pasta da execução (output/<host>/<data>)")
    fmt.add_argument("--only", help="regex no nome dos arquivos")
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
        config.start_click = [*config.start_click, *args.start_click]
    if getattr(args, "include_groups", False):
        config.selectors.include_groups = True

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

    if args.command == "format":
        from .formatter import format_run

        results = format_run(args.run, Path.cwd(), only=args.only)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0 if all(isinstance(r, int) for _, r in results) else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
