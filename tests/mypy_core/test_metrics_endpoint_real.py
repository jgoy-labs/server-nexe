"""
mypy core — real finding TDD test (dev, pilot run).

REAL bug classified by auditor:

  `core/metrics/endpoint.py:125` — `_update_module_health()` iterates
  `mm.list_modules()` with `for module_name, module_info in modules.items():`.
  The real signature (`personality/module_manager/module_manager.py:238`)
  returns `List[ModuleInfo]`, not a dict. The `.items()` call fails with
  `AttributeError`, caught by `except Exception` (lines 136-137) at
  `logger.debug("module_health_update_skipped", extra={"reason": ...})`.
  Consequence: `set_module_health(...)` is never called for any module
  and `module_health` metrics remain permanently at the initial value
  without any alarm.

This test (CEC on the function body — dev only reads signature + auditor):

  1. Mocks `ModuleManager.list_modules()` to return a **list**
     (as in production), not a dict (as the 4 pre-existing tests
     at `core/metrics/tests/test_endpoint.py:124-186` do — those tests
     are theatre: they pass because the mock returns a dict, contradicting
     the real signature).
  2. Patches `core.metrics.endpoint.logger` to capture `debug` calls.
  3. Executes `_update_module_health()`.
  4. Fails if a call to
     `logger.debug("module_health_update_skipped", ...)` was recorded —
     indicating that the function silently swallowed an exception (the
     `AttributeError` from bug #38).

Expected states:

  - **HEAD pre-surgery (this commit):** `xfailed` (strict). The code calls
    `.items()` on a list → `AttributeError` → `logger.debug("module_health_update_skipped")`
    → the assert fails → xfail is satisfied.
  - **HEAD post-surgery (dev):** when dev fixes the iteration to traverse
    `List[ModuleInfo]` correctly, `logger.debug("module_health_update_skipped")`
    will stop being called → the test passes → `XPASS` will trip the `xfail strict`
    → dev must remove the `@pytest.mark.xfail` to make it cleanly `passing`.

Empirical pytest evidence pre-fix (HEAD `79de490`, session 2):

    tests/onada4_mypy_core/test_metrics_endpoint_real.py::test_update_module_health_does_not_swallow_attributeerror_on_list_modules XFAIL
    AssertionError: _update_module_health silently caught an exception
    during iteration of list_modules() (which returns List[ModuleInfo], not dict).
    Calls to logger.debug('module_health_update_skipped'): [...]
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


def test_update_module_health_does_not_swallow_attributeerror_on_list_modules():
    """Pin-test contract: list_modules() returns a list and iteration must not
    silently swallow AttributeError. See module docstring."""
    from core.metrics.endpoint import _update_module_health

    mock_module_info = MagicMock()
    mock_module_info.name = "module_signature_returns_list_not_dict"

    mock_mm = MagicMock()
    mock_mm.list_modules.return_value = [mock_module_info]

    with patch(
        "personality.module_manager.module_manager.ModuleManager",
        return_value=mock_mm,
    ), patch("core.metrics.endpoint.logger") as mock_logger:
        asyncio.run(_update_module_health())

    skip_calls = [
        call
        for call in mock_logger.debug.call_args_list
        if call.args and "module_health_update_skipped" in str(call.args[0])
    ]
    assert not skip_calls, (
        "_update_module_health silently caught an exception "
        "during iteration of list_modules() (which returns List[ModuleInfo], "
        "not dict). Calls to logger.debug('module_health_update_skipped'): "
        f"{[repr(c) for c in skip_calls]}"
    )
