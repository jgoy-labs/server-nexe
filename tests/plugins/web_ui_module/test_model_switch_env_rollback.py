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
