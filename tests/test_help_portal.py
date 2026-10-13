"""`spa-extract help`: sumário do SAP Help Portal → pastas e .md, com um portal falso (sem rede)."""

import json
from pathlib import Path

import pytest

from spa_content_extractor.config import Config, Timing
from spa_content_extractor.help_portal import extract_help, parse_url

TOC = [
    {
        "t": "What Is SAP AI Core?",
        "u": "whatis.html",
        "id": 1,
        "c": [{"t": "Service Plans", "u": "plans.html", "id": 2, "c": []}],
    },
    {"t": "What's New", "u": "new.html", "id": 3, "c": []},
    {
        "t": "Initial Setup",
        "u": "setup.html",
        "id": 4,
        "c": [
            {
                "t": "Enabling the Service in Cloud Foundry",
                "u": "cf.html",
                "id": 5,
                "c": [{"t": "Create a Service Key", "u": "key.html", "id": 6, "c": []}],
            },
            {"t": "Enabling the Service in the Kyma Environment", "u": "kyma.html", "id": 7, "c": []},
        ],
    },
]
BODIES = {
    "whatis.html": "<h1>What Is SAP AI Core?</h1><p>SAP AI Core is a service in SAP BTP.</p>",
    "plans.html": "<h1>Service Plans</h1><table><tr><th>Plan</th></tr><tr><td>extended</td></tr></table>",
    "new.html": "<p>Release notes.</p>",
    "setup.html": "<h1>Initial Setup</h1><p>Get started with SAP AI Core.</p>",
    # como o portal devolve: documento inteiro, com <head><title> (que não pode virar linha solta)
    "cf.html": "<!DOCTYPE html><html><head><title>Enabling the Service in Cloud Foundry</title></head><body>"
    "<h1>Enabling the Service in Cloud Foundry</h1><p>Use the BTP cockpit.</p><button>Next</button></body></html>",
    "key.html": '<h1>Create a Service Key</h1><pre><code class=\'language-json\'>{"clientid": "x"}</code></pre>',
    "kyma.html": "<h1>Kyma</h1><p>Use the Kyma dashboard.</p>",
}


class FakePortal:
    def __init__(self):
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if path.endswith("deliverableMetadata"):
            assert params["product_url"] == "sap-ai-core" and params["deliverable_url"] == "sap-ai-core-service-guide"
            return {
                "deliverable": {"id": 24857212, "buildNo": 1759, "productName": "SAP AI Core"},
                "filePath": "setup.html",
                "readableUrls": {"tocReadableUrlMapping": [{"loio": "setup", "url": "initial-setup"}]},
            }
        if params.get("deliverableInfo"):
            return {"deliverable": {"title": "SAP AI Core Service Guide", "fullToc": TOC}, "body": BODIES["setup.html"]}
        return {"body": BODIES[params["file_path"]], "currentPage": {"t": params["file_path"]}}


def config_for(tmp_path: Path) -> Config:
    config = Config(timing=Timing(min_delay_s=0.0, max_delay_s=0.0))
    config.output_dir = tmp_path / "output"
    config.authorized_hosts = {"help.sap.com": "teste"}
    return config


URL = "https://help.sap.com/docs/sap-ai-core/sap-ai-core-service-guide/initial-setup?locale=en-US"


def test_le_a_url_do_documento():
    doc = parse_url(URL)
    assert (doc.product, doc.deliverable, doc.topic, doc.version, doc.locale) == (
        "sap-ai-core",
        "sap-ai-core-service-guide",
        "initial-setup",
        "LATEST",
        "en-US",
    )
    with pytest.raises(LookupError):
        parse_url("https://help.sap.com/viewer/abc")


def test_percorre_o_sumario_em_profundidade_e_grava_pastas(tmp_path):
    config = config_for(tmp_path)
    report = extract_help(config, URL, client=FakePortal())
    assert [i["path"] for i in report.items] == [
        "What Is SAP AI Core?",
        "What Is SAP AI Core? › Service Plans",
        "What's New",
        "Initial Setup",
        "Initial Setup › Enabling the Service in Cloud Foundry",
        "Initial Setup › Enabling the Service in Cloud Foundry › Create a Service Key",
        "Initial Setup › Enabling the Service in the Kyma Environment",
    ]
    assert all(i["status"] == "ok" for i in report.items)
    out = Path(report.output)
    assert out.parent.name == "00-sap-ai-core-service-guide"  # pasta do documento, numerada como os cursos
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md"))
    assert files == [
        "01-what-is-sap-ai-core/00-what-is-sap-ai-core.md",  # item com filhos: pasta + a página dele como 00-
        "01-what-is-sap-ai-core/01-service-plans.md",
        "02-what-s-new.md",
        "03-initial-setup/00-initial-setup.md",
        "03-initial-setup/01-enabling-the-service-in-cloud-foundry/00-enabling-the-service-in-cloud-foundry.md",
        "03-initial-setup/01-enabling-the-service-in-cloud-foundry/01-create-a-service-key.md",
        "03-initial-setup/02-enabling-the-service-in-the-kyma-environment.md",
    ]
    key = (out / files[5]).read_text(encoding="utf-8")
    assert 'module: "Initial Setup › Enabling the Service in Cloud Foundry"' in key
    assert "```json" in key  # bloco de código com a linguagem
    cf = (out / files[4]).read_text(encoding="utf-8")
    assert "Use the BTP cockpit" in cf and "Next" not in cf  # botão é ruído de interface
    assert cf.split("---\n\n", 1)[1].count("Enabling the Service in Cloud Foundry") == 1  # título uma vez só
    new = (out / files[2]).read_text(encoding="utf-8")
    assert new.split("---\n\n", 1)[1].startswith("# What's New")  # página sem título ganha o do sumário
    setup = (out / files[3]).read_text(encoding="utf-8")
    assert "source: https://help.sap.com/docs/sap-ai-core/sap-ai-core-service-guide/initial-setup" in setup
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["url"].startswith("https://help.sap.com/docs/sap-ai-core/sap-ai-core-service-guide?")


def test_only_e_limit(tmp_path):
    report = extract_help(config_for(tmp_path), URL, only="kyma|service key", client=FakePortal())
    assert [i["title"] for i in report.items] == [
        "Create a Service Key",
        "Enabling the Service in the Kyma Environment",
    ]
    report = extract_help(config_for(tmp_path), URL, limit=2, client=FakePortal())
    assert len(report.items) == 2


def test_respeita_o_robots_sem_autorizacao(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    config.authorized_hosts = {}

    def disallow(url, cfg):
        raise PermissionError("robots.txt não permite")

    monkeypatch.setattr("spa_content_extractor.help_portal.ensure_allowed", disallow)
    with pytest.raises(PermissionError):
        extract_help(config, URL, client=FakePortal())
