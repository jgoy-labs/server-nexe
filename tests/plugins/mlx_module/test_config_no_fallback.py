"""
F5.4 Bug B — regression tests: MLXConfig must NOT fall back to NEXE_HOME
(project_root) when NEXE_MLX_MODEL is unset and auto-discover returns empty.

Empirical log evidence (G10 portàtil 2026-05-19):
    MLXConfig: model_path is empty. Set NEXE_MLX_MODEL or pass model_path.
    MLXConfig loaded: model=/Users/nexe/Library/Application Support/com.nexe.app/sidecar/app
    MLXConfig: model_path does not contain config.json (required by mlx-lm)
    MLXModule: Configuration invalid. Check NEXE_MLX_MODEL.
    mlx_module initialization returned False — removing from loaded modules

Same root cause as Bug C in llama_cpp_module:
  __post_init__ elif branch fires on empty path: `os.path.isabs("")` is False
  → `str(project_root / "")` returns `str(project_root)` = NEXE_HOME.

Plus: when validate() fails, initialize() returns False, which makes
core/lifespan_modules.py::initialize_plugin_modules pop the plugin from
app.state.modules. Then F5.3.1 restart_sidecar cannot re-activate it
because the plugin is gone from the registry.

Fix expected:
  - Empty model_path stays empty (no fallback to project_root).
  - initialize() returns True with state=not_configured when no model — plugin
    stays at registry so restart_sidecar can re-activate post-wizard.
  - health_check() reports HealthStatus.UNKNOWN with not_configured message.
  - When config IS set and valid, behavior unchanged (state=ready).
"""

from __future__ import annotations

import logging
import os
import sys
import types
from unittest.mock import patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Bug B, fault 1: empty model_path must NOT collapse into project_root
# ──────────────────────────────────────────────────────────────────────────────


class TestMLXConfigEmptyPathStaysEmpty:
    """__post_init__ must not transform empty string into project_root."""

    def test_empty_model_path_remains_empty_string(self):
        from plugins.mlx_module.core.config import MLXConfig
        config = MLXConfig(model_path="")
        assert config.model_path == "", (
            "Empty model_path was rewritten by __post_init__ to "
            f"{config.model_path!r}. The elif branch must guard against empty "
            "strings: `elif self.model_path and not os.path.isabs(...)`."
        )

    def test_relative_path_still_resolved(self):
        """Sanity check: empty guard must not break relative-path resolution."""
        from plugins.mlx_module.core.config import MLXConfig
        config = MLXConfig(model_path="models/test-model")
        assert os.path.isabs(config.model_path), (
            "Relative path resolution regressed — guard fix overshot."
        )

    def test_absolute_path_still_unchanged(self):
        from plugins.mlx_module.core.config import MLXConfig
        config = MLXConfig(model_path="/absolute/path/model")
        assert config.model_path == "/absolute/path/model"

    def test_tilde_path_still_expanded(self):
        from plugins.mlx_module.core.config import MLXConfig
        config = MLXConfig(model_path="~/models/test")
        assert not config.model_path.startswith("~")
        assert os.path.expanduser("~") in config.model_path


# ──────────────────────────────────────────────────────────────────────────────
# Bug B, fault 2: from_env with no env var must produce empty path
# ──────────────────────────────────────────────────────────────────────────────


