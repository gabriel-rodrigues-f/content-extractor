"""`spa-extract page`: artigo estático (como o learn.microsoft.com) → um .md, sem rede."""

from pathlib import Path

from spa_content_extractor.config import Config
from spa_content_extractor.page import article, extract_page

# como o Microsoft Learn: o título fica num cabeçalho fora do corpo; main tem migalhas, metadados e o artigo
LEARN = """<html><head><title>Scenario - Entra ID and SAP | Microsoft Learn</title></head><body>
<header><nav>Learn › Entra › Fundamentals</nav></header>
<main id="main" role="main">
  <div class="content"><h1>Scenario - Entra ID and SAP</h1></div>
  <ul class="metadata"><li>Article</li><li>03/20/2026</li></ul>
  <div class="content">
    <p>This document provides advice on the technical design of SAP platforms when using Microsoft Entra ID as the
    primary user authentication service.</p>
    <h2>Recommendations</h2><ul><li>Use SAP Cloud Identity Services as a proxy.</li></ul>
    <pre><code class="lang-json">{"groups": ["sap-admins"]}</code></pre>
  </div>
  <div class="feedback"><button>Yes</button><button>No</button></div>
</main><footer>© Microsoft</footer></body></html>"""


def test_escolhe_o_corpo_do_artigo():
    title, body = article(LEARN, Config())
    assert title == "Scenario - Entra ID and SAP"
    assert "technical design" in body and "Fundamentals" not in body and "03/20/2026" not in body


def test_grava_a_pagina_no_layout_dos_cursos(tmp_path, monkeypatch):
    monkeypatch.setattr("spa_content_extractor.page.fetch", lambda url: LEARN)
    monkeypatch.setattr("spa_content_extractor.page.ensure_allowed", lambda url, config: None)
    config = Config()
    config.output_dir = tmp_path / "output"
    config.group = "entra-id"
    url = "https://learn.microsoft.com/en-us/entra/fundamentals/scenario-azure-first-sap-identity-integration"
    report = extract_page(config, url)
    out = Path(report.output)
    assert out.parent.parent.name == "00-entra-id" and out.parent.name == "00-scenario-entra-id-and-sap"
    text = (out / "01-scenario-entra-id-and-sap.md").read_text(encoding="utf-8")
    assert f"source: {url}" in text
    assert text.split("---\n\n", 1)[1].startswith("# Scenario - Entra ID and SAP")  # título do cabeçalho vem junto
    assert "```json" in text and "## Recommendations" in text
    assert report.items[0]["status"] == "ok"
