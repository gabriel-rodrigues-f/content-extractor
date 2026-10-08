"""O extrator respeita o robots.txt; host cadastrado com autorização passa."""

from urllib import robotparser

import pytest

from spa_content_extractor.config import Config
from spa_content_extractor.robots import RobotsDisallowedError, ensure_allowed


@pytest.fixture
def robots_disallow_all(monkeypatch):
    monkeypatch.setattr(robotparser.RobotFileParser, "read", lambda self: None)
    monkeypatch.setattr(robotparser.RobotFileParser, "can_fetch", lambda self, agent, url: False)


def test_bloqueia_site_que_proibe_robos(robots_disallow_all):
    with pytest.raises(RobotsDisallowedError, match="robots.txt de exemplo.com"):
        ensure_allowed("https://exemplo.com/curso", Config())


def test_host_autorizado_passa(robots_disallow_all):
    config = Config(authorized_hosts={"treinamento.minhaempresa.com": "site próprio da empresa"})
    ensure_allowed("https://treinamento.minhaempresa.com/curso", config)  # não levanta


def test_localhost_e_livre():
    ensure_allowed("http://127.0.0.1:8000/index.html", Config())
