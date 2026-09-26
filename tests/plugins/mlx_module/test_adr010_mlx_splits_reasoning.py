"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_adr010_mlx_splits_reasoning.py
Description: ADR-010 — the MLX plugin splits its model's reasoning from the
             answer itself, and hands its caller {thinking, content} chunks.

The case the core could not handle alone: a chat template that opens
<think> in the PROMPT (Qwen3 / Qwen3.5 / Gemma-4), so the model's text only
ever carries the closer. Only the plugin knows that about its template.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.turn.text.chunks import parse_chunk
from plugins.mlx_module.core.chat import MLXChatNode
from tests.plugins.mlx_module.test_f966_text_golden_master import (  # noqa: F401 — the fixture
    _clean,
    _Gen,
    _model_dir,
    _node,
)


@pytest.fixture(autouse=True)
def _template(monkeypatch):
    monkeypatch.setattr(MLXChatNode, "_template_think_prefix", None)


async def _turn(tmp_path, monkeypatch, *texts, opens_think, **inputs):
    node = _node(_model_dir(tmp_path))
    monkeypatch.setattr(MLXChatNode, "_template_opens_think", lambda self: opens_think)
    g = _Gen(*texts)
    with g:
        result = await node.execute({
            "system": "", "messages": [{"role": "user", "content": "q"}],
            "stream_callback": g.collect, **inputs,
        })
    parts = [parse_chunk(c) for c in g.chunks]
    return result, "".join(t for _, t in parts), "".join(c for c, _ in parts), g


async def test_a_template_that_opens_the_block_is_split_by_the_plugin(tmp_path, monkeypatch):
    result, reasoning, answer, g = await _turn(
        tmp_path, monkeypatch, "pensa ", "un moment", "</think>\n\n", "Resposta.",
        opens_think=True, thinking_enabled=True,
    )
    assert (reasoning, answer) == ("pensa un moment", "Resposta.")
    assert "".join(g.deltas) == "pensa un moment</think>\n\nResposta.", "raw kept exact"
    assert (result["thinking"], result["response"]) == ("pensa un moment", "Resposta.")


async def test_with_thinking_off_the_template_probe_does_not_apply(tmp_path, monkeypatch):
    _result, reasoning, answer, _g = await _turn(
        tmp_path, monkeypatch, "Resposta directa.",
        opens_think=True, thinking_enabled=False,
    )
    assert (reasoning, answer) == ("", "Resposta directa.")


async def test_inline_tags_are_split_too(tmp_path, monkeypatch):
    result, reasoning, answer, _g = await _turn(
        tmp_path, monkeypatch, "<think>raona</th", "ink>Hola",
        opens_think=False, thinking_enabled=True,
    )
    assert (reasoning, answer) == ("raona", "Hola")
    assert result["response"] == "Hola"


async def test_continue_is_left_raw(tmp_path, monkeypatch):
    """FD-S6 resumes from the exact raw text — the legacy path, untouched."""
    node = _node(_model_dir(tmp_path))
    monkeypatch.setattr(MLXChatNode, "_template_opens_think", lambda self: True)
    g = _Gen("segueixo")
    with g:
        await node.execute({
            "system": "", "messages": [{"role": "user", "content": "q"},
                                       {"role": "assistant", "content": "comen"}],
            "stream_callback": g.collect, "continue_final": True,
        })
    assert g.chunks == ["segueixo"]
