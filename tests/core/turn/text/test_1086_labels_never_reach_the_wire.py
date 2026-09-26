"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/text/test_1086_labels_never_reach_the_wire.py
Description: #1086 and its family — the model copies the prompt's section
             labels ([USER MEMORY], [CONTEXT a1b2c3d4] …) into its answer.
             Seen live 25/09 in the web UI: "(Fuente: [USER MEMORY])".
             Neither door streams them any more, split across chunks or not.
             The web UI still gets the memory tags: its badges read them.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.turn.text.tags import TagStreamFilter
from tests.plugins.web_ui_module.test_raonament_ui_wire import _msg, _wire
from tests.core.turn.text.test_v1_stream_is_clean import _content, _stream_v1  # noqa: F401 — fixture below


REPLY = ["[CONTEXT a1b2c3d4] Sóc Nexe (Font: [USER MEM", "ORY]). [MEM_SAVE: L'usuari viu a Vic] Vegeu [1]."]


@pytest.mark.asyncio
async def test_the_web_wire_drops_the_labels_and_keeps_the_memory_tags():
    wire, _h, _e = await _wire([_msg(c) for c in REPLY], None)
    assert "USER MEMORY" not in wire and "[CONTEXT" not in wire
    assert "[MEM_SAVE: L'usuari viu a Vic]" in wire, "the saved-fact badge reads it"
    assert "Sóc Nexe" in wire and "Vegeu [1]." in wire


def test_v1_drops_labels_and_memory_tags(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-chat-key-9999")
    status, lines = _stream_v1(REPLY)
    text = _content(lines)
    assert status == 200
    assert "USER MEMORY" not in text and "[CONTEXT" not in text and "MEM_SAVE" not in text
    assert "Sóc Nexe" in text and "Vegeu [1]." in text


@pytest.mark.parametrize("keep", ["Vegeu [1].", "[Nota important]", "[TODO] fes-ho", "un array [a, b]"])
def test_ordinary_brackets_pass(keep):
    f = TagStreamFilter()
    assert f.feed(keep) + f.flush() == keep


def test_a_label_split_anywhere_is_dropped():
    text = "Segons [MEMORIA DE L'USUARI] vius a Vic."
    for cut in range(1, len(text)):
        f = TagStreamFilter(memory=False, labels=True)
        assert f.feed(text[:cut]) + f.feed(text[cut:]) + f.flush() == "Segons  vius a Vic."
