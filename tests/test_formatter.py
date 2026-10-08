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


def test_formatacao_repete_as_pastas_do_curso(tmp_path, monkeypatch):
    class FakeFormatter:
        def __init__(self, project_root):
            pass

        def format_file(self, source, target):
            target.write_text(source.read_text(encoding="utf-8").upper(), encoding="utf-8")
            return 1

    monkeypatch.setattr(formatter, "Formatter", FakeFormatter)
    course = tmp_path / "output" / "00-curso"
    for run, text in (("20261008-150524", "antigo"), ("20261009-090000", "dois")):
        (course / run / "01-modulo" / "02-unidade").mkdir(parents=True)
        (course / run / "manifest.json").write_text("{}", encoding="utf-8")
        (course / run / "01-modulo" / "01-licao.md").write_text("um", encoding="utf-8")
        (course / run / "01-modulo" / "02-unidade" / "01-licao.md").write_text(text, encoding="utf-8")

    # a pasta do curso formata a extração mais recente, no mesmo caminho dentro de knowledge/
    results = formatter.format_run(course, tmp_path, only="unidade", knowledge_dir=tmp_path / "knowledge")
    assert results == [("01-modulo/02-unidade/01-licao.md", 1)]
    target = tmp_path / "knowledge" / "00-curso" / "20261009-090000" / "01-modulo" / "02-unidade" / "01-licao.md"
    assert target.read_text(encoding="utf-8") == "DOIS"
