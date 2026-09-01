"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_vlm_flag_reaches_the_v1_builder.py
Description: build_openai_response refuses to promote the VLM finish_reason
    guess to an OpenAI contract signal — but only if it can SEE that the turn
    was a VLM one. execute() re-wraps the runner's result into a fresh dict, so
    the single line carrying `vlm` through is what makes that gate work at all.
    Deleting it left every related test green while the guess flowed again.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from core.endpoints.chat_engines._common import build_openai_response
from plugins.mlx_module.core.chat import MLXChatNode


def _run_turn(monkeypatch, *, is_vlm: bool) -> dict:
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = MagicMock(
        temperature=0.7, top_p=0.9, max_tokens=2048,
        max_session_caches=2, max_kv_size=65536, model_path="/tmp/fake",
    )
    generated = {
        "text": "tallat a mig", "finish_reason": "length",
        "tokens": 16, "prompt_tokens": 10, "tokens_per_second": 5.0,
    }
    monkeypatch.setattr(node, "_generate_vlm", lambda *a, **k: generated, raising=False)
    monkeypatch.setattr(node, "_generate_blocking", lambda *a, **k: generated, raising=False)
    monkeypatch.setattr(MLXChatNode, "_get_model", lambda self: (MagicMock(), MagicMock()))
    monkeypatch.setattr(
        "plugins.mlx_module.core.chat.model_loader._detect_vlm_capability",
        lambda _path: is_vlm,
    )
    return asyncio.run(node.execute({
        "system": "", "messages": [{"role": "user", "content": "q"}],
        "session_id": "t", "thinking_enabled": False,
    }))


@pytest.mark.parametrize("is_vlm", [True, False])
def test_the_result_carries_which_path_produced_it(monkeypatch, is_vlm):
    result = _run_turn(monkeypatch, is_vlm=is_vlm)
    assert result.get("vlm") is is_vlm


def test_a_vlm_turn_does_not_reach_v1_as_a_ceiling_cut(monkeypatch):
    """End to end over the seam: engine result -> /v1 response.

    The VLM runner infers finish_reason from hitting the ceiling exactly, a
    guess it documents as false-positive on an EOS that lands there. Loading a
    VLM model routes every turn through that path, so the guess must not tell
    an OpenAI client to resume a complete answer.
    """
    result = _run_turn(monkeypatch, is_vlm=True)
    out = build_openai_response(result, "some-vlm", "mlx")
    assert out["choices"][0]["finish_reason"] == "stop"


def test_a_text_turn_still_reaches_v1_as_a_ceiling_cut(monkeypatch):
    """The twin: mlx_lm's own finish_reason is reliable and must survive."""
    result = _run_turn(monkeypatch, is_vlm=False)
    out = build_openai_response(result, "some-text-model", "mlx")
    assert out["choices"][0]["finish_reason"] == "length"
