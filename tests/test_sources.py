"""`spa-extract repo` e notebooks → Markdown, com um repositório falso (sem rede)."""

import json
from pathlib import Path

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
        return Result()

    monkeypatch.setattr("spa_content_extractor.sources.subprocess.run", fake_run)
    config = Config()
    config.output_dir = tmp_path / "output"
    report = extract_repo(config, "https://github.com/anthropics/courses")
    out = Path(report.output)
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md")) == ["readme.md", "tool-use/01-intro.md"]
    note = (out / "tool-use/01-intro.md").read_text(encoding="utf-8")
    assert 'title: "Tool use"' in note and 'module: "tool_use"' in note
    assert "source: https://github.com/anthropics/courses/blob/master/tool_use/01_intro.ipynb" in note
