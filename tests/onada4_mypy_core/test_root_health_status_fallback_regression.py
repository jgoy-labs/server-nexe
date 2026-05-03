"""Anti-regressió cluster `root.py` health status fallback (Onada 4.1, BUS Dev#1quater MINI).

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

**Correcció Dev#1quater MINI (auditoria externa Codex):** la versió
inicial del stub (Dev#1ter) exposava `get_health()`, però el `# type:
ignore[union-attr]` viu al branch `health_check()` (línia 98). Així el
refactor prohibit (línia 98) NO afectava el test, que sortia per el
branch equivocat. Aquesta versió pinya el branch correcte: stub que
NOMÉS exposa `async health_check()`. Verificat empíricament: el test
falla quan s'aplica el refactor prohibit (return literal `"unknown"`
al path defensiu) i passa al baseline `0306a26`.

El test pina empíricament:

  1. Construeix un stub d'instància amb `async health_check()` que
     retorna un objecte SENSE atribut `status` (replica el cas-extrem
     que dispara el fallback defensiu al branch on viu el ignore).
  2. Executa `_module_health_status(stub)` (async).
  3. Asserta `result == "unhealthy"` literal.

CEC: només firma + import lines + docstring (mòdul, no cos de la funció)
+ format dels tests existents (`test_metrics_endpoint_real.py`,
`test_serverstate_attributes_regression.py`). Cap lectura del cos de
`_module_health_status` més enllà de la línia 98 (necessària per
identificar quin branch hostatja el `# type: ignore[union-attr]`).

Estat esperat: PASS pre-fix (és anti-regressió, no TDD). A HEAD
`0306a26` el path defensiu ja retorna `"unhealthy"` per la captura del
`except Exception`. Si Dev#2 refactoritza el cluster 10 segons la
hipòtesi original (return "unknown"), aquest test salta amb teeth
empírics verificats.
"""

from __future__ import annotations

import asyncio


class _StubInstanceWithStatuslessHealthCheck:
    """Stub: mòdul amb `async health_check()` que retorna objecte SENSE atribut `status`.

    El `# type: ignore[union-attr]` viu a `core/endpoints/root.py:98`,
    DINS del branch `if hasattr(instance, "health_check")` (línies
    95-100). Per pinyar el contracte literal del path defensiu d'aquest
    branch concret, el stub ha de:

      - NO exposar `get_health` (sino entraria al branch anterior,
        línies 89-94, que NO conté la línia que el refactor prohibit
        modificaria).
      - Exposar `async health_check()` que retorna un objecte buit
        (`type("EmptyHealthResult", (), {})()`) sense atribut `status`.

    Mecànica defensiva (a línia 98 actual): `getattr(result, "status",
    "unknown")` retorna el str default `"unknown"`, l'accés posterior
    a `.value` dispara `AttributeError`, capturat pel `except Exception`
    (línia 99) que retorna el literal `"unhealthy"`.
    """

    async def health_check(self) -> object:
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

    stub = _StubInstanceWithStatuslessHealthCheck()
    result = asyncio.run(_module_health_status(stub))

    assert result == "unhealthy", (
        f"_module_health_status(stub_sense_status) = {result!r}, esperat "
        f"literal 'unhealthy'. Director Onada 4.1 va decidir Opció A: el "
        f"path defensiu pinya 'unhealthy'. Si Dev#2 refactoritza "
        f"core/endpoints/root.py:98 (Cluster 10 Auditor#1) i el return "
        f"value defensiu canvia, els monitors/dashboards que esperen "
        f"'unhealthy' per detectar mòduls caiguts trenquen silenciosament."
    )
