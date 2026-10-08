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


async def test_mapeia_menu_abrindo_modulos_recolhidos(spa_url, tmp_path):
    items = await discover(fast_config(tmp_path), spa_url, headed=False)
    titles = [i.title for i in items]
    assert titles == [
        "Módulo 1 — Fundamentos",
        "Lição 1.1 — O que é BPM",
        "Lição 1.2 — Notação BPMN",
        "Módulo 2 — Simulação",
        "Lição 2.1 — Monte Carlo",
    ]
    assert [i.is_group for i in items] == [True, False, False, True, False]
    assert items[4].group == "Módulo 2 — Simulação"
    assert "Sair" not in titles  # controle de interface não é item


async def test_extrai_cada_licao_do_iframe_aninhado_sem_ruido(spa_url, tmp_path):
    report = await extract(fast_config(tmp_path), spa_url, headed=False)
    assert [i["status"] for i in report.items] == ["ok", "ok", "ok"]
    out = Path(report.output)
    files = sorted(p.name for p in (out / "raw").glob("*.md"))
    assert files == ["002-licao-1-1-o-que-e-bpm.md", "003-licao-1-2-notacao-bpmn.md", "005-licao-2-1-monte-carlo.md"]

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

    monte = (out / "raw" / files[2]).read_text(encoding="utf-8")
    assert "### Réplicas" in monte
    assert "use a mesma seed para comparar cenários" in monte  # texto dentro de shadow DOM
    assert "O que é BPM" not in monte  # não ficou o conteúdo da lição anterior

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["items"]) == 3


async def test_filtra_por_regex(spa_url, tmp_path):
    report = await extract(fast_config(tmp_path), spa_url, headed=False, only="monte carlo")
    assert [i["title"] for i in report.items] == ["Lição 2.1 — Monte Carlo"]


def test_slug():
    assert slugify("Lição 1.2 — Notação BPMN") == "licao-1-2-notacao-bpmn"
