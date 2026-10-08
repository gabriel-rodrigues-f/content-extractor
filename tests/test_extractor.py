"""Ponta a ponta contra a SPA de exemplo: menu recolhido, URL fixa, conteúdo num iframe dentro de outro iframe,
renderização progressiva com spinner, shadow DOM e ruído de interface."""

import json
from pathlib import Path

from spa_content_extractor.config import Config, Timing
from spa_content_extractor.extractor import discover, extract, slugify


def fast_config(tmp_path: Path) -> Config:
    config = Config(timing=Timing(min_delay_s=0.05, max_delay_s=0.1, pre_click_delay_s=(0.0, 0.05)))
    config.output_dir = tmp_path / "output"
    config.auth_dir = tmp_path / ".auth"
    return config


async def test_mapeia_menu_abrindo_niveis_recolhidos(spa_url, tmp_path):
    items = await discover(fast_config(tmp_path), spa_url, headed=False)
    assert [i.title for i in items] == [
        "Módulo 1 — Fundamentos",
        "Lição 1.1 — O que é BPM",
        "Lição 1.2 — Notação BPMN",
        "Unidade 1.B — Avançado",  # segundo nível: data-state, sem aria-expanded
        "Lição 1.3 — Gateways",
        "Módulo 2 — Simulação",
        "Lição 2.1 — Monte Carlo",
    ]
    assert [i.is_group for i in items] == [True, False, False, True, False, True, False]
    assert items[4].group == "Módulo 1 — Fundamentos › Unidade 1.B — Avançado"
    assert items[6].group == "Módulo 2 — Simulação"
    assert "Sair" not in [i.title for i in items]  # controle de interface não é item


async def test_extrai_cada_licao_do_iframe_aninhado_sem_ruido(spa_url, tmp_path):
    report = await extract(fast_config(tmp_path), spa_url, headed=False)
    assert [i["status"] for i in report.items] == ["ok", "ok", "ok", "ok"]
    out = Path(report.output)
    files = sorted(p.name for p in (out / "raw").glob("*.md"))
    assert files == [
        "002-licao-1-1-o-que-e-bpm.md",
        "003-licao-1-2-notacao-bpmn.md",
        "005-licao-1-3-gateways.md",
        "007-licao-2-1-monte-carlo.md",
    ]

    bpm = (out / "raw" / files[0]).read_text(encoding="utf-8")
    assert 'module: "Módulo 1 — Fundamentos"' in bpm
    assert "# O que é BPM" in bpm
    assert "- Monitorar" in bpm  # a última parte da lista chegou depois: esperou estabilizar
    assert "BPM não é software" in bpm
    for noise in ("Próximo", "Anterior", "Marcar como concluído", "Selecione uma lição", "© 2026", "Imprimir"):
        assert noise not in bpm

    bpmn = (out / "raw" / files[1]).read_text(encoding="utf-8")
    assert "| Gateway exclusivo | Decisão |" in bpmn  # tabela
    assert "```xml" in bpmn and '<bpmn:task id="Task_1" />' in bpmn  # código com linguagem
    assert "<!-- Imagem presente aqui: sem descrição -->" in bpmn  # imagem sem alt

    gateways = (out / "raw" / files[2]).read_text(encoding="utf-8")
    assert 'module: "Módulo 1 — Fundamentos › Unidade 1.B — Avançado"' in gateways
    assert "paralelo que junta" in gateways

    monte = (out / "raw" / files[3]).read_text(encoding="utf-8")
    assert "### Réplicas" in monte
    assert "use a mesma seed para comparar cenários" in monte  # texto dentro de shadow DOM
    assert "O que é BPM" not in monte  # não ficou o conteúdo da lição anterior

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["items"]) == 4


async def test_filtra_por_regex(spa_url, tmp_path):
    report = await extract(fast_config(tmp_path), spa_url, headed=False, only="monte carlo")
    assert [i["title"] for i in report.items] == ["Lição 2.1 — Monte Carlo"]


def test_slug():
    assert slugify("Lição 1.2 — Notação BPMN") == "licao-1-2-notacao-bpmn"


async def test_resume_learning_na_mesma_aba(spa_url, tmp_path):
    config = fast_config(tmp_path)
    config.start_click = ["Resume learning"]
    landing = spa_url.replace("index.html", "landing.html")
    items = await discover(config, landing, headed=False)
    assert "Lição 1.3 — Gateways" in [i.title for i in items]


async def test_resume_learning_em_nova_aba(spa_url, tmp_path):
    config = fast_config(tmp_path)
    config.start_click = ["Resume learning"]
    landing = spa_url.replace("index.html", "landing-newtab.html")
    report = await extract(config, landing, headed=False, only="gateways")
    assert [(i["title"], i["status"]) for i in report.items] == [("Lição 1.3 — Gateways", "ok")]


async def test_botao_de_entrada_inexistente_explica(spa_url, tmp_path):
    config = fast_config(tmp_path)
    config.start_click = ["Botão que não existe"]
    config.timing = Timing(min_delay_s=0.0, max_delay_s=0.0, pre_click_delay_s=(0.0, 0.0))
    try:
        await discover(config, spa_url.replace("index.html", "landing.html"), headed=False)
    except LookupError as error:
        assert "Botão que não existe" in str(error)
    else:
        raise AssertionError("deveria avisar que o botão não existe")
