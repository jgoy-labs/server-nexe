"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/cli/test_cli_reads_the_ui_wire.py
Description: `nexe chat` reads /ui/chat's wire the way the web client does
             (25/09, Jordi: "mostrar-ho net"). Before: <think> blocks,
             [MEM_SAVE:] tags and echoed section labels were printed raw,
             colon-less sentinels leaked as text, a save showed only as "MEM"
             and a delete or a pending forget not at all.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.cli.chat_cli import _handle_user_message
from core.cli.utils.api_client import UiStreamReader

WIRE = (
    "\x00[MODEL:qwen3.5:4b]\x00\x00[MODEL_READY]\x00<think>raona un moment</think>"
    "Hola [USER MEMORY] [MEM_SAVE: L'usuari viu a Vic] adéu"
    # The real wire since 25/09 (#1098): the note of what memory kept rides on
    # THIS turn, with the facts. Before, this fixture put a bare [MEM:1] next to
    # the tag — a wire production never sent (the note came one turn late).
    "\x00[MEM:1:L'usuari viu a Vic]\x00\x00[DEL:1:el gat es diu Mite]\x00\x00[PENDING_DELETE:el gos]\x00"
).encode()


def _read(wire: bytes, step: int) -> list:
    r = UiStreamReader()
    out = []
    for i in range(0, len(wire), step):
        out += r.feed(wire[i:i + step])
    return out + r.close()


@pytest.mark.parametrize("step", [1, 3, 7, 64, len(WIRE)])
def test_the_wire_reads_the_same_however_it_is_cut(step):
    items = _read(WIRE, step)
    answer = "".join(i for i in items if isinstance(i, str))
    metas = {k: v for i in items if isinstance(i, dict) and i.get("type") == "metadata"
             for k, v in i.items() if k != "type"}
    reasoning = "".join(i["text"] for i in items if isinstance(i, dict) and i.get("type") == "reasoning")
    saved = [i for i in items if isinstance(i, dict) and i.get("type") == "memory_tags"]

    assert answer == "Hola   adéu"
    assert "\x00" not in answer and "MODEL_READY" not in answer
    assert reasoning == "raona un moment"
    assert metas["MODEL"] == "qwen3.5:4b" and metas["MODEL_READY"] == "1"
    assert metas["DEL"] == "1:el gat es diu Mite" and metas["PENDING_DELETE"] == "el gos"
    assert metas["MEM"] == "1:L'usuari viu a Vic"
    assert saved == [{"type": "memory_tags", "saved": ["L'usuari viu a Vic"]}]


class _Client:
    def __init__(self, confirm_result):
        self.memory_confirm_delete = AsyncMock(return_value=confirm_result)
        self.memory_cancel_delete = AsyncMock(return_value=True)

    async def chat_ui_stream(self, **_):
        r = UiStreamReader()
        for item in r.feed(WIRE) + r.close():
            yield item


@pytest.mark.parametrize("confirmed", [True, False])
def test_the_turn_is_printed_clean_with_its_memory(capsys, confirmed):
    client = _Client({"deleted": 1, "deleted_facts": [{"text": "el gos"}]})
    with patch("core.cli.chat_cli.click.confirm", return_value=confirmed):
        asyncio.run(_handle_user_message("hola", client, "s", {}, False))
    out = capsys.readouterr().out
    assert "raonament (~" in out and "raona un moment" not in out, "folded by default"
    assert "Hola" in out and "adéu" in out
    assert "[MEM_SAVE" not in out and "USER MEMORY" not in out and "<think>" not in out
    assert "💾 Desat: L'usuari viu a Vic" in out
    assert "🗑 Esborrat: el gat es diu Mite" in out
    if confirmed:
        # C4.5: the confirmation names the session whose pending entry dies.
        client.memory_confirm_delete.assert_awaited_once_with("el gos", "s")
        client.memory_cancel_delete.assert_not_awaited()
        assert "🗑 Esborrat: el gos" in out
    else:
        client.memory_confirm_delete.assert_not_awaited()
        # #1136: the "no" reaches the server, or a bare "sí" next turn deletes it.
        client.memory_cancel_delete.assert_awaited_once_with("s")


def test_show_thinking_prints_the_reasoning(capsys):
    with patch("core.cli.chat_cli.click.confirm", return_value=False):
        asyncio.run(_handle_user_message("hola", _Client({}), "s", {}, False, show_thinking=True))
    assert "raona un moment" in capsys.readouterr().out


def test_a_fact_the_server_did_not_confirm_is_not_called_saved(capsys):
    """25/09 live: gemma3 wrote [MEM_SAVE: El meu nom és Nexe.] on its own and
    the server stored nothing (no MEM sentinel) — the CLI said "Desat"."""
    class _Unconfirmed(_Client):
        async def chat_ui_stream(self, **_):
            r = UiStreamReader()
            for item in r.feed("Hola [MEM_SAVE: El meu nom és Nexe.]".encode()) + r.close():
                yield item

    asyncio.run(_handle_user_message("hola", _Unconfirmed({}), "s", {}, False))
    assert "Desat" not in capsys.readouterr().out


def _wire_client(wire: str):
    class _W(_Client):
        async def chat_ui_stream(self, **_):
            r = UiStreamReader()
            for item in r.feed(wire.encode()) + r.close():
                yield item
    return _W({})


def test_a_tag_the_server_kept_nothing_of_is_not_called_saved(capsys):
    """[MEM:0]: the server looked and kept nothing — the tag stays a request."""
    wire = "Hola [MEM_SAVE: L'usuari es diu Joan]\x00[MEM:0]\x00"
    asyncio.run(_handle_user_message("hola", _wire_client(wire), "s", {}, False))
    assert "Desat" not in capsys.readouterr().out


def test_what_is_called_saved_is_the_servers_list_not_the_models(capsys):
    """The model wrote one thing, the atomiser and filters kept another: the
    CLI prints what is in memory."""
    wire = ("Fet! [MEM_SAVE: viu a Vic i treballa de fuster]"
            "\x00[MEM:2:L'usuari viu a Vic|L'usuari treballa de fuster]\x00")
    asyncio.run(_handle_user_message("hola", _wire_client(wire), "s", {}, False))
    out = capsys.readouterr().out
    assert "💾 Desat: L'usuari viu a Vic; L'usuari treballa de fuster" in out
    assert "viu a Vic i treballa" not in out
