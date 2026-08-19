"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_b121_cache_config.py
Description: B121 — the MLX prompt cache manager must take its max_size from
            config (NEXE_MLX_MAX_SESSION_CACHES), not a hardcoded literal 8.
            The singleton only honours max_size on its first call, so an
            operator who lowers the cap for RAM was being ignored.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core.chat import MLXChatNode

pytest.importorskip("mlx_lm", reason="mlx-lm is Apple-Silicon only")


class _Stop(Exception):
    """Sentinel: stop _generate_blocking_inner right after the cache call."""


def test_cache_manager_uses_config_max_session_caches():
    """B121: get_prompt_cache_manager must receive self.config.max_session_caches."""
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = MagicMock(max_session_caches=4, model_path="/tmp/model")
    node._get_model = MagicMock(return_value=(MagicMock(), MagicMock()))

    recorded = {}

    def _spy(max_size):
        recorded["max_size"] = max_size
        raise _Stop()

    with patch(
        "plugins.mlx_module.core.prompt_cache_manager.get_prompt_cache_manager",
        side_effect=_spy,
    ):
        with pytest.raises(_Stop):
            node._generate_blocking_inner(
                "system", [{"role": "user", "content": "hi"}], [], None, "sess1234"
            )

    # Must be the configured value (4), not the hardcoded literal 8.
    assert recorded["max_size"] == 4


def test_bare_factory_call_respects_env_default(monkeypatch):
    """B121: get_prompt_cache_manager() with no arg honours NEXE_MLX_MAX_SESSION_CACHES.

    reset_model() and get_pool_stats() call the factory WITHOUT a max_size, and
    the singleton only honours the first call. If the bare default were a
    hardcoded 8, one of those running before the first generation would pin the
    singleton to 8 and silently override the operator's lower RAM cap.
    """
    import plugins.mlx_module.core.prompt_cache_manager as pcm

    monkeypatch.setattr(pcm, "_prompt_cache_manager", None)
    monkeypatch.setenv("NEXE_MLX_MAX_SESSION_CACHES", "3")
    mgr = pcm.get_prompt_cache_manager()  # bare call, like reset_model/get_pool_stats
    assert mgr.max_size == 3
