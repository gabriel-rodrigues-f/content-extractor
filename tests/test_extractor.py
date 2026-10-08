"""Ponta a ponta contra a SPA de exemplo: menu recolhido, URL fixa, conteúdo num iframe dentro de outro iframe,
renderização progressiva com spinner, shadow DOM e ruído de interface."""

import json
import re
from pathlib import Path

import pytest

from spa_content_extractor.config import Config, Timing
from spa_content_extractor.extractor import discover, extract, slugify


def md_files(report) -> list[str]:
    raw = Path(report.output)
    return sorted(p.relative_to(raw).as_posix() for p in raw.rglob("*.md"))


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
    files = md_files(report)
    assert files == [  # cada grupo do menu é uma pasta; cada lição, um arquivo dentro dela
        "01-modulo-1-fundamentos/01-licao-1-1-o-que-e-bpm.md",
        "01-modulo-1-fundamentos/02-licao-1-2-notacao-bpmn.md",
        "01-modulo-1-fundamentos/03-unidade-1-b-avancado/01-licao-1-3-gateways.md",
        "02-modulo-2-simulacao/01-licao-2-1-monte-carlo.md",
    ]

    bpm = (out / files[0]).read_text(encoding="utf-8")
    assert 'module: "Módulo 1 — Fundamentos"' in bpm
    assert "# O que é BPM" in bpm
    assert "- Monitorar" in bpm  # a última parte da lista chegou depois: esperou estabilizar
    assert "BPM não é software" in bpm
    for noise in ("Próximo", "Anterior", "Marcar como concluído", "Selecione uma lição", "© 2026", "Imprimir"):
        assert noise not in bpm

    bpmn = (out / files[1]).read_text(encoding="utf-8")
    assert "| Gateway exclusivo | Decisão |" in bpmn  # tabela
    assert "```xml" in bpmn and '<bpmn:task id="Task_1" />' in bpmn  # código com linguagem
    assert "<!-- Imagem presente aqui: sem descrição -->" in bpmn  # imagem sem alt

    gateways = (out / files[2]).read_text(encoding="utf-8")
    assert 'module: "Módulo 1 — Fundamentos › Unidade 1.B — Avançado"' in gateways
    assert "paralelo que junta" in gateways

    monte = (out / files[3]).read_text(encoding="utf-8")
    assert "### Réplicas" in monte
    assert "use a mesma seed para comparar cenários" in monte  # texto dentro de shadow DOM
    assert "O que é BPM" not in monte  # não ficou o conteúdo da lição anterior

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [i["file"] for i in manifest["items"]] == files


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


async def test_sanfona_percorre_em_profundidade_desde_o_primeiro_modulo(spa_url, tmp_path):
    """O player abre na Lição 3.2 (cache) e o menu é sanfona: mesmo assim a ordem é a do curso, do Módulo 1 em diante."""
    url = spa_url.replace("index.html", "accordion.html")
    items = await discover(fast_config(tmp_path), url, headed=False)
    assert [" › ".join(i.path) for i in items] == [
        "Módulo 1 — Introdução",
        "Módulo 1 — Introdução › Lição 1.1 — Visão geral",
        "Módulo 1 — Introdução › Resumo",
        "Módulo 2 — Modelagem",
        "Módulo 2 — Modelagem › Lição 2.1 — Eventos",
        "Módulo 2 — Modelagem › Unidade 2.A — Gateways",
        "Módulo 2 — Modelagem › Unidade 2.A — Gateways › Lição 2.A.1 — Exclusivo",
        "Módulo 3 — Simulação",
        "Módulo 3 — Simulação › Lição 3.1 — Réplicas",
        "Módulo 3 — Simulação › Lição 3.2 — Cenários",
        "Módulo 3 — Simulação › Resumo",
    ]


