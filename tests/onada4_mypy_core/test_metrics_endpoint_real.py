"""
Onada 4.1 mypy core — REAL #38 TDD test (Dev#1, sessió 2 BUS pilot).

Bug REAL classificat per Auditor#1 (`01-classificacio.md` §Bugs REAL detallat):

  `core/metrics/endpoint.py:125` — `_update_module_health()` itera
  `mm.list_modules()` amb `for module_name, module_info in modules.items():`.
  La signatura real (`personality/module_manager/module_manager.py:238`)
  retorna `List[ModuleInfo]`, no dict. La crida `.items()` falla amb
  `AttributeError`, capturada pel `except Exception` (línies 136-137) a
  `logger.debug("module_health_update_skipped", extra={"reason": ...})`.
  Conseqüència: `set_module_health(...)` no s'invoca mai per cap mòdul
  i les mètriques `module_health` queden permanentment al valor inicial
  sense alarma.

Aquest test (CEC al cos de la funció — Dev#1 només llegeix firma + Auditor#1):

  1. Mocka `ModuleManager.list_modules()` per retornar una **llista**
     (com producció), no un dict (com fan els 4 tests pre-existents
     a `core/metrics/tests/test_endpoint.py:124-186` — aquests tests
     són teatre: passen perquè el mock retorna dict, contradient la
     signatura real).
  2. Patxa `core.metrics.endpoint.logger` per capturar crides a `debug`.
  3. Executa `_update_module_health()`.
  4. Falla si s'ha registrat una crida a
     `logger.debug("module_health_update_skipped", ...)` — que indica
     que la funció ha empassat silenciosament una excepció (l'`AttributeError`
     del bug #38).

Estats esperats:

  - **HEAD pre-cirurgia (aquest commit):** `xfailed` (strict). El codi crida
    `.items()` sobre llista → `AttributeError` → `logger.debug("module_health_update_skipped")`
    → l'assert falla → xfail compleix.
  - **HEAD post-cirurgia (Dev#2):** quan Dev#2 arregli la iteració per recórrer
    `List[ModuleInfo]` correctament, el `logger.debug("module_health_update_skipped")`
    deixarà de cridar-se → el test passarà → `XPASS` farà saltar l'`xfail strict`
    → Dev#2 ha de retirar el `@pytest.mark.xfail` per fer-lo `passing` net.

Evidència empírica pytest pre-fix (HEAD `79de490`, Onada 4.1 sessió 2):

    tests/onada4_mypy_core/test_metrics_endpoint_real.py::test_update_module_health_does_not_swallow_attributeerror_on_list_modules XFAIL
    AssertionError: _update_module_health silenciosament va capturar una excepció
    durant la iteració de list_modules() (que retorna List[ModuleInfo], no dict).
    Crides a logger.debug('module_health_update_skipped'): [...]
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


def test_update_module_health_does_not_swallow_attributeerror_on_list_modules():
    """Pin-test contracte: list_modules() retorna llista i la iteració no
    pot empassar AttributeError silenciosament. Veure docstring del mòdul."""
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
        "_update_module_health silenciosament va capturar una excepció "
        "durant la iteració de list_modules() (que retorna List[ModuleInfo], "
        "no dict). Crides a logger.debug('module_health_update_skipped'): "
        f"{[repr(c) for c in skip_calls]}"
    )
