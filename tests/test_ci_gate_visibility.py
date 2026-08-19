"""
────────────────────────────────────
Server Nexe
Location: tests/test_ci_gate_visibility.py
Description: Anti-regression for the CI gates of .github/workflows/ci.yml (#914).

             A GitHub Actions job stops at its first red step. `Static` runs
             four gates and `Security Audit` three, so a run only ever showed
             the FIRST broken one: on 2026-08-19 bandit hid vulture, and the
             pypdf pip-audit hid both the OSV gate and gitleaks — the two
             hidden ones were red and nobody could see it.

             Same day, a second red with the same shape: gitleaks scans
             <sha>^..<sha>, and the default shallow checkout has no parent
             commit on pull_request, so Security Audit went red on EVERY
             Dependabot PR for a reason unrelated to secrets.

             These tests lock both fixes: every gate after the first keeps
             reporting in the same run, none of them is downgraded to
             advisory, and the audit job checks out full history.

             Pure YAML parse — no network.
────────────────────────────────────
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"

# Gates that must survive an earlier red step in the same job.
LATER_GATES = {
    "static-analysis": ["bandit (gate)", "vulture (gate)"],
    "security-audit": [
        "Run OSV CVE gate for bundled deps (B070)",
        "Run gitleaks (secret scan)",
    ],
}


def _job(job_id: str) -> dict[str, Any]:
    cfg = yaml.safe_load(CI.read_text(encoding="utf-8"))
    jobs = (cfg or {}).get("jobs") or {}
    assert job_id in jobs, f"job {job_id!r} missing from ci.yml"
    return jobs[job_id]


def _step(job_id: str, name: str) -> dict[str, Any]:
    for step in _job(job_id).get("steps") or []:
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} missing from job {job_id!r}")


def test_later_gates_still_run_after_an_earlier_red_step() -> None:
    """#914: one run must show ALL failing gates, not just the first."""
    for job_id, names in LATER_GATES.items():
        for name in names:
            cond = str(_step(job_id, name).get("if", ""))
            assert "cancelled()" in cond and "!" in cond, (
                f"{job_id} / {name!r} has no `if: ${{{{ !cancelled() }}}}`: an "
                "earlier red step hides it again and the run stops showing the "
                "full gate map (#914)."
            )


def test_gates_are_not_downgraded_to_advisory() -> None:
    """The #914 fix must not become `continue-on-error` — that hides the red."""
    for job_id, names in LATER_GATES.items():
        for name in names:
            step = _step(job_id, name)
            assert step.get("continue-on-error") is not True, (
                f"{job_id} / {name!r} is continue-on-error: the gate stops "
                "blocking. Visibility (#914) is about running every gate, not "
                "about making failures pass."
            )


def test_security_audit_checks_out_full_history_for_gitleaks() -> None:
    """gitleaks resolves <sha>^; a shallow clone has no parent on a PR."""
    steps = _job("security-audit").get("steps") or []
    checkout = next(
        (s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")),
        None,
    )
    assert checkout is not None, "security-audit has no checkout step"
    depth = (checkout.get("with") or {}).get("fetch-depth")
    assert depth == 0, (
        "security-audit must check out with fetch-depth: 0. Without it gitleaks "
        "dies on `unknown revision <sha>^..<sha>` and every pull_request run "
        "goes red for a reason that has nothing to do with secrets."
    )
