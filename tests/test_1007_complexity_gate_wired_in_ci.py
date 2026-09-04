"""
────────────────────────────────────
Server Nexe
Location: tests/test_1007_complexity_gate_wired_in_ci.py
Description: The complexity freeze must have a CI path that does not run
             through the `tests` job (#1007).

             Finding #1007 said `scripts/check_complexity.py` "is called by
             nobody". That premise was already stale: `tests/test_complexity_
             gate.py::TestGateRuns::test_repo_is_within_the_frozen_complexity_
             baseline` runs the script by subprocess and asserts returncode 0,
             and the `tests` job of ci.yml collects it. The wiring was done in
             Python, so a search over .yml/.sh/.md/.toml could not see it.

             What survived the re-check is a smaller, real hole: that pytest
             test was the ONLY CI path. The `tests` job installs the whole of
             requirements.txt first, and — verified 2026-09-04 on this venv —
             a single collection error anywhere under tests/ interrupts the
             run before one test executes (pytest exits 2, "Interrupted: 1
             error during collection"). Either way the freeze silently stopped
             being enforced for reasons that had nothing to do with complexity,
             while its companion gate `check_layering.py` — same contract, same
             stdlib-only design — kept running in a job of its own.

             These tests lock the standalone step: it exists, it lives outside
             the `tests` job and does not depend on it, and the script it runs
             stays importable with nothing but the stdlib (which is what lets
             the step survive a failed `pip install` via `!cancelled()`).

             That the step also keeps reporting after an earlier red step, and
             is not downgraded to advisory, is asserted in
             tests/test_ci_gate_visibility.py (#914), which now carries it.

             Pure YAML/AST parse — no network, no subprocess.
────────────────────────────────────
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"
SCRIPT_REL = "scripts/check_complexity.py"
SCRIPT = REPO / SCRIPT_REL
PYTEST_SIDE_GATE = REPO / "tests" / "test_complexity_gate.py"

# The job whose pytest run was, before #1007, the only CI path to the freeze.
TESTS_JOB = "tests"


def _jobs() -> dict[str, Any]:
    cfg = yaml.safe_load(CI.read_text(encoding="utf-8"))
    jobs = (cfg or {}).get("jobs") or {}
    assert jobs, "ci.yml declares no jobs"
    return jobs


def _jobs_running_the_script() -> set[str]:
    """Job ids with a `run:` step that invokes the gate script directly."""
    found = set()
    for job_id, job in _jobs().items():
        for step in job.get("steps") or []:
            if SCRIPT_REL in str(step.get("run", "")):
                found.add(job_id)
    return found


def _needs_closure(job_id: str) -> set[str]:
    """Every job `job_id` waits for, transitively."""
    jobs = _jobs()
    seen: set[str] = set()
    pending = [job_id]
    while pending:
        current = pending.pop()
        needs = (jobs.get(current) or {}).get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        for dep in needs:
            if dep not in seen:
                seen.add(dep)
                pending.append(dep)
    return seen


def _import_roots(source: str) -> set[str]:
    """Top-level package of every import in the module, at any nesting depth."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` (level > 0) has no module to resolve.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_a_job_other_than_tests_runs_the_complexity_gate() -> None:
    """The freeze must not depend on the unit-test job getting that far."""
    runners = _jobs_running_the_script()
    assert runners, (
        f"no CI job runs `{SCRIPT_REL}`. The freeze is then reachable only "
        "through tests/test_complexity_gate.py inside the `tests` job, which "
        "does not run at all if requirements.txt fails to install or if any "
        "test module under tests/ fails to import (#1007)."
    )
    assert runners - {TESTS_JOB}, (
        f"only the {TESTS_JOB!r} job runs `{SCRIPT_REL}` — that is the hole "
        "#1007 is about, not a fix for it."
    )


def test_the_standalone_gate_job_does_not_depend_on_the_tests_job() -> None:
    """A `needs: tests` would put the hole straight back."""
    standalone = _jobs_running_the_script() - {TESTS_JOB}
    independent = {job for job in standalone if TESTS_JOB not in _needs_closure(job)}
    assert independent, (
        f"every job running `{SCRIPT_REL}` outside {TESTS_JOB!r} waits for it: "
        f"{ {job: sorted(_needs_closure(job)) for job in standalone} }. A job "
        "that never starts because the suite went red enforces nothing."
    )


def test_the_gate_script_is_stdlib_only_so_the_step_needs_no_install() -> None:
    """`check_complexity.py` says it "has to run in CI with nothing but the
    stdlib". The standalone step banks on it: it sits after a `pip install`
    it deliberately does not need, and `!cancelled()` runs it even when that
    install failed. A third-party import here breaks the step in exactly the
    run where the gate matters most."""
    third_party = sorted(_import_roots(SCRIPT.read_text(encoding="utf-8")) - sys.stdlib_module_names)
    assert not third_party, (
        f"{SCRIPT_REL} imports {third_party}, which the standalone CI step "
        "does not install. Either vendor the logic into the stdlib subset or "
        "give the gate its own install step — but then say so here."
    )


def test_the_pytest_side_gate_still_runs_the_same_script() -> None:
    """The CI step is a second door, not a replacement: without the pytest
    test the freeze stops being checked on a developer's machine, which is
    where a growing function is cheap to fix."""
    spec = importlib.util.spec_from_file_location("_cc_gate_test", PYTEST_SIDE_GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SCRIPT == SCRIPT, (
        f"tests/test_complexity_gate.py points at {module.SCRIPT}, the CI step "
        f"at {SCRIPT}. Two gates on two different scripts is one gate less "
        "than it looks."
    )
