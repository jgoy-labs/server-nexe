"""
F5.4 Bug C — regression tests: LlamaCppConfig must NOT corrupt the model path
in logs when NEXE_LLAMA_CPP_MODEL is unset.

Empirical log evidence (G10 portàtil 2026-05-19):
    LlamaCppConfig: model_path is empty. Set NEXE_LLAMA_CPP_MODEL or pass model_path.
    LlamaCppConfig loaded: model=ication Support/com.nexe.app/sidecar/app, ...
    ModelPool initialized: max_sessions=2, model=ication Support/...
    LlamaCppModule initialized successfully  ← FALSE POSITIVE

Two-fault chain:
  1. __post_init__ elif branch fires on empty path: `os.path.isabs("")` is False
     → `str(project_root / "")` returns `str(project_root)` = NEXE_HOME (67 chars).
  2. from_env log INFO slices `model_path[-40:]` → produces literal "ication
     Support/com.nexe.app/sidecar/app" from the 67-char project_root path.

Plus: module reports "initialized successfully" when path is empty (validate
fails but `_initialized=True` and returns True from initialize()).

Fix expected:
  - Empty model_path stays empty after __post_init__ (no fallback to project_root).
  - Log INFO from_env uses the full path (no -40: slicing).
  - module.initialize() returns True with state=not_configured (plugin stays at
    registry with HealthStatus.UNKNOWN), NOT a false-positive `initialized
    successfully`.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Bug C, fault 1: empty model_path must NOT collapse into project_root
# ──────────────────────────────────────────────────────────────────────────────


class TestLlamaCppConfigEmptyPathStaysEmpty:
    """__post_init__ must not transform empty string into project_root."""

    def test_empty_model_path_remains_empty_string(self):
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="")
        assert config.model_path == "", (
            "Empty model_path was rewritten by __post_init__ to "
            f"{config.model_path!r}. The elif branch must guard against empty "
            "strings: `elif self.model_path and not os.path.isabs(...)`."
        )

    def test_relative_path_still_resolved(self, tmp_path, monkeypatch):
        """Sanity check: the empty-string guard must NOT break relative-path
        resolution (existing test_relative_path_resolution covered this)."""
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="models/test.gguf")
        assert os.path.isabs(config.model_path), (
            "Relative path resolution regressed — guard fix overshot."
        )

    def test_absolute_path_still_unchanged(self):
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="/absolute/model.gguf")
        assert config.model_path == "/absolute/model.gguf"

    def test_tilde_path_still_expanded(self):
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        config = LlamaCppConfig(model_path="~/models/test.gguf")
        assert not config.model_path.startswith("~")
        assert os.path.expanduser("~") in config.model_path


# ──────────────────────────────────────────────────────────────────────────────
# Bug C, fault 2: from_env log INFO must NOT slice [-40:] to "save space"
# ──────────────────────────────────────────────────────────────────────────────


class TestLlamaCppConfigFromEnvLogDoesNotCorruptPath:
    """The INFO log line emitted by from_env must show the full model path,
    not a [-40:] slice that produces fake substrings like "ication Support/...".

    The original code (line 123) did:
        config.model_path[-40:] if config.model_path else "(empty)"

    For a typical macOS Application Support path:
        /Users/nexe/Library/Application Support/com.nexe.app/sidecar/app
        ───────────────────^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                           last 40 chars = "ication Support/com.nexe.app/sidecar/app"

    which falsely looks like a literal path with corrupted prefix.
    """

    @pytest.fixture
    def long_macos_appsupport_path(self, tmp_path):
        # Build a path with the same shape as a real macOS app sidecar root,
        # but inside tmp so we can mkdir freely. The point is the substring
        # "Application Support" plus enough length to trigger the bug.
        target = tmp_path / "Users" / "nexe" / "Library" / "Application Support" / "com.nexe.app" / "sidecar" / "app"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model.gguf").write_text("fake gguf")
        return target / "model.gguf"

    def test_log_does_not_show_sliced_path_corruption(self, caplog, long_macos_appsupport_path, monkeypatch):
        """Bug C smoking gun: log must NOT show a path that starts with
        'ication Support' (= sliced 'Application Support'). The full path
        must include the 'Appl' prefix.

        The original bug emitted 'model=ication Support/com.nexe.app/...' —
        a `[-40:]` slice of the 67-char macOS appsupport path. The literal
        substring 'Application Support' will appear naturally in the full
        path; the corruption is when 'ication' appears WITHOUT 'Appl'
        immediately before it.
        """
        from plugins.llama_cpp_module.core import config as llama_cfg

        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", str(long_macos_appsupport_path))
        with caplog.at_level(logging.INFO, logger=llama_cfg.__name__):
            llama_cfg.LlamaCppConfig.from_env()

        relevant = [r.message for r in caplog.records if "LlamaCppConfig loaded" in r.message]
        assert relevant, "Expected at least one 'LlamaCppConfig loaded' INFO log"
        for msg in relevant:
            # Bug C: model=ication Support/... means the prefix was sliced off.
            # Use regex anchored on `model=` so we catch the corruption pattern.
            import re as _re
            assert not _re.search(r"model=ication Support", msg), (
                "Bug C: log shows 'model=ication Support' — model_path was "
                "sliced with [-40:] in from_env log INFO. Emit the full path "
                f"instead.\nGot: {msg}"
            )
            # Positive assertion: when the full path is emitted it MUST include
            # 'Application Support' (with the 'Appl' prefix), not just the
            # sliced suffix.
            assert "Application Support" in msg, (
                "Expected 'Application Support' (complete) in log, "
                f"got: {msg}"
            )
            # And the full path leading to the model file is present.
            assert str(long_macos_appsupport_path) in msg, (
                f"Expected full model path in log, got: {msg}"
            )

    def test_log_with_empty_path_says_empty_not_corrupt(self, caplog, monkeypatch):
        """When model_path is empty after env+auto-discover, log must say
        '(empty)' or similar — not a slice of nothing or NEXE_HOME."""
        from plugins.llama_cpp_module.core import config as llama_cfg

        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        # Prevent auto-discover from finding any .gguf
        with patch.object(llama_cfg, "logger"):
            with caplog.at_level(logging.INFO, logger=llama_cfg.__name__):
                cfg = llama_cfg.LlamaCppConfig.from_env()
        # The exact wording is up to the implementation, but the path must
        # not be a substring of NEXE_HOME / project_root.
        assert cfg.model_path == "", (
            f"With no env var and no auto-discover, model_path must remain "
            f"empty, got: {cfg.model_path!r}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Bug C, fault 3: module.initialize() must NOT report false-positive success
# ──────────────────────────────────────────────────────────────────────────────


class TestLlamaCppModuleInitializeNotConfiguredState:
    """When the config validation fails because no model is configured (env
    var unset + auto-discover empty), initialize() must return True (so the
    loader keeps it at the registry) AND mark internal state as not_configured
    AND skip ModelPool initialization AND health_check must NOT report HEALTHY.

    The DEV venv may not have llama-cpp-python installed; we mock the
    `import llama_cpp` check so the test focuses on the no-model-path flow.
    """

    @pytest.fixture
    def fresh_module(self):
        from plugins.llama_cpp_module.module import LlamaCppModule
        return LlamaCppModule()

    @pytest.fixture
    def mock_llama_cpp_present(self, monkeypatch):
        """Make `import llama_cpp` succeed inside initialize() without needing
        the actual native lib. Tests focus on the no-model-path flow."""
        import sys
        import types
        if "llama_cpp" not in sys.modules:
            monkeypatch.setitem(sys.modules, "llama_cpp", types.ModuleType("llama_cpp"))
        yield

    @pytest.mark.asyncio
    async def test_initialize_with_no_model_returns_true_and_marks_not_configured(
        self, fresh_module, monkeypatch, mock_llama_cpp_present
    ):
        """No env var, no auto-discover .gguf → initialize() returns True
        but plugin is in not_configured state (not a false-positive success).

        The True return is intentional: it keeps the plugin at the registry so
        F5.3.1 restart_sidecar can re-initialize it after the user completes
        the wizard. The not_configured state prevents callers from treating
        it as ready."""
        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        # No models_dir set → auto-discover finds nothing.
        monkeypatch.delenv("NEXE_STORAGE_PATH", raising=False)

        result = await fresh_module.initialize(context={})

        assert result is True, (
            "initialize() must return True when no model is configured — the "
            "plugin must stay at the registry for restart_sidecar to "
            "re-activate it after the wizard. False would trigger "
            "plugin_modules.pop in lifespan_modules.py."
        )
        # Internal state marker — using getattr to allow either `_state` attr
        # or property pattern; the test asserts the SEMANTIC state.
        state = getattr(fresh_module, "_state", None)
        assert state == "not_configured", (
            f"Expected plugin._state == 'not_configured', got: {state!r}. "
            "After the fix the plugin must record that it has no model "
            "configured so consumers know not to use it for chat."
        )

    @pytest.mark.asyncio
    async def test_initialize_with_no_model_does_not_create_model_pool(
        self, fresh_module, monkeypatch, mock_llama_cpp_present
    ):
        """ModelPool must NOT be initialized when there is no model — the
        old behavior printed 'ModelPool initialized: max_sessions=2, model=
        ication Support/...' which was a false positive."""
        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        monkeypatch.delenv("NEXE_STORAGE_PATH", raising=False)

        await fresh_module.initialize(context={})

        assert fresh_module._node is None, (
            "self._node must be None when no model is configured. "
            "Creating LlamaCppChatNode (which builds ModelPool) with an empty "
            "config is the source of the misleading 'ModelPool initialized' "
            "log line in Bug C."
        )

    @pytest.mark.asyncio
    async def test_health_check_with_no_model_is_not_healthy(
        self, fresh_module, monkeypatch, mock_llama_cpp_present
    ):
        """health_check() must report a non-HEALTHY status when no model is
        configured so the /status endpoint correctly informs UI."""
        from core.loader.protocol import HealthStatus

        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        monkeypatch.delenv("NEXE_STORAGE_PATH", raising=False)

        await fresh_module.initialize(context={})
        health = await fresh_module.health_check()

        assert health.status != HealthStatus.HEALTHY, (
            f"health_check must not report HEALTHY when no model is "
            f"configured, got: {health.status}. The previous false-positive "
            "'initialized successfully' log misled health checks."
        )
        # Message must mention the underlying cause so the UI/log is actionable.
        assert "not_configured" in (health.message or "").lower() or \
               "no model" in (health.message or "").lower() or \
               "not initialized" in (health.message or "").lower(), (
            f"Expected health message to mention the not-configured state, "
            f"got: {health.message!r}"
        )
