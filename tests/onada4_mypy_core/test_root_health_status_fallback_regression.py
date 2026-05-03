"""Anti-regressió cluster `root.py` health status fallback (Onada 4.1, BUS Dev#1ter MINI).

Cobreix el finding mypy #64 (`01-classificacio.md` taula completa, i
`02-tests-bis.md` §DUBTE escalat sobre Cluster 10).

Mecànica del finding (extreta exclusivament d'Auditor#1 — CEC al cos de
la funció):

    `core/endpoints/root.py:98` — `return getattr(result, "status", "unknown").value`.
    Quan `result` no exposa l'atribut `status`, `getattr` retorna el str
    default `"unknown"`. Aquest str no té atribut `.value` → `AttributeError`
    capturat pel `except Exception` (línia 99) → la funció retorna el literal
    `"unhealthy"`.

Director Onada 4.1 ha decidit **Opció A** sobre el DUBTE escalat per
Dev#1bis (`02-tests-bis.md` §DUBTE escalats al director, Cluster 10):

    "El path defensiu retorna literal 'unhealthy', NO 'unknown'."

Conseqüència: bloca el refactor proposat per Auditor#1 al Cluster 10
(`status_obj = getattr(result, "status", None); return status_obj.value
if status_obj else "unknown"`), que canviaria observablement el return
value defensiu de `"unhealthy"` a `"unknown"` i seria una regressió
silenciosa per als monitors/dashboards que mapegen `"unhealthy"` a
"mòdul caigut".

El test pina empíricament:

  1. Construeix un stub d'instància amb `get_health()` que retorna un
     objecte SENSE atribut `status` (replica el cas-extrem que dispara
     el fallback defensiu).
  2. Executa `_module_health_status(stub)` (async).
  3. Asserta `result == "unhealthy"` literal.

CEC: només firma + import lines + docstring (mòdul, no cos de la funció)
+ format dels tests existents (`test_metrics_endpoint_real.py`,
`test_serverstate_attributes_regression.py`). Cap lectura del cos de
`_module_health_status`.

Estat esperat: PASS pre-fix (és anti-regressió, no TDD). A HEAD
`cf97ce9` el path defensiu ja retorna `"unhealthy"` per la captura del
`except Exception`. Si Dev#2 refactoritza el cluster 10 segons la
hipòtesi original (return "unknown"), aquest test salta.
"""

from __future__ import annotations

import asyncio


class _StubInstanceWithStatuslessHealth:
    """Stub: mòdul amb `get_health()` sync que retorna objecte SENSE atribut `status`.

    `_module_health_status` (firma `async def _module_health_status(instance) -> str:`
    a `core/endpoints/root.py:88`) consulta `result.status` via
    `getattr(result, "status", "unknown")` (línia 98 segons Auditor#1).
    Aquest stub retorna un objecte buit (`type("EmptyHealthResult", (), {})()`)
    que no exposa l'atribut `status` — així el `getattr` cau al default str
    `"unknown"`, l'accés posterior a `.value` dispara `AttributeError`, i
    el `except Exception` (línia 99) retorna el literal `"unhealthy"`.
    """

    def get_health(self) -> object:
        return type("EmptyHealthResult", (), {})()


def test_module_health_status_defensive_path_returns_literal_unhealthy() -> None:
    """Pina contracte literal 'unhealthy' al return defensiu (finding #64).

    Director Onada 4.1 va decidir Opció A: bloca refactor Cluster 10
    (Auditor#1) que canviaria el literal a 'unknown'. Si Dev#2 modifica
    `core/endpoints/root.py:98` perquè el path defensiu retorni `"unknown"`,
    aquest test salta — la regressió hauria de ser intencional i validada
    pel director, no silenciosa.
    """
    from core.endpoints.root import _module_health_status

    stub = _StubInstanceWithStatuslessHealth()
    result = asyncio.run(_module_health_status(stub))

    assert result == "unhealthy", (
        f"_module_health_status(stub_sense_status) = {result!r}, esperat "
        f"literal 'unhealthy'. Director Onada 4.1 va decidir Opció A: el "
        f"path defensiu pinya 'unhealthy'. Si Dev#2 refactoritza "
        f"core/endpoints/root.py:98 (Cluster 10 Auditor#1) i el return "
        f"value defensiu canvia, els monitors/dashboards que esperen "
        f"'unhealthy' per detectar mòduls caiguts trenquen silenciosament."
    )
