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
