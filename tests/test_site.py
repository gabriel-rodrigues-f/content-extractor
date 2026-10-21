"""`spa-extract site`: site de documentação inteiro, com um site falso em memória (sem rede)."""

import json
from pathlib import Path

import pytest

from spa_content_extractor.config import Config, Timing
from spa_content_extractor.site import default_prefix, extract_site

ROOT = "https://docs.example.com/guide/"


def page(title, body, links=()):
    nav = "".join(f'<a href="{href}">{href}</a>' for href in links)
    return (
        f"<html><head><title>{title} | Example</title></head><body><nav>{nav}</nav>"
        f"<main><h1>{title}</h1><div class='content'><p>{body}</p></div></main></body></html>"
    )


def fake_site(monkeypatch, pages):
    calls = []

    def fetch(url, retries=3):
        calls.append(url)
        if url not in pages:
            raise RuntimeError(f"404 {url}")
        return pages[url]

    monkeypatch.setattr("spa_content_extractor.site.fetch", fetch)
    return calls


@pytest.fixture
def config(tmp_path):
    config = Config(timing=Timing(min_delay_s=0.0, max_delay_s=0.0))
    config.output_dir = tmp_path / "output"
    return config


def files(report):
    out = Path(report.output)
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*.md"))


def test_prefixo_padrao_e_a_pasta_da_url():
    assert default_prefix("https://a.com/x/userguide/what-is.html") == "https://a.com/x/userguide/"
    assert default_prefix("https://a.com/azure/ai-foundry/") == "https://a.com/azure/ai-foundry/"


def test_sumario_em_json_do_microsoft_learn(monkeypatch, config):
    start = page("Foundry", "Overview of Foundry.").replace("<head>", '<head><meta name="toc_rel" content="toc.json">')
    toc = {
        "items": [
            {"toc_title": "Overview", "href": "./"},
            {
                "toc_title": "Agents",
                "children": [
                    {"toc_title": "What are agents?", "href": "agents/overview"},
                    {"toc_title": "Quickstart", "href": "agents/quickstart"},
                    {"toc_title": "Pricing", "href": "https://azure.microsoft.com/pricing/"},  # fora do prefixo
                ],
            },
            {"toc_title": "Elsewhere", "href": "../other/"},  # fora: some
        ]
    }
    fake_site(
        monkeypatch,
        {
            "https://docs.example.com/robots.txt": "User-agent: *\nAllow: /\n",
            ROOT: start,
            ROOT + "toc.json": json.dumps(toc),
            ROOT + "agents/overview": page("What are agents?", "Agents use tools."),
            ROOT + "agents/quickstart": page("Quickstart", "Create an agent."),
        },
    )
    report = extract_site(config, ROOT)
    assert files(report) == [
        "01-overview.md",
        "02-agents/01-what-are-agents.md",
        "02-agents/02-quickstart.md",
    ]
    text = (Path(report.output) / "02-agents/02-quickstart.md").read_text(encoding="utf-8")
    assert 'module: "Agents"' in text and f"source: {ROOT}agents/quickstart" in text and "Create an agent." in text
    assert all(i["status"] == "ok" for i in report.items)


def test_varredura_pelos_links_na_ordem_e_retomada_sem_sobrescrever(monkeypatch, config):
    pages = {
        "https://docs.example.com/robots.txt": "User-agent: *\nDisallow: /guide/private/\n",
        ROOT: page("Guide", "Start here.", ["intro.html", "setup/install.html", "private/x.html", "/blog/"]),
        ROOT + "intro.html": page("Intro", "Hello.", ["setup/install.html", "setup/config.html"]),
        ROOT + "setup/install.html": page("Install", "pip install."),
        ROOT + "setup/config.html": page("Config", "Edit the file."),
        ROOT + "private/x.html": page("Private", "secret"),
    }
    calls = fake_site(monkeypatch, pages)
    report = extract_site(config, ROOT, limit=3)
    assert files(report) == ["01-guide.md", "02-intro.md", "03-setup/01-install.md"]
    assert ROOT + "private/x.html" not in calls  # o robots.txt não permite
    assert not any("/blog/" in c for c in calls)  # fora do prefixo

    calls.clear()
    resumed = extract_site(config, ROOT, resume=True)
    assert resumed.output == report.output
    assert files(resumed) == ["01-guide.md", "02-intro.md", "03-setup/01-install.md", "03-setup/02-config.md"]
    assert sum(1 for i in resumed.items if i["status"] == "ok") == 4


