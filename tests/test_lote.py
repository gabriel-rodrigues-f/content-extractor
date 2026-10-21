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
