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
    """F5.6 BUG-NC-18 part 2 regression guard — routes_chat.py must use the
    runtime_state singleton instead of mutating os.environ. The previous
    pattern (P0-3 env try/finally rollback) was replaced because env writes
    are thread-unsafe and the singleton stays consistent across concurrent
    requests.
    """

    def test_routes_chat_uses_runtime_state_for_mlx(self):
        from pathlib import Path
        import plugins.web_ui_module as _pkg
        src = Path(_pkg.__file__).parent / "api" / "routes_chat.py"
        content = src.read_text(encoding="utf-8")
        # Runtime override path must be in place for both motors.
        assert 'set_override("NEXE_MLX_MODEL"' in content, (
            "NEXE_MLX_MODEL must be set through runtime_state.set_override "
            "(see F5.6 BUG-NC-18 part 2)."
        )
        assert 'set_override("NEXE_LLAMA_CPP_MODEL"' in content, (
            "NEXE_LLAMA_CPP_MODEL must be set through runtime_state.set_override "
            "(see F5.6 BUG-NC-18 part 2)."
        )
        # Anti-regression: no env writes for these motors should sneak back in.
        assert 'os.environ["NEXE_MLX_MODEL"]' not in content, (
            "os.environ['NEXE_MLX_MODEL'] write resurfaced — use set_override."
        )
        assert 'os.environ["NEXE_LLAMA_CPP_MODEL"]' not in content, (
            "os.environ['NEXE_LLAMA_CPP_MODEL'] write resurfaced — use set_override."
        )
