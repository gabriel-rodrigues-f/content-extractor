"""O extrator respeita o robots.txt pela RFC 9309; host cadastrado com autorização passa."""

import pytest

from spa_content_extractor.config import Config
from spa_content_extractor.robots import RobotsDisallowedError, RobotsRules, ensure_allowed


@pytest.fixture
def robots_disallow_all(monkeypatch):
    monkeypatch.setattr(
        "spa_content_extractor.robots.load_robots", lambda url: (RobotsRules.parse("User-agent: *\nDisallow: /"), "")
    )


def test_bloqueia_site_que_proibe_robos(robots_disallow_all):
    with pytest.raises(RobotsDisallowedError, match="robots.txt de exemplo.com"):
        ensure_allowed("https://exemplo.com/curso", Config())


def test_host_autorizado_passa(robots_disallow_all):
    config = Config(authorized_hosts={"treinamento.minhaempresa.com": "site próprio da empresa"})
    ensure_allowed("https://treinamento.minhaempresa.com/curso", config)  # não levanta


def test_localhost_e_livre():
    ensure_allowed("http://127.0.0.1:8000/index.html", Config())


def test_empate_entre_disallow_e_allow_vale_o_allow():
    # pages.community.sap.com e discovery-center.cloud.sap: "Disallow: /" seguido de "Allow: /"
    rules = RobotsRules.parse("User-agent: *\nDisallow: /\nAllow: /\nDisallow: /protected/*\n")
    assert rules.allowed("https://pages.community.sap.com/topics/task-center/faq")
    assert not rules.allowed("https://discovery-center.cloud.sap/protected/x")


def test_curingas_e_regra_mais_especifica():
    text = (
        "User-agent: *\nCrawl-delay: 5\nDisallow: /t5/forums/forumtopicprintpage\nDisallow: /*?ticket=\n"
        "Disallow: /*nobounce\nDisallow: /*.drawio$\nDisallow: /docs/\nAllow: /docs/ref-arch/\n"
        "User-agent: GPTBot\nDisallow: /\n"
    )
    rules = RobotsRules.parse(text)
    assert rules.crawl_delay == 5
    assert rules.allowed("https://community.sap.com/t5/technology-blog-posts-by-members/x/ba-p/14470964")
    assert not rules.allowed("https://community.sap.com/t5/forums/forumtopicprintpage/x")
    assert not rules.allowed("https://community.sap.com/t5/x?ticket=abc")
    assert rules.allowed("https://architecture.learning.sap.com/docs/ref-arch/c1e07f")  # Allow mais longo vence
    assert not rules.allowed("https://architecture.learning.sap.com/docs/other")
    # o Allow mais longo vence até o $: /docs/ref-arch/ (15) > /*.drawio$ (10)
    assert rules.allowed("https://architecture.learning.sap.com/docs/ref-arch/c1e07f/a.drawio")
    architecture = RobotsRules.parse("User-agent: *\nDisallow: /404.html\nDisallow: /*.json$\nDisallow: /*.drawio$\n")
    assert not architecture.allowed("https://architecture.learning.sap.com/docs/ref-arch/c1e07f/drawio/a.drawio")
    assert architecture.allowed("https://architecture.learning.sap.com/docs/ref-arch/c1e07f")
    assert not RobotsRules.parse(text, agent="GPTBot/1.0").allowed("https://x/anything")  # grupo próprio do agente
