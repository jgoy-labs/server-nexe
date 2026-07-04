"""MC-030: composition helpers shared by every streaming ChatNode.execute().

Guards for plugins/_shared/chat_node.py — the genuinely identical boilerplate
(thread-safe stream bridge + common result envelope) extracted from MLXChatNode
and LlamaCppChatNode by COMPOSITION (no base class). The divergent generation
core of each engine stays untouched.
"""
from unittest.mock import Mock

from plugins._shared.chat_node import make_threadsafe_callback, base_chat_result


def test_threadsafe_callback_forwards_via_call_soon_threadsafe():
    loop = Mock()
    sink = Mock()
    cb = make_threadsafe_callback(loop, sink)
    cb("hola")
    # The worker thread must hand off to the loop, never call the sink directly.
    loop.call_soon_threadsafe.assert_called_once_with(sink, "hola")
    sink.assert_not_called()


def test_threadsafe_callback_noop_when_callback_is_none():
    loop = Mock()
    cb = make_threadsafe_callback(loop, None)
    cb("hola")  # must not raise
    loop.call_soon_threadsafe.assert_not_called()


def test_threadsafe_callback_noop_when_callback_not_callable():
    loop = Mock()
    cb = make_threadsafe_callback(loop, "not-callable")
    cb("hola")
    loop.call_soon_threadsafe.assert_not_called()


def test_base_chat_result_has_exactly_the_nine_common_keys():
    r = base_chat_result(
        response="hi", model_used="m", elapsed_ms=10, tokens=5,
        tokens_per_second=12.345, prompt_tokens=3, context_used=8,
        system_tokens=2, system_prompt="sys",
    )
    assert set(r) == {
        "response", "model_used", "elapsed_ms", "tokens", "tokens_per_second",
        "prompt_tokens", "context_used", "system_tokens", "system_prompt",
    }
    assert r["response"] == "hi"
    assert r["model_used"] == "m"
    assert r["system_prompt"] == "sys"


def test_base_chat_result_rounds_tps_to_one_decimal():
    r = base_chat_result(
        response="", model_used="", elapsed_ms=0, tokens=0,
        tokens_per_second=12.345, prompt_tokens=0, context_used=0,
        system_tokens=0, system_prompt="",
    )
    # Every engine reports tokens_per_second with the same precision.
    assert r["tokens_per_second"] == 12.3


def test_base_chat_result_passes_through_non_tps_fields_unchanged():
    # Only tokens_per_second is rounded; every other field passes through as-is.
    # This is the contract that distinguishes the helper from OllamaNode's envelope
    # (which truncates system_prompt[:200] and makes elapsed_ms a float).
    r = base_chat_result(
        response="r", model_used="m", elapsed_ms=10, tokens=5,
        tokens_per_second=1.0, prompt_tokens=3, context_used=8,
        system_tokens=2, system_prompt="full system prompt, never truncated",
    )
    assert r["elapsed_ms"] == 10 and isinstance(r["elapsed_ms"], int)
    assert r["system_prompt"] == "full system prompt, never truncated"
    assert r["context_used"] == 8


def test_base_chat_result_composes_with_engine_specific_keys():
    base = base_chat_result(
        response="r", model_used="", elapsed_ms=0, tokens=0,
        tokens_per_second=0, prompt_tokens=0, context_used=0,
        system_tokens=0, system_prompt="",
    )
    # mlx merges cache metrics, llama merges session_id/cache_hit — base survives.
    merged = {**base, "cache_active": True, "session_id": "s1"}
    assert merged["cache_active"] is True
    assert merged["session_id"] == "s1"
    assert merged["response"] == "r"
