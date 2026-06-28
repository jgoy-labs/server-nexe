"""T31 — Real tests for core/lifespan_auto_clean.py.

The original test-theatre had:
    assert callable(_startup_auto_clean)
which passes for any importable function and never exercises any logic.

Bug taped: all logic in _startup_auto_clean (NEXE_AUTO_CLEAN_ENABLED gating at
lines 20-25, dry_run flag at 34-36, and the actual run_auto_clean call at 37-40)
was entirely unprotected — a regression that broke the gating would pass unseen.

Mutation targets:
- Remove `if not auto_clean_enabled: return` (lines 24-25)
  → test_gating_disabled_does_not_call_run_auto_clean turns RED.
- Change dry_run default from 'true' to 'false' (line 35)
  → test_enabled_defaults_to_dry_run turns RED.
"""

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def _make_server_state(tmp_path: Path):
    """Minimal server_state double with i18n=None and a real project_root."""
    state = MagicMock()
    state.i18n = None
    state.project_root = tmp_path
    return state


def _make_translate():
    """Passthrough _translate stub that returns the default string."""
    def _translate(i18n, key, default, **kwargs):
        return default.format(**kwargs) if kwargs else default
    return _translate


def _inject_fake_auto_clean(mock_run):
    """Return a context manager that injects a fake personality.auto_clean module."""
    parent = types.ModuleType("personality.auto_clean")
    core = types.ModuleType("personality.auto_clean.core")
    leaf = types.ModuleType("personality.auto_clean.core.auto_clean")
    leaf.run_auto_clean = mock_run
    return patch.dict(sys.modules, {
        "personality.auto_clean": parent,
        "personality.auto_clean.core": core,
        "personality.auto_clean.core.auto_clean": leaf,
    })


class TestLifespanAutoClean:

    def test_gating_disabled_does_not_call_run_auto_clean(self, tmp_path):
        """T31a: when NEXE_AUTO_CLEAN_ENABLED is absent/false, _startup_auto_clean
        must return early without ever calling run_auto_clean.

        Mutation target: remove `if not auto_clean_enabled: return` (lines 24-25)
        in lifespan_auto_clean.py → mock_run gets called despite being disabled
        → assert_not_called() fails → RED.
        """
        from core.lifespan_auto_clean import _startup_auto_clean

        mock_run = AsyncMock(return_value={"files_cleaned": 0, "would_clean": 0})

        env_overrides = {
            "NEXE_AUTO_CLEAN_ENABLED": "false",
            "AUTO_CLEAN_ENABLED": "false",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            with _inject_fake_auto_clean(mock_run):
                asyncio.run(_startup_auto_clean(
                    _make_server_state(tmp_path),
                    _make_translate(),
                ))

        mock_run.assert_not_called()

    def test_enabled_calls_run_auto_clean(self, tmp_path):
        """T31b: when NEXE_AUTO_CLEAN_ENABLED=true, _startup_auto_clean must
        call run_auto_clean with core_root=server_state.project_root.

        Mutation target: remove `if not auto_clean_enabled: return` has no effect
        here, but breaking the call itself (e.g. removing `await run_auto_clean(...)`)
        → assert_called_once fails → RED.
        """
        from core.lifespan_auto_clean import _startup_auto_clean

        mock_run = AsyncMock(return_value={"files_cleaned": 0, "would_clean": 0})

        env_overrides = {
            "NEXE_AUTO_CLEAN_ENABLED": "true",
            "AUTO_CLEAN_ENABLED": "true",
            "NEXE_AUTO_CLEAN_DRY_RUN": "false",
            "AUTO_CLEAN_DRY_RUN": "false",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            with _inject_fake_auto_clean(mock_run):
                asyncio.run(_startup_auto_clean(
                    _make_server_state(tmp_path),
                    _make_translate(),
                ))

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("core_root") == tmp_path, (
            f"run_auto_clean must receive core_root=project_root; got {call_kwargs!r}"
        )

    def test_enabled_defaults_to_dry_run(self, tmp_path):
        """T31c: when NEXE_AUTO_CLEAN_DRY_RUN is not set (default), dry_run must
        be True (conservative default: never delete without explicit opt-in).

        Mutation target: change default in lifespan_auto_clean.py line 35 from
        'true' to 'false' → run_auto_clean receives dry_run=False → assert fails → RED.
        """
        from core.lifespan_auto_clean import _startup_auto_clean

        mock_run = AsyncMock(return_value={"files_cleaned": 0, "would_clean": 0})

        # Enable auto-clean but leave dry-run env vars UNSET (default behaviour).
        env_base = {
            "NEXE_AUTO_CLEAN_ENABLED": "true",
            "AUTO_CLEAN_ENABLED": "true",
        }
        # Remove dry-run vars so the default kicks in.
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("NEXE_AUTO_CLEAN_DRY_RUN", "AUTO_CLEAN_DRY_RUN")}
        env_clean.update(env_base)

        with patch.dict(os.environ, env_clean, clear=True):
            with _inject_fake_auto_clean(mock_run):
                asyncio.run(_startup_auto_clean(
                    _make_server_state(tmp_path),
                    _make_translate(),
                ))

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("dry_run") is True, (
            "Default dry_run must be True when NEXE_AUTO_CLEAN_DRY_RUN is unset; "
            f"got dry_run={call_kwargs.get('dry_run')!r}"
        )
