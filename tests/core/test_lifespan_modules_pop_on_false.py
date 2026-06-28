"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/tests/test_lifespan_modules_pop_on_false.py
Description: Regression tests for P0-2.b fix — loader removes failed plugins from
             app.state.modules when initialize() returns False, AND iterates safely
             over a dict copy to avoid RuntimeError.

             Design choice documented via test 4: exceptions during initialize()
             do NOT pop the module. Those are handled by P0-2.c (/status symmetric
             check) because the _node will stay None on exception and /status will
             report engines_available.{plugin}: false via the _node is None check.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

try:
  from core.lifespan_modules import initialize_plugin_modules
except ImportError:
  pytest.skip("initialize_plugin_modules not available", allow_module_level=True)


def _make_app_with_modules(modules_dict):
  """Helper: build a mock app with app.state.modules = modules_dict."""
  app = MagicMock()
  app.state.modules = modules_dict
  return app


def _make_server_state():
  """Helper: build a minimal server_state mock."""
  server_state = MagicMock()
  server_state.config = {}
  server_state.project_root = "/tmp"
  return server_state


class TestLoaderPopOnFalse:
  """P0-2.b: loader removes failed plugins when initialize() returns False."""

  @pytest.mark.asyncio
  async def test_module_removed_when_initialize_returns_false(self):
    """A plugin whose initialize() returns False must be popped from modules dict."""
    fake_plugin = MagicMock()
    fake_plugin.initialize = AsyncMock(return_value=False)

    modules_dict = {"fake_plugin": fake_plugin}
    app = _make_app_with_modules(modules_dict)

    await initialize_plugin_modules(app, _make_server_state())

    assert "fake_plugin" not in modules_dict, (
      "Plugin that returned False from initialize() should have been popped"
    )

  @pytest.mark.asyncio
  async def test_module_kept_when_initialize_returns_true(self):
    """A plugin whose initialize() returns True must stay in modules dict."""
    fake_plugin = MagicMock()
    fake_plugin.initialize = AsyncMock(return_value=True)

    modules_dict = {"fake_plugin": fake_plugin}
    app = _make_app_with_modules(modules_dict)

    await initialize_plugin_modules(app, _make_server_state())

    assert "fake_plugin" in modules_dict, (
      "Plugin that returned True from initialize() should stay in modules"
    )
    assert modules_dict["fake_plugin"] is fake_plugin

  @pytest.mark.asyncio
  async def test_iteration_safe_with_pop_during_loop(self):
    """Iterating over plugin_modules must be safe even when pop() happens inside the loop.

    Prior to the fix, iterating directly on plugin_modules.items() while calling
    plugin_modules.pop() inside the loop raised RuntimeError:
    dictionary changed size during iteration. The fix uses list(...).
    """
    good_plugin_1 = MagicMock()
    good_plugin_1.initialize = AsyncMock(return_value=True)

    bad_plugin = MagicMock()
    bad_plugin.initialize = AsyncMock(return_value=False)

    good_plugin_2 = MagicMock()
    good_plugin_2.initialize = AsyncMock(return_value=True)

    modules_dict = {
      "good_1": good_plugin_1,
      "bad": bad_plugin,
      "good_2": good_plugin_2,
    }
    app = _make_app_with_modules(modules_dict)

    # Must NOT raise RuntimeError
    await initialize_plugin_modules(app, _make_server_state())

    assert "good_1" in modules_dict
    assert "bad" not in modules_dict, "Failed plugin should be removed"
    assert "good_2" in modules_dict, (
      "Plugins after the failed one must still be processed "
      "(no RuntimeError during iteration)"
    )
    # All three initialize() were called
    good_plugin_1.initialize.assert_awaited_once()
    bad_plugin.initialize.assert_awaited_once()
    good_plugin_2.initialize.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_exception_during_initialize_keeps_module_in_dict(self):
    """Design choice: exceptions during initialize() do NOT pop the module.

    Rationale: exception path is handled by P0-2.c (/status symmetric check).
    When a plugin raises during initialize(), its _node will stay None, and
    /status reports engines_available.{plugin}: false via the `_node is None`
    check added in P0-2.c.

    This test exists to document the contract so a future dev doesn't "fix"
    this apparent gap by also popping on exception — doing so would break
    the symmetric pattern and risk subtle /status inconsistencies.
    """
    exploding_plugin = MagicMock()
    exploding_plugin.initialize = AsyncMock(side_effect=RuntimeError("boom"))

    modules_dict = {"exploding": exploding_plugin}
    app = _make_app_with_modules(modules_dict)

    # Must NOT raise (exception is caught and logged by the loader)
    await initialize_plugin_modules(app, _make_server_state())

    assert "exploding" in modules_dict, (
      "Design choice: plugin that raised from initialize() MUST stay in "
      "modules dict. The failure is observed via /status symmetric check "
      "(P0-2.c), which returns engines_available.{plugin}: false when "
      "_node is None (which happens naturally on initialize exception)."
    )
    exploding_plugin.initialize.assert_awaited_once()


