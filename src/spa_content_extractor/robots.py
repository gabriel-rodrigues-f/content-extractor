"""Respeito ao robots.txt: o extrator só roda onde o site permite robôs ou onde há autorização registrada."""

from __future__ import annotations

import logging
from urllib import robotparser
from urllib.parse import urlparse

from .config import Config

log = logging.getLogger(__name__)

USER_AGENT = "spa-content-extractor"
_LOCAL = {"localhost", "127.0.0.1", "::1"}


class RobotsDisallowedError(PermissionError):
    pass


def ensure_allowed(url: str, config: Config) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in _LOCAL or host.endswith((".localhost", ".test")):
        return  # desenvolvimento e testes
    authorization = config.authorized_hosts.get(host) or config.authorized_hosts.get(parsed.netloc)
    if authorization:
        log.warning("%s: execução autorizada (%s)", host, authorization)
        return
    robots = robotparser.RobotFileParser(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try:
        robots.read()
    except OSError as error:
        log.warning("robots.txt de %s indisponível (%s); seguindo com ritmo educado", host, type(error).__name__)
        return
    if not robots.can_fetch(USER_AGENT, url):
        raise RobotsDisallowedError(
            f"O robots.txt de {host} não permite robôs nesta URL. Use o extrator só em sites que permitem ou, se o site "
            "for seu ou houver permissão por escrito, cadastre o host em authorized_hosts no extractor.toml."
        )