async def test_sanfona_extrai_todas_as_licoes_na_ordem_do_curso(spa_url, tmp_path):
    url = spa_url.replace("index.html", "accordion.html")
    report = await extract(fast_config(tmp_path), url, headed=False)
    assert [i["path"] for i in report.items] == [
        "Módulo 1 — Introdução › Lição 1.1 — Visão geral",
        "Módulo 1 — Introdução › Resumo",
        "Módulo 2 — Modelagem › Lição 2.1 — Eventos",
        "Módulo 2 — Modelagem › Unidade 2.A — Gateways › Lição 2.A.1 — Exclusivo",
        "Módulo 3 — Simulação › Lição 3.1 — Réplicas",
        "Módulo 3 — Simulação › Lição 3.2 — Cenários",
        "Módulo 3 — Simulação › Resumo",
    ]
    assert all(i["status"] == "ok" for i in report.items)
    raw = Path(report.output)
    first = (raw / "01-modulo-1-introducao" / "01-licao-1-1-visao-geral.md").read_text(encoding="utf-8")
    assert "# Visão geral" in first  # a primeira lição extraída é a 1.1, não a 3.2 que o player abriu
    # "Resumo" repetido: cada um na pasta do próprio módulo, com o conteúdo dele
    assert "Processos são ativos" in (raw / "01-modulo-1-introducao" / "02-resumo.md").read_text(encoding="utf-8")
    assert "Compare cenários" in (raw / "03-modulo-3-simulacao" / "03-resumo.md").read_text(encoding="utf-8")
    cenarios = (raw / "03-modulo-3-simulacao" / "02-licao-3-2-cenarios.md").read_text(encoding="utf-8")
    assert "mesma seed" in cenarios  # a lição que já estava aberta também é extraída


async def test_resume_learning_espera_o_player_na_mesma_url(spa_url, tmp_path):
    """A página de entrada tem um sumário que parece menu; o clique troca a página pelo player só depois de 1,5 s e
    sem mudar a URL. O extrator precisa esperar o player — nunca mapear o sumário da entrada."""
    config = fast_config(tmp_path)
    config.start_click = ["Resume Learning"]
    url = spa_url.replace("index.html", "landing-spa.html")
    items = await discover(config, url, headed=False)
    paths = [" › ".join(i.path) for i in items]
    assert paths[0] == "Módulo 1 — Introdução"
    assert "Módulo 3 — Simulação › Resumo" in paths
    assert not any("Unidade 1: Introdução ao curso" in p for p in paths)

    report = await extract(config, url, headed=False, limit=1)
    assert [(i["path"], i["status"]) for i in report.items] == [
        ("Módulo 1 — Introdução › Lição 1.1 — Visão geral", "ok")
    ]


async def test_botao_que_nao_leva_a_lugar_nenhum_para_com_mensagem(spa_url, tmp_path):
    config = fast_config(tmp_path)
    config.start_click = ["Resume Learning"]
    config.timing.transition_timeout_s = 3
    with pytest.raises(LookupError, match="a página não mudou"):
        await discover(config, spa_url.replace("index.html", "landing-dead.html"), headed=False)


OUTLINE = [
    "Módulo 1 — Descoberta",
    "Módulo 1 — Descoberta › Tópico 1.1 — Entrevistas",
    "Módulo 1 — Descoberta › Tópico 1.2 — Mapeamento",
    "Módulo 2 — Desenho",
    "Módulo 2 — Desenho › Tópico 2.1 — Notação",
    "Módulo 2 — Desenho › Unidade 2.A — Padrões",
    "Módulo 2 — Desenho › Unidade 2.A — Padrões › Tópico 2.A.1 — Gateways",
    "Módulo 3 — Entrega",
    "Módulo 3 — Entrega › Tópico 3.1 — Publicação",
]


async def test_sanfona_sem_lista_reconhece_os_modulos_como_pastas(spa_url, tmp_path):
    """Sanfona de React sem <ul> (cabeçalho <h3><button> + painel irmão, que some quando fechado): o módulo é pasta, o
    painel não vira item e as âncoras do sumário da lição aberta não viram tópicos."""
    url = spa_url.replace("index.html", "outline.html")
    items = await discover(fast_config(tmp_path), url, headed=False)
    assert [" › ".join(i.path) for i in items] == OUTLINE
    assert [i.is_group for i in items] == [True, False, False, True, False, True, False, True, False]