class TestDegradedModulesSignal:
  """MC-122: a startup phase that fails silently must NOT be reported as
  'all operational'. Failed subsystems are appended to server_state.degraded_modules
  and the final banner logs DEGRADED. These tests use a REAL list for
  degraded_modules (the older tests used a MagicMock server_state, whose
  .append() is a no-op and would not catch a regression)."""

  def _state_with_real_degraded_list(self):
    state = MagicMock()
    state.config = {}
    state.project_root = "/tmp"
    state.degraded_modules = []  # real list, not a MagicMock attribute
    return state

  @pytest.mark.asyncio
  async def test_plugin_init_exception_marks_degraded(self):
    """A plugin that raises during initialize() is recorded in degraded_modules.

    Mutation guard: drop the `server_state.degraded_modules.append(module_name)`
    in the except branch of initialize_plugin_modules and this goes RED."""
    exploding = MagicMock()
    exploding.initialize = AsyncMock(side_effect=RuntimeError("boom"))
    app = _make_app_with_modules({"exploding": exploding})
    state = self._state_with_real_degraded_list()

    await initialize_plugin_modules(app, state)

    assert "exploding" in state.degraded_modules, (
      "a plugin that raised during initialize() must be flagged in degraded_modules (MC-122)"
    )

  @pytest.mark.asyncio
  async def test_plugin_init_returns_false_marks_degraded(self):
    """A plugin whose initialize() returns False is recorded in degraded_modules.

    Mutation guard: drop the append() in the 'returned False' branch → RED."""
    bad = MagicMock()
    bad.initialize = AsyncMock(return_value=False)
    app = _make_app_with_modules({"bad": bad})
    state = self._state_with_real_degraded_list()

    await initialize_plugin_modules(app, state)

    assert "bad" in state.degraded_modules, (
      "a plugin whose initialize() returned False must be flagged in degraded_modules (MC-122)"
    )

  @pytest.mark.asyncio
  async def test_healthy_plugin_not_marked_degraded(self):
    """A plugin that initializes cleanly leaves degraded_modules empty."""
    good = MagicMock()
    good.initialize = AsyncMock(return_value=True)
    app = _make_app_with_modules({"good": good})
    state = self._state_with_real_degraded_list()

    await initialize_plugin_modules(app, state)

    assert state.degraded_modules == [], "a healthy plugin must not be flagged"

  def test_banner_warns_degraded_when_modules_failed(self, monkeypatch, caplog):
    """MC-122: the final banner logs DEGRADED (not 'all operational') when a
    subsystem failed.

    Mutation guard: revert the banner back to the unconditional
    'All systems operational' log and this goes RED."""
    import core.lifespan as lifespan
    monkeypatch.setattr(lifespan.server_state, "config", {"core": {"server": {}}}, raising=False)
    monkeypatch.setattr(lifespan.server_state, "crypto_provider", None, raising=False)
    monkeypatch.setattr(lifespan.server_state, "degraded_modules", ["memory", "mlx"], raising=False)

    with caplog.at_level(logging.WARNING):
      lifespan._startup_final_banner()

    messages = [r.getMessage() for r in caplog.records]
    assert any("DEGRADED" in m for m in messages), (
      "banner must warn DEGRADED when degraded_modules is non-empty (MC-122)"
    )
    assert any("memory" in m and "mlx" in m for m in messages), (
      "banner must name the failed subsystems"
    )

  def test_banner_operational_when_nothing_degraded(self, monkeypatch, caplog):
    """With no degraded modules the banner reports 'All systems operational'."""
    import core.lifespan as lifespan
    monkeypatch.setattr(lifespan.server_state, "config", {"core": {"server": {}}}, raising=False)
    monkeypatch.setattr(lifespan.server_state, "crypto_provider", None, raising=False)
    monkeypatch.setattr(lifespan.server_state, "degraded_modules", [], raising=False)

    with caplog.at_level(logging.INFO):
      lifespan._startup_final_banner()

    messages = [r.getMessage() for r in caplog.records]
    assert any("All systems operational" in m for m in messages)
    assert not any("DEGRADED" in m for m in messages)
