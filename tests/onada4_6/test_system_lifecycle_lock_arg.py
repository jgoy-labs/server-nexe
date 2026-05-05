"""
Onada 4.6a B1 — TDD cec
Bug: system_lifecycle.py passa arg `lock` obsolet a ModuleLifecycleManager.
"""
import inspect
import pytest
from unittest.mock import MagicMock, AsyncMock

from personality.module_manager.module_lifecycle import ModuleLifecycleManager
from personality.module_manager.system_lifecycle import SystemLifecycleManager


@pytest.mark.asyncio
async def test_start_system_typeerror_lock_arg_obsolet():
    """REAL ModuleLifecycleManager. start_system() crida load_module(name, lock) però
    la signatura és load_module(name) → TypeError → start_system retorna False.
    Quan el fix s'aplica: load_module(name) → retorna False (mòdul no al dict) →
    start_system retorna True → XPASSED (strict=True → CI falla, confirma fix detectat)."""
    real_lifecycle = ModuleLifecycleManager(
        modules={},
        loader=MagicMock(),
        registry=MagicMock(),
        events=MagicMock(),
        metrics=MagicMock(),
    )

    mod_info = MagicMock()
    mod_info.name = "test_mod"
    mod_info.auto_start = True
    mod_info.enabled = True

    mgr = SystemLifecycleManager(
        modules={},
        module_lifecycle=real_lifecycle,
        discovery_func=AsyncMock(return_value=["test_mod"]),
        list_modules_func=MagicMock(return_value=[mod_info]),
    )

    result = await mgr.start_system()
    # Bug present: TypeError → captat → False. Fix aplicat: cap error → True.
    assert result is True


def test_module_lifecycle_signature_no_lock_arg():
    """Pin estàtic: load_module, start_module, stop_module només accepten `module_name`.
    Si reapareix arg extra, test falla."""
    for method_name in ("load_module", "start_module", "stop_module"):
        sig = inspect.signature(getattr(ModuleLifecycleManager, method_name))
        params = list(sig.parameters.keys())
        assert params == ["self", "module_name"], (
            f"ModuleLifecycleManager.{method_name} té paràmetres inesperats: {params}"
        )
