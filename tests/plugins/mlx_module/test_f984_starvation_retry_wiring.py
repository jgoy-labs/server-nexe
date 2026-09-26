"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_f984_starvation_retry_wiring.py
Description: #984 — the detector is worth nothing if execute() never acts on
    it. These exercise the wiring: a starved first generation must be followed
    by exactly one retry with thinking OFF, and none of the healthy shapes may
    trigger a second generation at all.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from plugins.mlx_module.core.chat import MLXChatNode


STARVED = {
    "text": "<think>\nLet me work through this problem step by",
    "finish_reason": "length",
    "tokens": 2048, "prompt_tokens": 100, "tokens_per_second": 40.0,
}
ANSWERED = {
    "text": "Reben 5, 11 i 31 caramels.",
    "finish_reason": "stop",
    "tokens": 30, "prompt_tokens": 100, "tokens_per_second": 40.0,
}


def _node():
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = MagicMock(
        temperature=0.7, top_p=0.9, max_tokens=2048,
        max_session_caches=2, max_kv_size=65536, model_path="/tmp/fake",
    )
    return node


def _run(monkeypatch, first, second, *, thinking_enabled=True, is_vlm=False):
    """Drive execute() with generation stubbed; return (result, calls).

    `calls` records the `thinking` flag each generation was asked for, which is
    what the retry is actually about.
    """
    node = _node()
    calls: list[bool] = []
    results = [first, second]

    def _fake_generate(*args, **kwargs):
        # thinking is positional in both signatures: index 6 for the VLM path,
        # 7 for the text path (see the two functools.partial builders).
        calls.append(args[6] if is_vlm else args[7])
        return results[len(calls) - 1]

    monkeypatch.setattr(node, "_generate_vlm", _fake_generate, raising=False)
    monkeypatch.setattr(node, "_generate_blocking", _fake_generate, raising=False)
    monkeypatch.setattr(MLXChatNode, "_get_model", lambda self: (MagicMock(), MagicMock()))
    # execute() asks the loader per turn, not the class flag.
    monkeypatch.setattr(
        "plugins.mlx_module.core.chat.model_loader._detect_vlm_capability",
        lambda _path: is_vlm,
    )

    out = asyncio.run(node.execute({
        "system": "", "messages": [{"role": "user", "content": "q"}],
        "session_id": "t", "thinking_enabled": thinking_enabled,
    }))
    return out, calls


class TestRetryWiring:
    def test_a_starved_turn_is_retried_once_with_thinking_off(self, monkeypatch):
        out, calls = _run(monkeypatch, STARVED, ANSWERED)
        assert calls == [True, False], calls
        assert "caramels" in out["response"], "the retry's answer must win"
        assert out.get("thinking_retry") is True

    def test_a_healthy_turn_is_never_retried(self, monkeypatch):
        _, calls = _run(monkeypatch, ANSWERED, ANSWERED)
        assert calls == [True], "a turn that answered must not generate twice"

    def test_a_starved_turn_with_thinking_already_off_is_not_retried(self, monkeypatch):
        """No second chance to take: thinking was not what ate the ceiling."""
        _, calls = _run(monkeypatch, STARVED, ANSWERED, thinking_enabled=False)
        assert calls == [False], calls

    def test_the_retry_never_chains(self, monkeypatch):
        """A retry that starves again must stop, not loop."""
        _, calls = _run(monkeypatch, STARVED, STARVED)
        assert calls == [True, False], "exactly one retry, whatever it returns"


@pytest.mark.parametrize("is_vlm", [False, True])
def test_both_dispatch_paths_retry(monkeypatch, is_vlm):
    """A VLM-capable model routes every turn through the VLM runner, so the
    retry must be wired on both branches — that is the case measured."""
    _, calls = _run(monkeypatch, STARVED, ANSWERED, is_vlm=is_vlm)
    assert calls == [True, False], calls