async def test_sanfona_sem_lista_grava_uma_pasta_por_modulo(spa_url, tmp_path):
    report = await extract(fast_config(tmp_path), spa_url.replace("index.html", "outline.html"), headed=False)
    assert all(i["status"] == "ok" for i in report.items)
    assert md_files(report) == [
        "01-modulo-1-descoberta/01-topico-1-1-entrevistas.md",
        "01-modulo-1-descoberta/02-topico-1-2-mapeamento.md",
        "02-modulo-2-desenho/01-topico-2-1-notacao.md",
        "02-modulo-2-desenho/02-unidade-2-a-padroes/01-topico-2-a-1-gateways.md",
        "03-modulo-3-entrega/01-topico-3-1-publicacao.md",
    ]
    raw = Path(report.output)
    mapeamento = (raw / "01-modulo-1-descoberta" / "02-topico-1-2-mapeamento.md").read_text(encoding="utf-8")
    assert "O AS-IS registra" in mapeamento and "O TO-BE propõe" in mapeamento


async def test_modulo_que_revela_aulas_ao_ser_clicado_vira_pasta(spa_url, tmp_path):
    """Nada no menu diz que o módulo é grupo: as aulas só aparecem depois do clique. O extrator percebe e grava as
    aulas dentro da pasta do módulo — sem deixar um arquivo com o nome do módulo."""
    url = spa_url.replace("index.html", "lazy.html")
    items = await discover(fast_config(tmp_path), url, headed=False)
    assert [(" › ".join(i.path), i.is_group) for i in items] == [
        ("Módulo 1 — Base", True),
        ("Módulo 1 — Base › Aula 1.1 — Conceitos", False),
        ("Módulo 1 — Base › Aula 1.2 — Papéis", False),
        ("Módulo 2 — Prática", True),
        ("Módulo 2 — Prática › Aula 2.1 — Exercício", False),
    ]

    report = await extract(fast_config(tmp_path), url, headed=False)
    assert [(i["path"], i["status"]) for i in report.items] == [
        ("Módulo 1 — Base › Aula 1.1 — Conceitos", "ok"),
        ("Módulo 1 — Base › Aula 1.2 — Papéis", "ok"),
        ("Módulo 2 — Prática › Aula 2.1 — Exercício", "ok"),
    ]
    assert md_files(report) == [
        "01-modulo-1-base/01-aula-1-1-conceitos.md",
        "01-modulo-1-base/02-aula-1-2-papeis.md",
        "02-modulo-2-pratica/01-aula-2-1-exercicio.md",
    ]
    aula = (Path(report.output) / "01-modulo-1-base" / "02-aula-1-2-papeis.md").read_text(encoding="utf-8")
    assert "Papéis e responsabilidades" in aula
    manifest = json.loads((Path(report.output) / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["items"]) == 3


async def test_include_groups_guarda_a_pagina_do_modulo_dentro_da_pasta(spa_url, tmp_path):
    config = fast_config(tmp_path)
    config.selectors.include_groups = True
    report = await extract(config, spa_url.replace("index.html", "lazy.html"), headed=False)
    assert md_files(report) == [
        "01-modulo-1-base/00-modulo-1-base.md",
        "01-modulo-1-base/01-aula-1-1-conceitos.md",
        "01-modulo-1-base/02-aula-1-2-papeis.md",
        "02-modulo-2-pratica/00-modulo-2-pratica.md",
        "02-modulo-2-pratica/01-aula-2-1-exercicio.md",
    ]
    overview = (Path(report.output) / "01-modulo-1-base" / "00-modulo-1-base.md").read_text(encoding="utf-8")
    assert "Visão geral do Módulo 1" in overview


DETAILS = [
    "Módulo 1 — Fundamentos",
    "Módulo 1 — Fundamentos › Primeiros passos",
    "Módulo 1 — Fundamentos › Elementos do processo",
    "Módulo 1 — Fundamentos › Quiz",
    "Módulo 2 — Publicação",
    "Módulo 2 — Publicação › Trabalhando com feedback",
    "Módulo 2 — Publicação › Quiz",
]


def details_config(tmp_path: Path) -> Config:
    config = fast_config(tmp_path)
    config.timing.navigation_timeout_ms = 10_000  # um clique num item escondido falha em 10 s, não em 45
    return config


async def test_modulos_em_details_fechado_sao_abertos_antes_do_clique(spa_url, tmp_path):
    """Módulos em <details> fechados (o conteúdo ainda tem tamanho no Chrome), títulos com duração/status no mesmo link
    e o rodapé desenhado antes do menu: o menu é a árvore do curso, cada módulo é aberto antes de clicar nas lições e
    os títulos saem limpos."""
    url = spa_url.replace("index.html", "details.html")
    items = await discover(details_config(tmp_path), url, headed=False)
    assert [" › ".join(i.path) for i in items] == DETAILS
    assert [i.is_group for i in items] == [True, False, False, False, True, False, False]


async def test_modulos_em_details_viram_pastas_com_as_licoes(spa_url, tmp_path):
    report = await extract(details_config(tmp_path), spa_url.replace("index.html", "details.html"), headed=False)
    assert [(i["path"], i["status"]) for i in report.items] == [(p, "ok") for p in DETAILS if p.count("›") == 1]
    assert md_files(report) == [
        "01-modulo-1-fundamentos/01-primeiros-passos.md",
        "01-modulo-1-fundamentos/02-elementos-do-processo.md",
        "01-modulo-1-fundamentos/03-quiz.md",
        "02-modulo-2-publicacao/01-trabalhando-com-feedback.md",
        "02-modulo-2-publicacao/02-quiz.md",
    ]
    raw = Path(report.output)
    first = (raw / "01-modulo-1-fundamentos" / "01-primeiros-passos.md").read_text(encoding="utf-8")
    assert "# Primeiros passos" in first and "Comece pelo mapa" in first
    # o menu mora dentro do <main>, ao lado da lição: nada dele, do banner nem do "foi útil? / próxima lição" entra
    for noise in ("Elementos do processo", "3 min", "Concluído", "Assine o plano", "foi útil", "Próxima lição"):
        assert noise not in first
    assert "fundamentos" in (raw / "01-modulo-1-fundamentos" / "03-quiz.md").read_text(encoding="utf-8")
    assert "publicação" in (raw / "02-modulo-2-publicacao" / "02-quiz.md").read_text(encoding="utf-8")


async def test_cada_curso_ganha_uma_pasta_numerada_direto_em_output(spa_url, tmp_path):
    """output/00-<curso>/<data-hora>/…, output/01-<curso>/…: sem host e sem raw/. Repetir um curso reaproveita a pasta
    dele e cria outra extração com a data."""
    config = fast_config(tmp_path)
    first = await extract(config, spa_url.replace("index.html", "lazy.html"), headed=False, limit=1)
    await extract(config, spa_url.replace("index.html", "outline.html"), headed=False, limit=1)
    again = await extract(config, spa_url.replace("index.html", "lazy.html"), headed=False, limit=1)
    config.course_name = "Meu curso"
    await extract(config, spa_url.replace("index.html", "details.html"), headed=False, limit=1)

    assert sorted(p.name for p in config.output_dir.iterdir()) == [
        "00-player-com-aulas-sob-demanda",  # título da página de entrada
        "01-player-com-sanfona-sem-lista",
        "02-meu-curso",  # --name
    ]
    course = config.output_dir / "00-player-com-aulas-sob-demanda"
    assert Path(first.output).parent == Path(again.output).parent == course
    assert re.fullmatch(r"\d{8}-\d{6}", Path(first.output).name)
    assert Path(first.output) != Path(again.output)  # duas extrações, duas pastas de data
    assert (Path(first.output) / "manifest.json").exists()
    assert (Path(first.output) / "01-modulo-1-base" / "01-aula-1-1-conceitos.md").exists()
