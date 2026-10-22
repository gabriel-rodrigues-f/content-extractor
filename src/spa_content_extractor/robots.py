"""Respeito ao robots.txt: o extrator só roda onde o site permite robôs ou onde há autorização registrada.

A avaliação segue a RFC 9309 (a do Google), não o `urllib.robotparser` da biblioteca padrão, que usa a primeira regra
que casa e não entende curingas: com ele, `Disallow: /` seguido de `Allow: /` (SAP Community, Discovery Center) vira
"proibido" e regras como `Disallow: /*?ticket=` derrubam o site inteiro. Pela RFC:
- valem os grupos cujo `User-agent` casa com o nosso nome; sem nenhum, os de `*` (vários grupos iguais se somam);
- `*` casa qualquer sequência e `$` no fim ancora o fim da URL (caminho + query);
- vence a regra mais específica (padrão mais longo); empate entre `Allow` e `Disallow` → `Allow`;
- `Disallow:` vazio não proíbe nada; nenhuma regra casando → permitido;
- robots.txt com 4xx = sem restrições; falha de rede ou 5xx = segue com ritmo educado (e avisa).
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .config import Config

log = logging.getLogger(__name__)

USER_AGENT = "spa-content-extractor"
_LOCAL = {"localhost", "127.0.0.1", "::1"}


class RobotsDisallowedError(PermissionError):
    pass


@dataclass
class RobotsRules:
    rules: list[tuple[bool, str, re.Pattern]] = field(default_factory=list)  # (allow, padrão, regex)
    crawl_delay: float = 0.0

    @classmethod
    def parse(cls, text: str, agent: str = USER_AGENT) -> RobotsRules:
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        lines: list[tuple[str, str]] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if lines:  # começa um grupo novo
                    groups.append((agents, lines))
                    agents, lines = [], []
                agents.append(value.lower())
            elif key in {"allow", "disallow", "crawl-delay"} and agents:
                lines.append((key, value))
        if agents:
            groups.append((agents, lines))
        token = agent.lower()
        mine = [g for g in groups if any(a != "*" and a in token for a in g[0])]
        chosen = mine or [g for g in groups if "*" in g[0]]
        result = cls()
        for _, group_lines in chosen:
            for key, value in group_lines:
                if key == "crawl-delay":
                    try:
                        result.crawl_delay = max(result.crawl_delay, float(value))
                    except ValueError:
                        pass
                elif value:  # "Disallow:" vazio não proíbe nada
                    result.rules.append((key == "allow", value, _pattern(value)))
        return result

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
        best: tuple[int, bool] | None = None  # (comprimento do padrão, allow)
        for allow, pattern, regex in self.rules:
            if regex.match(target):
                candidate = (len(pattern), allow)
                if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and allow):
                    best = candidate
        return True if best is None else best[1]


def _pattern(value: str) -> re.Pattern:
    anchored = value.endswith("$")
    body = re.escape(value[:-1] if anchored else value).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def load_robots(url: str) -> tuple[RobotsRules, str]:
    """(regras, texto) do robots.txt do site da URL."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            return RobotsRules(), ""  # RFC 9309: robots.txt inexistente/inacessível (4xx) = sem restrições
        log.warning("robots.txt de %s respondeu %s; seguindo com ritmo educado", parsed.netloc, error.code)
        return RobotsRules(), ""
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning(
            "robots.txt de %s indisponível (%s); seguindo com ritmo educado", parsed.netloc, type(error).__name__
        )
        return RobotsRules(), ""
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        return RobotsRules(), ""  # site que devolve uma página HTML no lugar do robots.txt (ex.: d2l.ai)
    return RobotsRules.parse(text), text


def ensure_allowed(url: str, config: Config) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in _LOCAL or host.endswith((".localhost", ".test")):
        return  # desenvolvimento e testes
    authorization = config.authorized_hosts.get(host) or config.authorized_hosts.get(parsed.netloc)
    if authorization:
        log.warning("%s: execução autorizada (%s)", host, authorization)
        return
    rules, _ = load_robots(url)
    if not rules.allowed(url):
        raise RobotsDisallowedError(
            f"O robots.txt de {host} não permite robôs nesta URL. Use o extrator só em sites que permitem ou, se o site "
            "for seu ou houver permissão por escrito, cadastre o host em authorized_hosts no extractor.toml."
        )