def test_a_stopped_turn_is_never_retried(monkeypatch):
    """Stop means stop: a cancelled turn must not trigger a second generation.

    Without this the user presses Stop on a long reasoning block and the engine
    answers back with a generation nobody asked for — and burns the GPU doing it.
    """
    import threading

    node = _node()
    calls: list[bool] = []
    cancelled = threading.Event()
    cancelled.set()

    def _fake_generate(*args, **kwargs):
        calls.append(args[7])
        return STARVED

    monkeypatch.setattr(node, "_generate_blocking", _fake_generate, raising=False)
    monkeypatch.setattr(MLXChatNode, "_get_model", lambda self: (MagicMock(), MagicMock()))
    monkeypatch.setattr(
        "plugins.mlx_module.core.chat.model_loader._detect_vlm_capability",
        lambda _path: False,
    )

    asyncio.run(node.execute({
        "system": "", "messages": [{"role": "user", "content": "q"}],
        "session_id": "t", "thinking_enabled": True, "cancel_event": cancelled,
    }))
    assert calls == [True], "a stopped turn must generate exactly once"


def test_the_retry_closes_the_think_block_it_inherited(monkeypatch):
    """Without a closing tag the retry's answer never reaches the user.

    The web UI think parser keeps `in_think` across chunks, so the <think>
    the starved pass opened and never closed swallows every token that
    follows — including the whole retry. Exercised against the real parser,
    not just by asserting the string was emitted.
    """
    node = _node()
    emitted: list[str] = []
    calls = {"n": 0}

    def _gen(*args, **kwargs):
        # Emit through the callback exactly as a real generation does, so the
        # replay below sees the true wire order instead of a hand-built one.
        calls["n"] += 1
        result = STARVED if calls["n"] == 1 else ANSWERED
        callback = args[3]
        if callback is not None:
            callback(result["text"])
        return result

    monkeypatch.setattr(node, "_generate_blocking", _gen, raising=False)
    monkeypatch.setattr(MLXChatNode, "_get_model", lambda self: (MagicMock(), MagicMock()))
    monkeypatch.setattr(
        "plugins.mlx_module.core.chat.model_loader._detect_vlm_capability",
        lambda _path: False,
    )

    asyncio.run(node.execute({
        "system": "", "messages": [{"role": "user", "content": "q"}],
        "session_id": "t", "thinking_enabled": True,
        "stream_callback": lambda tok: emitted.append(tok),
    }))

    raws = [t["raw"] for t in emitted]
    assert "</think>\n" in raws, f"no closer was emitted: {raws}"

    # ADR-010: the plugin hands the caller {thinking, content}; the answer of
    # the retry must land in content, the starved reasoning in thinking —
    # read the way the core reads every engine chunk.
    from core.turn.text.chunks import parse_chunk

    parts = [parse_chunk(t) for t in emitted]
    answer = "".join(c for c, _ in parts)
    reasoning = "".join(t for _, t in parts)
    assert "caramels" in answer, f"the answer stayed inside the think block: {emitted!r}"
    assert "Let me work" in reasoning and "Let me work" not in answer


def test_a_failing_retry_keeps_the_first_pass_instead_of_losing_the_turn(monkeypatch):
    """The recovery must never be worse than not recovering.

    Before the guarantee, a starved turn still returned its truncated text with
    finish_reason=length. If the second generation raises — an OOM on the Metal
    allocator is the realistic one, since pass 1's KV is still resident — the
    user must get that turn back, not an error that loses everything.
    """
    node = _node()
    calls = {"n": 0}

    def _gen(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return STARVED
        raise RuntimeError("[metal::malloc] attempting to allocate 4.2 GB")

    monkeypatch.setattr(node, "_generate_blocking", _gen, raising=False)
    monkeypatch.setattr(MLXChatNode, "_get_model", lambda self: (MagicMock(), MagicMock()))
    monkeypatch.setattr(
        "plugins.mlx_module.core.chat.model_loader._detect_vlm_capability",
        lambda _path: False,
    )

    out = asyncio.run(node.execute({
        "system": "", "messages": [{"role": "user", "content": "q"}],
        "session_id": "t", "thinking_enabled": True,
    }))

    assert calls["n"] == 2, "the retry must have been attempted"
    # ADR-010: pass 1 was reasoning only — it survives as the turn's
    # reasoning, apart from an (empty) answer, instead of posing as one.
    assert out["thinking"] == STARVED["text"][len("<think>"):], "pass 1 must survive a failed retry"
    assert out["response"] == ""
    assert out.get("thinking_retry") is False