def test_sitemap_quando_nao_ha_sumario(monkeypatch, config):
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{ROOT}b.html</loc></url><url><loc>{ROOT}a.html</loc></url>"
        "<url><loc>https://docs.example.com/blog/post.html</loc></url></urlset>"
    )
    fake_site(
        monkeypatch,
        {
            "https://docs.example.com/robots.txt": "User-agent: *\nSitemap: https://docs.example.com/sm.xml\n",
            "https://docs.example.com/sm.xml": sitemap,
            ROOT: page("Guide", "Start."),
            ROOT + "a.html": page("Page A", "Alpha."),
            ROOT + "b.html": page("Page B", "Beta."),
        },
    )
    report = extract_site(config, ROOT)
    assert files(report) == ["01-guide.md", "02-b.md", "03-a.md"]  # ordem do sitemap
    assert 'title: "Page B"' in (Path(report.output) / "02-b.md").read_text(encoding="utf-8")


def test_respeita_o_crawl_delay_do_robots(monkeypatch, config):
    sleeps = []
    monkeypatch.setattr("spa_content_extractor.site.time.sleep", sleeps.append)
    fake_site(
        monkeypatch,
        {
            "https://docs.example.com/robots.txt": "User-agent: *\nCrawl-delay: 5\n",
            ROOT: page("Guide", "Start.", ["a.html"]),
            ROOT + "a.html": page("A", "Alpha."),
        },
    )
    extract_site(config, ROOT, delay=1)
    assert sleeps and min(sleeps) >= 5


def test_exclude_depth_e_versao_em_markdown(monkeypatch, config):
    pages = {
        "https://docs.example.com/robots.txt": "User-agent: *\n",
        # página inicial fora do prefixo (como uma trilha que aponta para módulos): só serve para descobrir links
        "https://docs.example.com/paths/p1/": page("Path", "Path.", ["/guide/m1/", "/guide/es/m1/"]),
        ROOT + "m1/": page("Module", "Module.", ["u1", "u2"]),
        ROOT + "m1/u1": page("Unit 1", "HTML 1", ["/guide/m2/"]),
        ROOT + "m1/u2": page("Unit 2", "HTML 2"),
        ROOT
        + "m1/u1.md": "---\ntitle: Unit One\n---\n> ## Documentation Index\n> see /llms.txt\n\n# Unit One [[u1]]\n\nMD 1\n",
        ROOT + "m1/u2.md": "<!DOCTYPE html><html>not markdown</html>",
        ROOT + "m1.md": "# Module\n\nMD module\n",
    }
    calls = fake_site(monkeypatch, pages)
    report = extract_site(
        config, "https://docs.example.com/paths/p1/", prefix=ROOT, exclude=r"/es/", depth=2, markdown="{url}.md"
    )
    out = Path(report.output)
    assert files(report) == ["01-m1/01-unit-1.md", "01-m1/02-unit-2.md", "01-module.md"]
    assert not any("/es/" in c or "/m2/" in c for c in calls)  # --exclude e --depth cortam a varredura
    texts = {p.name: p.read_text(encoding="utf-8") for p in out.rglob("*.md")}
    one = next(text for name, text in texts.items() if "MD 1" in text)
    assert 'title: "Unit One"' in one and "[[u1]]" not in one and "Documentation Index" not in one
    assert any("HTML 2" in text for text in texts.values())  # .md que veio HTML: cai para o HTML


def test_render_le_a_pagina_montada_por_javascript(spa_url, config):
    url = spa_url.replace("index.html", "rendered/lesson.html")
    report = extract_site(config, url, render=True, content="article")
    text = next(Path(report.output).rglob("*.md")).read_text(encoding="utf-8")
    assert "deterministic code" in text and report.items[0]["status"] == "ok"
