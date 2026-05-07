"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_model_switch_env_rollback.py
Description: Regression guard P0-3 env rollback — `NEXE_MLX_MODEL` and
             `NEXE_LLAMA_CPP_MODEL` must be restored to their previous state
             after the UI model selector mutates them to build a `from_env()`.
             Without rollback, subsequent requests without `body.model`
             would inherit the mutated value.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os

import pytest

# These tests do not need to load the full FastAPI stack — they exercise
# the try/finally sequence that wraps the `os.environ` mutation
# inside routes_chat.py. We flatten the pattern into a helper function that
# reproduces the same logic; any change to `routes_chat.py` that breaks
# the rollback must be caught by a grep guard.


def _switch_with_rollback(env_var: str, new_value: str) -> str:
    """Replica of the try/finally pattern from `routes_chat.py` (P0-3 fix)."""
    prev = os.environ.get(env_var)
    try:
        os.environ[env_var] = new_value
        current = os.environ[env_var]
    finally:
        if prev is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = prev
    return current


class TestRollback:

    def test_unset_before_stays_unset_after(self, monkeypatch):
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        _switch_with_rollback("NEXE_MLX_MODEL", "/tmp/new-model")  # nosemgrep
        assert "NEXE_MLX_MODEL" not in os.environ

    def test_set_before_keeps_original_after(self, monkeypatch):
        monkeypatch.setenv("NEXE_MLX_MODEL", "/tmp/original")  # nosemgrep
        _switch_with_rollback("NEXE_MLX_MODEL", "/tmp/new-model")  # nosemgrep
        assert os.environ["NEXE_MLX_MODEL"] == "/tmp/original"  # nosemgrep

    def test_value_is_read_inside_the_window(self, monkeypatch):
        """The consumer (e.g. MLXConfig.from_env) reads the mutated value."""
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        value_seen = _switch_with_rollback("NEXE_MLX_MODEL", "/tmp/new-model")  # nosemgrep
        assert value_seen == "/tmp/new-model"  # nosemgrep

    def test_rollback_even_if_consumer_raises(self, monkeypatch):
        """Exception inside the try block must not break the rollback."""
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/tmp/original")  # nosemgrep

        prev = os.environ.get("NEXE_LLAMA_CPP_MODEL")
        with pytest.raises(RuntimeError):
            try:
                os.environ["NEXE_LLAMA_CPP_MODEL"] = "/tmp/new"  # nosemgrep
                raise RuntimeError("consumer failed")
            finally:
                if prev is None:
                    os.environ.pop("NEXE_LLAMA_CPP_MODEL", None)
                else:
                    os.environ["NEXE_LLAMA_CPP_MODEL"] = prev

        assert os.environ["NEXE_LLAMA_CPP_MODEL"] == "/tmp/original"  # nosemgrep


class TestSourceGuard:
    """Regression grep guard — the routes_chat.py file must have the
    explicit rollbacks because the `_switch_with_rollback` pattern here
    is only a didactic copy."""

    def test_routes_chat_has_mlx_rollback(self):
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "api" / "routes_chat.py"
        content = src.read_text(encoding="utf-8")
        # We look for the two markers that guarantee the try/finally P0-3.
        assert "_prev_mlx" in content, "MLX env rollback absent a routes_chat.py"
        assert "_prev_llama" in content, "LLAMA env rollback absent a routes_chat.py"
        assert 'os.environ.pop("NEXE_MLX_MODEL"' in content
        assert 'os.environ.pop("NEXE_LLAMA_CPP_MODEL"' in content
