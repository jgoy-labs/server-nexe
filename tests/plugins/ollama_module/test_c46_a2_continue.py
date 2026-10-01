"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/ollama_module/test_c46_a2_continue.py
Description: C4.6-a2 — Ollama resumes a cut answer, and a web reply has the
             same 2048-token ceiling MLX and llama.cpp already have.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import inspect
from unittest.mock import MagicMock

import pytest

from plugins.ollama_module.core.chat import (
    OllamaChat,
    chunk_is_continuable,
    model_can_continue,
    reply_ceiling,
)
from plugins.ollama_module.module import OllamaModule


def _chat() -> OllamaChat:
    client = MagicMock()
    client.base_url = "http://localhost:11434"
    return OllamaChat(client)


def _length(**extra):
    chunk = {"done": True, "done_reason": "length", "prompt_eval_count": 100, "eval_count": 2048}
    chunk.update(extra)
    return chunk


# ── which models ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "qwen3.5:4b", "qwen3.5:9b", "library/qwen3.5:9b", "Qwen3.5:4b",
    "gemma4:e4b", "gemma4:31b",
])
def test_a_current_family_can_continue(name):
    assert model_can_continue(name) is True


@pytest.mark.parametrize("name", [
    # Previous generation. A probe resumed them; they stay out on purpose.
    "qwen3:4b", "qwen3:8b", "qwen3:14b", "gemma3:4b", "gemma3:12b",
    # A longer token that merely starts with a current family.
    "qwen3.50:9b", "gemma40:7b",
    "qwen3-coder-next", "qwen3-coder-next:latest", "gpt-oss:20b",
    "llama3.2:3b", "qwq:32b", "deepseek-r1:32b", "", None,
])
def test_an_old_or_unmeasured_name_cannot_continue(name):
    """`gemma4` inside `gemma40` must not match, and the previous generation
    (qwen3, gemma3) is not a current family. Substring matching is what
    `can_think` does, and it is the wrong rule here."""
    assert model_can_continue(name) is False


def test_the_module_asks_the_same_function():
    module = OllamaModule()
    assert module.can_continue("gemma4:e4b") is True
    assert module.can_continue("qwen3-coder-next") is False
    assert module.can_continue(None) is False


def test_continue_final_is_an_explicit_parameter():
    """The door passes the flag only when the signature declares it by name."""
    param = inspect.signature(OllamaModule.chat).parameters["continue_final"]
    assert param.default is False
    assert param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


# ── the ceiling ────────────────────────────────────────────────────────────


def test_the_ceiling_defaults_to_2048(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_MAX_TOKENS", raising=False)
    assert reply_ceiling() == 2048


@pytest.mark.parametrize("raw", ["nope", "0", "-3", "", "2048.5"])
def test_a_bad_ceiling_stays_2048(monkeypatch, raw):
    monkeypatch.setenv("NEXE_OLLAMA_MAX_TOKENS", raw)
    assert reply_ceiling() == 2048


def test_a_positive_ceiling_is_honoured(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_MAX_TOKENS", "4096")
    assert reply_ceiling() == 4096


def test_the_payload_sends_the_ceiling(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_MAX_TOKENS", "1536")
    payload = _chat()._build_payload("qwen3.5:4b", [{"role": "user", "content": "hi"}], stream=True)
    assert payload["options"]["num_predict"] == 1536


# ── a resume ends inside the cut answer, with thinking off ────────────────


def test_continue_forces_think_off_even_when_the_env_asks_for_it(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_THINK", "true")
    messages = [
        {"role": "user", "content": "explica"},
        {"role": "assistant", "content": "Una resposta tall"},
    ]
    payload = _chat()._build_payload(
        "qwen3.5:4b", messages, stream=True, thinking_enabled=True, continue_final=True,
    )
    assert payload["think"] is False
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "Una resposta tall"


def test_without_continue_the_env_still_turns_thinking_on(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_THINK", "true")
    payload = _chat()._build_payload(
        "qwen3.5:4b", [{"role": "user", "content": "hi"}], stream=True, thinking_enabled=False,
    )
    assert payload["think"] is True


async def test_continue_refuses_before_calling_ollama():
    chat = _chat()
    with pytest.raises(ValueError, match="assistant"):
        async for _chunk in chat.chat(
            "qwen3.5:4b", [{"role": "user", "content": "hi"}], continue_final=True,
        ):
            pass


# ── the done chunk says whether Continue is honest ─────────────────────────


def test_continuable_needs_length_a_capable_model_and_room():
    assert chunk_is_continuable("qwen3.5:4b", _length(), num_ctx=8192, ceiling=2048) is True


def test_a_natural_stop_is_not_continuable():
    chunk = _length(done_reason="stop")
    assert chunk_is_continuable("qwen3.5:4b", chunk, num_ctx=8192, ceiling=2048) is False


def test_an_incapable_model_is_not_continuable():
    assert chunk_is_continuable("gpt-oss:20b", _length(), num_ctx=8192, ceiling=2048) is False


def test_missing_counts_fail_closed():
    chunk = {"done": True, "done_reason": "length"}
    assert chunk_is_continuable("gemma4:e4b", chunk, num_ctx=8192, ceiling=2048) is False


def test_no_room_for_another_reply_is_not_continuable():
    # 7000 + 2048 + 2048 + 512 = 11608, which does not fit in 8192.
    chunk = _length(prompt_eval_count=7000, eval_count=2048)
    assert chunk_is_continuable("qwen3.5:9b", chunk, num_ctx=8192, ceiling=2048) is False


def test_exactly_filling_the_window_is_not_continuable():
    # used + ceiling + 512 == num_ctx: the MLX gate is strict `<`.
    used_prompt = 8192 - 2048 - 2048 - 512
    chunk = _length(prompt_eval_count=used_prompt, eval_count=2048)
    assert chunk_is_continuable("gemma4:e4b", chunk, num_ctx=8192, ceiling=2048) is False


def test_the_done_chunk_is_stamped_and_a_token_is_not():
    chat = _chat()
    done = _length()
    stamped = chat._with_continuable("qwen3.5:4b", done, num_ctx=8192, ceiling=2048)
    assert stamped["continuable"] is True
    assert "continuable" not in done
    token = {"message": {"content": "A"}, "done": False}
    assert chat._with_continuable("qwen3.5:4b", token, 8192, 2048) is token


class _Breaker:
    class config:
        timeout_seconds = 1

    async def check_circuit(self):
        return True


async def test_chat_stamps_the_done_chunk_it_yields(monkeypatch):
    """Removing the stamp at the yield site (and leaving the helper) goes red."""
    chat = _chat()

    class _Parent:
        httpx = object()
        ollama_breaker = _Breaker()

    monkeypatch.setattr("plugins.ollama_module.core.chat._parent", lambda: _Parent())

    async def _fake_gen(*_args, **_kwargs):
        yield {"message": {"content": "cua"}}
        yield _length()

    chat._generate_with_answer_guarantee = _fake_gen
    messages = [
        {"role": "user", "content": "explica"},
        {"role": "assistant", "content": "Una resposta tall"},
    ]
    chunks = [c async for c in chat.chat("qwen3.5:4b", messages, continue_final=True)]
    assert chunks[0] == {"message": {"content": "cua"}}
    assert chunks[-1]["continuable"] is True
    assert chunks[-1]["done_reason"] == "length"
