"""F5.6 BUG-NC-18 part 2 — Tests for the runtime_state override singleton.

The singleton must:
  * accept only the four declared keys (typos fail loudly),
  * return None when no override is set,
  * favour the override over the environment in get_with_env_fallback,
  * clear on reset() so tests stay isolated.
"""

import pytest

from core.runtime_state import (
    get_override,
    get_with_env_fallback,
    reset,
    set_override,
)


@pytest.fixture(autouse=True)
def _isolate_runtime_state():
    reset()
    yield
    reset()


def test_unknown_key_raises_on_set():
    with pytest.raises(ValueError, match="unknown override key"):
        set_override("NEXE_BOGUS", "x")


def test_unknown_key_raises_on_get():
    with pytest.raises(ValueError, match="unknown override key"):
        get_override("NEXE_BOGUS")


def test_get_override_returns_none_when_unset():
    assert get_override("NEXE_MODEL_ENGINE") is None


def test_set_then_get_roundtrip():
    set_override("NEXE_MODEL_ENGINE", "mlx")
    assert get_override("NEXE_MODEL_ENGINE") == "mlx"


def test_empty_string_clears_override():
    set_override("NEXE_DEFAULT_MODEL", "llama3.2:3b")
    assert get_override("NEXE_DEFAULT_MODEL") == "llama3.2:3b"
    set_override("NEXE_DEFAULT_MODEL", "")
    assert get_override("NEXE_DEFAULT_MODEL") is None


def test_none_clears_override():
    set_override("NEXE_MLX_MODEL", "/tmp/foo")
    set_override("NEXE_MLX_MODEL", None)
    assert get_override("NEXE_MLX_MODEL") is None


def test_env_fallback_when_no_override(monkeypatch):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "ollama")
    assert get_with_env_fallback("NEXE_MODEL_ENGINE", "auto") == "ollama"


def test_default_when_neither_override_nor_env(monkeypatch):
    monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)
    assert get_with_env_fallback("NEXE_DEFAULT_MODEL", "fallback") == "fallback"


def test_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/from-env.gguf")
    set_override("NEXE_LLAMA_CPP_MODEL", "/from-ui.gguf")
    assert get_with_env_fallback("NEXE_LLAMA_CPP_MODEL", "") == "/from-ui.gguf"


def test_reset_clears_all_overrides():
    for key in (
        "NEXE_MODEL_ENGINE",
        "NEXE_DEFAULT_MODEL",
        "NEXE_MLX_MODEL",
        "NEXE_LLAMA_CPP_MODEL",
    ):
        set_override(key, "value")
    reset()
    for key in (
        "NEXE_MODEL_ENGINE",
        "NEXE_DEFAULT_MODEL",
        "NEXE_MLX_MODEL",
        "NEXE_LLAMA_CPP_MODEL",
    ):
        assert get_override(key) is None


def test_thread_safe_setters():
    """Concurrent setters must not lose values or corrupt the dict."""
    import threading

    keys = (
        "NEXE_MODEL_ENGINE",
        "NEXE_DEFAULT_MODEL",
        "NEXE_MLX_MODEL",
        "NEXE_LLAMA_CPP_MODEL",
    )

    def worker(key: str, value: str) -> None:
        for _ in range(200):
            set_override(key, value)
            assert get_override(key) == value

    threads = [
        threading.Thread(target=worker, args=(k, f"v-{k}"))
        for k in keys
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for k in keys:
        assert get_override(k) == f"v-{k}"
