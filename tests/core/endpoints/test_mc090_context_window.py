"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/tests/test_mc090_context_window.py
Description: MC-090 — the RAG token budget must reflect the context window the
    serving engine actually uses, not a fixed 8192.

    #965 rewrote the mechanism: the window now comes from the live engine's own
    get_context_window() (all three engines), instead of a special case for
    Ollama capped at DEFAULT_CONTEXT_WINDOW. That cap was written as "never more
    than the user asked for", but nothing in the product ever sets
    NEXE_DEFAULT_CONTEXT_WINDOW — so it really meant "always 8192", and MLX and
    llama.cpp were never adjusted at all.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.endpoints.chat import _trim_rag_context, get_effective_context_window
from core.endpoints.chat_sanitization import DEFAULT_CONTEXT_WINDOW


def _app_state(engine_key: str, window):
    """An app_state carrying one live engine module that reports `window`."""
    module = MagicMock()
    module.get_context_window.return_value = window
    return SimpleNamespace(modules={engine_key: module})


class TestTheWindowComesFromTheLiveEngine:

    @pytest.mark.parametrize(
        "engine,key",
        [("ollama", "ollama_module"), ("mlx", "mlx_module"), ("llama_cpp", "llama_cpp_module")],
    )
    def test_every_engine_reports_its_own_window(self, engine, key) -> None:
        assert get_effective_context_window(engine, _app_state(key, 16384)) == 16384

    def test_a_big_window_is_no_longer_capped(self) -> None:
        """#965, the actual bug: a 32768-token engine used to be planned for as
        if it were 8192, because of min(auto_num_ctx(), DEFAULT_CONTEXT_WINDOW)."""
        assert get_effective_context_window("ollama", _app_state("ollama_module", 32768)) == 32768

    def test_mlx_is_no_longer_pinned_to_the_default(self) -> None:
        """Before #965 this returned DEFAULT_CONTEXT_WINDOW no matter what MLX held."""
        window = get_effective_context_window("mlx", _app_state("mlx_module", 65536))
        assert window == 65536
        assert window != DEFAULT_CONTEXT_WINDOW


class TestItFallsBackInsteadOfFailing:
    """Window detection is a convenience. It must never be why a chat turn 500s."""

    def test_no_app_state_keeps_the_documented_default(self) -> None:
        assert get_effective_context_window("ollama") == DEFAULT_CONTEXT_WINDOW

    @pytest.mark.parametrize("engine", ["mlx", "llama_cpp", "", "unknown"])
    def test_engine_with_no_live_module_keeps_the_default(self, engine) -> None:
        assert get_effective_context_window(engine, SimpleNamespace(modules={})) == DEFAULT_CONTEXT_WINDOW

    def test_engine_that_cannot_answer_keeps_the_default(self) -> None:
        """None is the contract's "I cannot answer" — e.g. a module with no node."""
        assert get_effective_context_window("mlx", _app_state("mlx_module", None)) == DEFAULT_CONTEXT_WINDOW

    def test_engine_that_raises_keeps_the_default(self) -> None:
        module = MagicMock()
        module.get_context_window.side_effect = RuntimeError("boom")
        state = SimpleNamespace(modules={"ollama_module": module})
        assert get_effective_context_window("ollama", state) == DEFAULT_CONTEXT_WINDOW

    @pytest.mark.parametrize("bogus", [0, -1, "8192", 8192.0, True])
    def test_an_unusable_value_keeps_the_default(self, bogus) -> None:
        """A window of 0, a negative, or a string would poison every budget
        downstream — refuse it here rather than divide by it later."""
        state = _app_state("ollama_module", bogus)
        assert get_effective_context_window("ollama", state) == DEFAULT_CONTEXT_WINDOW

    def test_a_module_predating_the_contract_keeps_the_default(self) -> None:
        assert get_effective_context_window(
            "ollama", SimpleNamespace(modules={"ollama_module": object()})
        ) == DEFAULT_CONTEXT_WINDOW


class TestTheBudgetStillHonoursTheWindow:
    """Unchanged by #965: whatever the window is, the trim must scale with it."""

    def test_trim_respects_effective_window(self) -> None:
        context = "lorem ipsum dolor sit amet " * 800
        messages = [{"role": "user", "content": "hello"}]

        trimmed_small = _trim_rag_context(context, messages, effective_ctx_window=4096)
        trimmed_large = _trim_rag_context(context, messages, effective_ctx_window=8192)

        assert len(trimmed_small) < len(trimmed_large)

    def test_trim_defaults_to_full_window_when_unset(self) -> None:
        context = "lorem ipsum dolor sit amet " * 800
        messages = [{"role": "user", "content": "hello"}]

        trimmed_default = _trim_rag_context(context, messages)
        trimmed_explicit = _trim_rag_context(context, messages, effective_ctx_window=DEFAULT_CONTEXT_WINDOW)

        assert len(trimmed_default) == len(trimmed_explicit)
