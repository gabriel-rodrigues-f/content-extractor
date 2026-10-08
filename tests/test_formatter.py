"""Passo de formatação sem chamar a IA: divisão por títulos, front matter e credenciais da service key."""

import json
import os

from spa_content_extractor import formatter


def test_divide_documentos_grandes_nos_titulos():
    doc = "".join(f"# Seção {i}\n" + ("texto " * 300) + "\n" for i in range(6))
    parts = formatter.chunks(doc, limit=4_000)
    assert len(parts) > 1
    assert all(p.startswith("# Seção") for p in parts)
    assert "".join(parts) == doc  # nada se perde nem se repete


def test_separa_front_matter():
    front, body = formatter.split_front_matter('---\ntitle: "X"\n---\n\n# X\ntexto\n')
    assert front.startswith("---") and 'title: "X"' in front
    assert body == "# X\ntexto\n"


def test_service_key_vira_variaveis_do_sdk(tmp_path, monkeypatch):
    for name in (
        "AICORE_CLIENT_ID",
        "AICORE_CLIENT_SECRET",
        "AICORE_AUTH_URL",
        "AICORE_BASE_URL",
        "AICORE_RESOURCE_GROUP",
    ):
        monkeypatch.delenv(name, raising=False)
    fake = {
        "clientid": "id-de-teste",
        "clientsecret": "segredo-de-teste",
        "url": "https://exemplo.authentication.us10.hana.ondemand.com",
        "serviceurls": {"AI_API_URL": "https://api.ai.exemplo.ml.hana.ondemand.com"},
    }
    monkeypatch.setenv("AICORE_SERVICE_KEY", json.dumps(fake))
    formatter._load_credentials(tmp_path)
    assert os.environ["AICORE_AUTH_URL"].endswith("/oauth/token")
    assert os.environ["AICORE_BASE_URL"].endswith("/v2")
    assert os.environ["AICORE_RESOURCE_GROUP"] == "default"


def test_sem_chave_explica_o_que_fazer(tmp_path, monkeypatch):
    monkeypatch.delenv("AICORE_SERVICE_KEY", raising=False)
    try:
        formatter._load_credentials(tmp_path)
    except RuntimeError as error:
        assert "create-local-ai-core-key.sh" in str(error)
    else:
        raise AssertionError("deveria exigir a service key")
