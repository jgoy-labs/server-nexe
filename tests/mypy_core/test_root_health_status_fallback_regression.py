"""Anti-regression for `root.py` health status fallback (, refactor).

Covers mypy finding #64 ( full table, and
 § escalated on scenario).

Finding mechanics (extracted exclusively from auditor — CEC on the
function body):

    `core/endpoints/root.py:98` — `return getattr(result, "status", "unknown").value`.
    When `result` does not expose the `status` attribute, `getattr` returns the
    default str `"unknown"`. This str has no `.value` attribute → `AttributeError`
    caught by `except Exception` (line 99) → the function returns the literal
    `"unhealthy"`.

design decided **Option A** on the  escalated by
dev:

    "The defensive path returns the literal 'unhealthy', NOT 'unknown'."

Consequence: blocks the refactor proposed by auditor for scenario
(`status_obj = getattr(result, "status", None); return status_obj.value
if status_obj else "unknown"`), which would observably change the defensive
return value from `"unhealthy"` to `"unknown"` and would be a silent regression
for monitors/dashboards that map `"unhealthy"` to "module down".

**dev MINI correction (security review):** the initial
stub version (dev) exposed `get_health()`, but the `# type:
ignore[union-attr]` lives in the `health_check()` branch (line 98). So the
forbidden refactor (line 98) did NOT affect the test, which exited via the
wrong branch. This version pins the correct branch: a stub that
ONLY exposes `async health_check()`. Empirically verified: the test
fails when the forbidden refactor is applied (return literal `"unknown"`
on the defensive path) and passes at baseline `0306a26`.

The test empirically pins:

  1. Builds a stub instance with `async health_check()` that returns
     an object WITHOUT a `status` attribute (replicates the edge case
     that triggers the defensive fallback in the branch where the ignore lives).
  2. Executes `_module_health_status(stub)` (async).
  3. Asserts `result == "unhealthy"` literal.

CEC: signature + import lines + docstring only (module, not function body)
+ format of existing tests (`test_metrics_endpoint_real.py`,
`test_serverstate_attributes_regression.py`). No reading of the
`_module_health_status` body beyond line 98 (needed to identify which branch
hosts the `# type: ignore[union-attr]`).

Expected state: PASS pre-fix (this is anti-regression, not TDD). At HEAD
`0306a26` the defensive path already returns `"unhealthy"` via the
`except Exception` catch. If dev refactors scenario per the original
hypothesis (return "unknown"), this test fails with verified empirical teeth.
"""

from __future__ import annotations

import asyncio


class _StubInstanceWithStatuslessHealthCheck:
    """Stub: module with `async health_check()` that returns an object WITHOUT a `status` attribute.

    The `# type: ignore[union-attr]` lives at `core/endpoints/root.py:98`,
    INSIDE the branch `if hasattr(instance, "health_check")` (lines
    95-100). To pin the literal contract of the defensive path in this
    specific branch, the stub must:

      - NOT expose `get_health` (otherwise it would enter the previous branch,
        lines 89-94, which does NOT contain the line the forbidden refactor
        would modify).
      - Expose `async health_check()` that returns an empty object
        (`type("EmptyHealthResult", (), {})()`) without a `status` attribute.

    Defensive mechanics (at current line 98): `getattr(result, "status",
    "unknown")` returns the default str `"unknown"`, the subsequent access
    to `.value` triggers `AttributeError`, caught by `except Exception`
    (line 99) which returns the literal `"unhealthy"`.
    """

    async def health_check(self) -> object:
        return type("EmptyHealthResult", (), {})()


def test_module_health_status_defensive_path_returns_literal_unhealthy() -> None:
    """Pins the literal 'unhealthy' contract on the defensive return (finding #64).

    Director chose Option A: blocks the scenario refactor
    (auditor) that would change the literal to 'unknown'. If dev modifies
    `core/endpoints/root.py:98` so that the defensive path returns `"unknown"`,
    this test fails — the regression should be intentional and validated
    by the director, not silent.
    """
    from core.endpoints.root import _module_health_status

    stub = _StubInstanceWithStatuslessHealthCheck()
    result = asyncio.run(_module_health_status(stub))

    assert result == "unhealthy", (
        f"_module_health_status(stub_without_status) = {result!r}, expected "
        f"literal 'unhealthy'. Director chose Option A: the "
        f"defensive path pins 'unhealthy'. If dev refactors "
        f"core/endpoints/root.py:98 (scenario auditor) and the defensive "
        f"return value changes, monitors/dashboards that expect "
        f"'unhealthy' to detect downed modules will break silently."
    )
