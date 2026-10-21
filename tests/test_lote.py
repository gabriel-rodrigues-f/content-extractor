"""scripts/lote.py: parâmetros por linha do STATUS.md e o comando escolhido pela URL."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("lote", Path(__file__).parents[1] / "scripts" / "lote.py")
lote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lote)


def test_parametros_da_linha_e_comando_pela_url():
    line = "- [x] https://help.sap.com/docs/btp/x/mapping --subtree — 3/3 lições · 00-entra-id/00-btp"
    match = lote.ITEM.match(line)
    assert match.group(2) == "https://help.sap.com/docs/btp/x/mapping"
    assert lote.line_args(match.group(3)) == "--subtree"
    assert lote.line_args(lote.ITEM.match("- [ ] https://learning.sap.com/c --only 'Mapping Role'").group(3)) == (
        "--only 'Mapping Role'"
    )
    assert lote.line_args(lote.ITEM.match("- [ ] https://learning.sap.com/c").group(3)) == ""
    assert lote.command_for("https://help.sap.com/docs/btp/x") == "help"
    assert lote.command_for("https://learn.microsoft.com/en-us/entra/x") == "page"
    assert lote.command_for("https://learning.sap.com/courses/x") == "extract"
    assert lote.command_for("https://learning.sap.com/live-sessions/x") == "page"
    assert lote.ITEM.match("- [~] https://d2l.ai — aguardando adaptador") is None  # fila, o lote não roda


def test_workers_em_paralelo_nunca_dois_do_mesmo_site(tmp_path, monkeypatch):
    import threading
    import time

    from spa_content_extractor.config import Config

    status = tmp_path / "STATUS.md"
    status.write_text(
        "# Status\n\n## Docs\n"
        "- [ ] https://a.com/1\n- [ ] https://a.com/2\n- [ ] https://b.com/1\n"
        "- [~] https://c.com/fila — aguardando adaptador\n\n## Outro\n- [ ] https://c.com/1 site --delay 1\n",
        encoding="utf-8",
    )
    config = Config()
    config.output_dir = tmp_path
    monkeypatch.setattr(lote, "load_config", lambda path: config)
    running, peak, overlap, lock = set(), [0], [], threading.Lock()

    def fake_run(output, group, url, args):
        host = url.split("/")[2]
        with lock:
            if host in running:
                overlap.append(host)
            running.add(host)
            peak[0] = max(peak[0], len(running))
        time.sleep(0.05)
        with lock:
            running.discard(host)
        return True, f"ok {args}".strip()

    monkeypatch.setattr(lote, "run_item", fake_run)
    monkeypatch.setattr("sys.argv", ["lote.py", "--workers", "3"])
    assert lote.main() == 0
    lines = status.read_text(encoding="utf-8").splitlines()
    assert not overlap and peak[0] >= 2  # sites diferentes ao mesmo tempo, o mesmo site nunca
    assert "- [x] https://c.com/1 site --delay 1 — ok site --delay 1" in lines
    assert sum(line.startswith("- [x]") for line in lines) == 4
    assert "- [~] https://c.com/fila — aguardando adaptador" in lines  # fila intacta
    assert "## Outro — concluído" in lines and "## Docs" in lines  # Docs tem item [~]: não fecha


def test_item_em_andamento_de_lote_morto_volta_a_fila():
    lines = [
        "## G",
        "- [>] https://a.com/1 --subtree — em andamento (pid 999999)",
        f"- [>] https://a.com/2 — em andamento (pid {__import__('os').getpid()})",
        "- [ ] https://a.com/3",
    ]
    items = lote.pending_items(lines, None)
    assert [(i[2], i[3]) for i in items] == [("https://a.com/1", "--subtree"), ("https://a.com/3", "")]