class TestMLXConfigFromEnvWithNoModel:
    """When NEXE_MLX_MODEL is unset AND server.toml AND auto-discover return
    empty, the final model_path must remain empty (not project_root)."""

    def test_from_env_with_no_model_produces_empty_path(self, monkeypatch):
        from plugins.mlx_module.core.config import MLXConfig
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        # Force auto-discover to find nothing by pointing storage to empty tmp.
        # Both NEXE_STORAGE_PATH and NEXE_DATA_DIR drive get_models_dir().
        monkeypatch.delenv("NEXE_STORAGE_PATH", raising=False)
        monkeypatch.delenv("NEXE_DATA_DIR", raising=False)
        # Patch toml fallback and autodiscover to return empty
        with patch.object(MLXConfig, "_model_path_from_toml", return_value=""), \
             patch.object(MLXConfig, "_model_path_autodiscover", return_value=""):
            config = MLXConfig.from_env()

        assert config.model_path == "", (
            f"With no env var, no toml, no auto-discover, model_path must "
            f"remain empty, got: {config.model_path!r}. The previous fallback "
            "to project_root via str(project_root / '') caused MLXConfig to "
            "produce paths like NEXE_HOME (the app dir, not a model)."
        )

    def test_from_env_log_does_not_show_fake_path(self, caplog, monkeypatch):
        """The INFO log line emitted by from_env must say '(empty)' when no
        model is configured, not a fabricated project_root path."""
        from plugins.mlx_module.core import config as mlx_cfg

        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        monkeypatch.delenv("NEXE_STORAGE_PATH", raising=False)
        monkeypatch.delenv("NEXE_DATA_DIR", raising=False)
        with patch.object(mlx_cfg.MLXConfig, "_model_path_from_toml", return_value=""), \
             patch.object(mlx_cfg.MLXConfig, "_model_path_autodiscover", return_value=""):
            with caplog.at_level(logging.INFO, logger=mlx_cfg.__name__):
                mlx_cfg.MLXConfig.from_env()

        relevant = [r.message for r in caplog.records if "MLXConfig loaded" in r.message]
        assert relevant, "Expected at least one 'MLXConfig loaded' INFO log"
        for msg in relevant:
            # The log MUST indicate empty state, not a fake path
            assert "(empty)" in msg, (
                f"Expected '(empty)' marker in log when no model is "
                f"configured, got: {msg}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# Bug B, fault 3: MLXModule.initialize() must return True with not_configured
# ──────────────────────────────────────────────────────────────────────────────


class TestMLXModuleInitializeNotConfiguredState:
    """When no model is configured (env unset, toml empty, auto-discover
    empty), initialize() must return True (so the loader keeps it at the
    registry for restart_sidecar) AND mark state as not_configured.
    Previously initialize() returned False on validate failure, which made
    lifespan_modules.py::initialize_plugin_modules pop the plugin from
    app.state.modules — then restart_sidecar could not re-activate it."""

    @pytest.fixture
    def fresh_module(self):
        from plugins.mlx_module.module import MLXModule
        return MLXModule()

    @pytest.fixture
    def mock_metal_available(self, monkeypatch):
        """Force MLXConfig.is_metal_available() True so we test the no-model
        flow (not the no-Metal flow which is a separate concern)."""
        from plugins.mlx_module.core import config as mlx_cfg
        monkeypatch.setattr(
            mlx_cfg.MLXConfig, "is_metal_available", staticmethod(lambda: True)
        )
        yield

    @pytest.mark.asyncio
    async def test_initialize_with_no_model_returns_true_and_marks_not_configured(
        self, fresh_module, monkeypatch, mock_metal_available
    ):
        from plugins.mlx_module.core import config as mlx_cfg
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        monkeypatch.delenv("NEXE_STORAGE_PATH", raising=False)
        monkeypatch.delenv("NEXE_DATA_DIR", raising=False)
        with patch.object(mlx_cfg.MLXConfig, "_model_path_from_toml", return_value=""), \
             patch.object(mlx_cfg.MLXConfig, "_model_path_autodiscover", return_value=""):
            result = await fresh_module.initialize(context={})

        assert result is True, (
            "initialize() must return True when no model is configured — the "
            "plugin must stay at the registry for F5.3.1 restart_sidecar to "
            "re-activate it after the wizard completes. False would trigger "
            "plugin_modules.pop in core/lifespan_modules.py:99."
        )
        state = getattr(fresh_module, "_state", None)
        assert state == "not_configured", (
            f"Expected plugin._state == 'not_configured', got: {state!r}."
        )

    @pytest.mark.asyncio
    async def test_initialize_with_no_model_does_not_create_node(
        self, fresh_module, monkeypatch, mock_metal_available
    ):
        """MLXChatNode (which holds the model and KV cache) must NOT be
        created when no model is configured — empty config would just produce
        a broken node with confusing downstream errors."""
        from plugins.mlx_module.core import config as mlx_cfg
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        with patch.object(mlx_cfg.MLXConfig, "_model_path_from_toml", return_value=""), \
             patch.object(mlx_cfg.MLXConfig, "_model_path_autodiscover", return_value=""):
            await fresh_module.initialize(context={})

        assert fresh_module._node is None, (
            "self._node must be None when no model is configured."
        )

    @pytest.mark.asyncio
    async def test_health_check_with_no_model_reports_not_configured(
        self, fresh_module, monkeypatch, mock_metal_available
    ):
        from core.loader.protocol import HealthStatus
        from plugins.mlx_module.core import config as mlx_cfg

        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        with patch.object(mlx_cfg.MLXConfig, "_model_path_from_toml", return_value=""), \
             patch.object(mlx_cfg.MLXConfig, "_model_path_autodiscover", return_value=""):
            await fresh_module.initialize(context={})

        health = await fresh_module.health_check()
        assert health.status != HealthStatus.HEALTHY, (
            f"health_check must not report HEALTHY when no model is "
            f"configured, got: {health.status}."
        )
        assert "not_configured" in (health.message or "").lower() or \
               "no model" in (health.message or "").lower() or \
               "not initialized" in (health.message or "").lower(), (
            f"Expected health message to mention the not-configured state, "
            f"got: {health.message!r}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Bug B, fault 4: lifespan_modules must keep plugin at registry when state
# is not_configured (vs. when initialize() returns False catastrophically)
# ──────────────────────────────────────────────────────────────────────────────


class TestLifespanModulesKeepsNotConfiguredPlugins:
    """When a plugin initialize() returns True (incl. state=not_configured),
    it must stay at app.state.modules. Only catastrophic failures (returns
    False, raises uncaught) should be popped from the registry."""

    @pytest.mark.asyncio
    async def test_not_configured_plugin_stays_at_registry(self, monkeypatch):
        """Integration: MLXModule with no model → initialize returns True
        → plugin remains in plugin_modules dict after
        initialize_plugin_modules() runs."""
        from core.lifespan_modules import initialize_plugin_modules
        from plugins.mlx_module.module import MLXModule
        from plugins.mlx_module.core import config as mlx_cfg

        # Force Metal available so we test the no-model flow
        monkeypatch.setattr(
            mlx_cfg.MLXConfig, "is_metal_available", staticmethod(lambda: True)
        )
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)

        # Build minimal app + server_state mocks
        class _State:
            pass

        app = _State()
        app.state = _State()
        app.state.modules = {"mlx_module": MLXModule()}

        server_state = _State()
        server_state.config = None
        server_state.project_root = "/tmp"

        with patch.object(mlx_cfg.MLXConfig, "_model_path_from_toml", return_value=""), \
             patch.object(mlx_cfg.MLXConfig, "_model_path_autodiscover", return_value=""):
            await initialize_plugin_modules(app, server_state)

        assert "mlx_module" in app.state.modules, (
            "MLXModule was popped from app.state.modules even though "
            "initialize() returned True (not_configured state). "
            "lifespan_modules.py must only pop on explicit False return."
        )
        plugin = app.state.modules["mlx_module"]
        assert getattr(plugin, "_state", None) == "not_configured"
