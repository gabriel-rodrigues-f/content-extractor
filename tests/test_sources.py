"""`spa-extract repo` e notebooks → Markdown, com um repositório falso (sem rede)."""

import json
from pathlib import Path
from typing import ClassVar

from spa_content_extractor.config import Config
from spa_content_extractor.sources import extract_repo, notebook_markdown

NOTEBOOK = {
    "metadata": {"language_info": {"name": "python"}},
    "cells": [
        {
            "cell_type": "markdown",
            "source": ["# Tool use\n", "Claude can call tools.\n", "![diagram](attachment:a.png)"],
        },
        {
            "cell_type": "code",
            "source": ["import anthropic\n", "client = anthropic.Anthropic()"],
            "outputs": [{"output_type": "display_data", "data": {"image/png": "iVBORw0KGgo..."}}],
        },
        {"cell_type": "code", "source": [], "outputs": []},
    ],
}


def test_notebook_vira_markdown_sem_saidas():
    markdown = notebook_markdown(json.dumps(NOTEBOOK))
    assert markdown.startswith("# Tool use\nClaude can call tools.")
    assert "```python\nimport anthropic\nclient = anthropic.Anthropic()\n```" in markdown
    assert "iVBORw0KGgo" not in markdown and "<!-- Imagem presente aqui: diagram -->" in markdown


def test_repositorio_mantem_as_pastas(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        class Result:
            stdout = "master\n"

        if cmd[:2] == ["git", "clone"]:
            target = Path(cmd[-1])
            (target / "tool_use").mkdir(parents=True)
            (target / "LICENSE").write_text("Attribution-NonCommercial 4.0 International\n...", encoding="utf-8")
            (target / "README.md").write_text("# Courses\n\nWelcome.", encoding="utf-8")
            (target / "tool_use" / "01_intro.ipynb").write_text(json.dumps(NOTEBOOK), encoding="utf-8")
            (target / "tool_use" / "image.png").write_bytes(b"\x89PNG")
            (target / "tool_use" / "flow.drawio").write_text("<mxfile/>", encoding="utf-8")
        return Result()

    monkeypatch.setattr("spa_content_extractor.sources.subprocess.run", fake_run)
    config = Config()
    config.output_dir = tmp_path / "output"
    report = extract_repo(config, "https://github.com/anthropics/courses", assets=r"\.drawio$")
    out = Path(report.output)
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md")) == ["readme.md", "tool-use/01-intro.md"]
    note = (out / "tool-use/01-intro.md").read_text(encoding="utf-8")
    assert 'title: "Tool use"' in note and 'module: "tool_use"' in note
    assert "source: https://github.com/anthropics/courses/blob/master/tool_use/01_intro.ipynb" in note
    assert (out / "tool-use/flow.drawio").read_text(encoding="utf-8") == "<mxfile/>"  # anexo copiado
    assert not (out / "tool-use/image.png").exists()  # só o que bate com --assets


def test_titulo_mantem_underscore_de_nomes():
    from spa_content_extractor.sources import _title

    assert _title("# `btp_subaccount` (Resource)\n\ntext", "x") == "btp_subaccount (Resource)"
    assert _title("## **Tool use** basics", "x") == "Tool use basics"


def test_repo_com_path_diferente_vai_para_pasta_propria(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        class Result:
            stdout = "dev\n"

        if cmd[:2] == ["git", "clone"]:
            target = Path(cmd[-1])
            for ra in ("RA0009", "RA0018"):
                (target / "docs" / "ref-arch" / ra).mkdir(parents=True)
                (target / "docs" / "ref-arch" / ra / "readme.md").write_text(f"# {ra}\n\ntext", encoding="utf-8")
        return Result()

    monkeypatch.setattr("spa_content_extractor.sources.subprocess.run", fake_run)
    config = Config()
    config.output_dir = tmp_path / "output"
    first = extract_repo(config, "https://github.com/SAP/architecture-center", path="docs/ref-arch/RA0009")
    second = extract_repo(config, "https://github.com/SAP/architecture-center", path="docs/ref-arch/RA0018")
    assert Path(first.output).parent != Path(second.output).parent


def test_zendesk_pela_api_json(tmp_path, monkeypatch):
    from spa_content_extractor.sources import extract_zendesk

    api = "https://ajuda.exemplo.com/api/v2/help_center/pt-br"
    responses = {
        f"{api}/categories.json?per_page=100": {"categories": [{"id": 1, "name": "Núcleo RH"}], "next_page": None},
        f"{api}/sections.json?per_page=100": {
            "sections": [
                {"id": 10, "name": "API", "category_id": 1, "html_url": "x"},
                {"id": 11, "name": "Reintegração", "category_id": 1, "html_url": "y"},
            ],
            "next_page": None,
        },
        f"{api}/sections/10/articles.json?per_page=100": {
            "articles": [
                {
                    "title": "API - Gerar Relatório",
                    "html_url": "https://ajuda.exemplo.com/hc/pt-br/articles/1",
                    "body": "<p>Endpoint SOAP ServicoDeRelatorio.</p>",
                    "position": 0,
                }
            ],
            "next_page": None,
        },
    }
    monkeypatch.setattr("spa_content_extractor.sources._zendesk_get", lambda url: responses[url])
    monkeypatch.setattr("spa_content_extractor.sources.ensure_allowed", lambda url, config: None)
    config = Config()
    config.output_dir = tmp_path / "output"
    report = extract_zendesk(config, "https://ajuda.exemplo.com/hc/pt-br", sections="^API$", pause=0)
    out = Path(report.output)
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md"))
    assert files == ["01-nucleo-rh/01-api/01-api-gerar-relatorio.md"]
    note = (out / files[0]).read_text(encoding="utf-8")
    assert "ServicoDeRelatorio" in note and "source: https://ajuda.exemplo.com/hc/pt-br/articles/1" in note


def test_pdf_dividido_pelo_sumario_embutido():
    from spa_content_extractor.sources import pdf_sections

    class Mark:
        def __init__(self, title, page):
            self.title, self.page = title, page

    class Reader:
        # sumário: Contents (ignorado), 1 Intro, 2 Auth › V2 Token e V1 Token — os dois na mesma página
        outline: ClassVar[list] = [
            Mark("Contents", 0),
            Mark("1 Intro", 1),
            Mark("2 Auth", 2),
            [Mark("V2 Token", 2), Mark("V1 Token", 2)],
        ]

        def get_destination_page_number(self, mark):
            return mark.page

    pages = [
        "Contents 1 Intro 2 Auth",
        "1 Intro\nAbout Unifier.",
        "2 Auth\nV2 Token\nGET /v2/auth/token\nV1 Token\nGET /v1",
    ]
    sections = pdf_sections(Reader(), pages, max_depth=2)
    assert [s[0] for s in sections] == [("1 Intro",), ("2 Auth",), ("2 Auth", "V2 Token"), ("2 Auth", "V1 Token")]
    assert [s[1] for s in sections] == [(1,), (2,), (2, 1), (2, 2)]
    assert "GET /v2/auth/token" in sections[2][2] and "GET /v1" not in sections[2][2]  # corta no título, não na página
    assert sections[3][2].startswith("V1 Token") and "GET /v1" in sections[3][2]
