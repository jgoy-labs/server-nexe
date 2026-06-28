"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/tests/test_mc090_context_window.py
Description: MC-090 — the RAG token budget must reflect the context window the
    serving engine actually uses (Ollama auto_num_ctx, e.g. 4096 on 16GB), not
    a fixed 8192, so RAG context is not silently truncated. Ollama-only for
    1.0.7; other engines keep DEFAULT_CONTEXT_WINDOW.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from core.endpoints.chat import _trim_rag_context, get_effective_context_window
from core.endpoints.chat_sanitization import DEFAULT_CONTEXT_WINDOW


def test_effective_window_ollama_uses_num_ctx(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_NUM_CTX", "4096")
    assert get_effective_context_window("ollama") == 4096


def test_effective_window_ollama_capped_at_configured_budget(monkeypatch):
    # A big Ollama window must not push the RAG budget above the configured one.
    monkeypatch.setenv("NEXE_OLLAMA_NUM_CTX", "32768")
    assert get_effective_context_window("ollama") == DEFAULT_CONTEXT_WINDOW


@pytest.mark.parametrize("engine", ["mlx", "llama_cpp", "", "unknown"])
def test_effective_window_other_engines_keep_default(engine):
    # Only Ollama is adjusted in 1.0.7 (MLX max_kv_size != context window).
    assert get_effective_context_window(engine) == DEFAULT_CONTEXT_WINDOW


def test_effective_window_resilient_to_bad_num_ctx(monkeypatch):
    # A bad NEXE_OLLAMA_NUM_CTX (or any auto_num_ctx failure) must NOT break the
    # chat request — fall back to DEFAULT instead of propagating a 500.
    monkeypatch.setenv("NEXE_OLLAMA_NUM_CTX", "not-a-number")
    assert get_effective_context_window("ollama") == DEFAULT_CONTEXT_WINDOW


def test_trim_respects_effective_window(monkeypatch):
    # A smaller effective window must trim the RAG context MORE aggressively.
    context = "lorem ipsum dolor sit amet " * 800  # large RAG blob
    messages = [{"role": "user", "content": "hello"}]

    trimmed_small = _trim_rag_context(context, messages, effective_ctx_window=4096)
    trimmed_large = _trim_rag_context(context, messages, effective_ctx_window=8192)

    assert len(trimmed_small) < len(trimmed_large)  # smaller window → more trimming


def test_trim_defaults_to_full_window_when_unset():
    # Backward compatibility: no effective window → behaves as before (DEFAULT).
    context = "lorem ipsum dolor sit amet " * 800
    messages = [{"role": "user", "content": "hello"}]

    trimmed_default = _trim_rag_context(context, messages)
    trimmed_explicit = _trim_rag_context(context, messages, effective_ctx_window=DEFAULT_CONTEXT_WINDOW)

    assert len(trimmed_default) == len(trimmed_explicit)
