"""
Onada 4.6a B1 — Blind TDD
Bug: system_lifecycle.py passes obsolete `lock` arg to ModuleLifecycleManager.
"""
import inspect
import pytest
from unittest.mock import MagicMock, AsyncMock

from personality.module_manager.module_lifecycle import ModuleLifecycleManager
from personality.module_manager.system_lifecycle import SystemLifecycleManager
from personality.module_manager.types import LifecycleConfig, SystemLifecycleConfig


@pytest.mark.asyncio
async def test_start_system_typeerror_lock_arg_obsolet():
    """REAL ModuleLifecycleManager. start_system() calls load_module(name, lock) but
    the signature is load_module(name) → TypeError → start_system returns False.
    When the fix is applied: load_module(name) → returns False (module not in dict) →
    start_system returns True → XPASSED (strict=True → CI fails, confirms fix detected)."""
    real_lifecycle = ModuleLifecycleManager(LifecycleConfig(
        modules={},
        loader=MagicMock(),
        registry=MagicMock(),
        events=MagicMock(),
        metrics=MagicMock(),
    ))

    mod_info = MagicMock()
    mod_info.name = "test_mod"
    mod_info.auto_start = True
    mod_info.enabled = True

    mgr = SystemLifecycleManager(SystemLifecycleConfig(
        modules={},
        module_lifecycle=real_lifecycle,
        discovery_func=AsyncMock(return_value=["test_mod"]),
        list_modules_func=MagicMock(return_value=[mod_info]),
    ))

    result = await mgr.start_system()
    # Bug present: TypeError → caught → False. Fix applied: no error → True.
    assert result is True


def test_module_lifecycle_signature_no_lock_arg():
    """Static pin: load_module, start_module, stop_module only accept `module_name`.
    If an extra arg reappears, test fails."""
    for method_name in ("load_module", "start_module", "stop_module"):
        sig = inspect.signature(getattr(ModuleLifecycleManager, method_name))
        params = list(sig.parameters.keys())
        assert params == ["self", "module_name"], (
            f"ModuleLifecycleManager.{method_name} has unexpected parameters: {params}"
        )
