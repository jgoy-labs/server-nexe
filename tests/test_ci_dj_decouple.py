"""D-J / #867 — CI must not skip the suite when Security Audit is red.

The 04/08 push (4ff1580) had Security Audit failure and Unit Tests +
Layering skipped, because those jobs `needs: security-audit` and the
audit pip-audited requirements-macos.txt on ubuntu (pyobjc wants
/usr/bin/sw_vers).

These tests read the live workflow. Re-adding `needs: security-audit`
to tests/layering/precompute-check, or pip-auditing the macos file
again, turns them RED.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _job_body(job_id: str) -> str:
    """Text of one top-level job, up to the next job at the same indent."""
    pat = re.compile(rf"^  {re.escape(job_id)}:\s*$", re.M)
    m = pat.search(CI)
    assert m, f"job {job_id!r} missing from ci.yml"
    start = m.end()
    nxt = re.search(r"^  [A-Za-z0-9_-]+:\s*$", CI[start:], re.M)
    return CI[start : start + nxt.start()] if nxt else CI[start:]


def test_suite_jobs_do_not_need_security_audit():
    for job in ("tests", "layering", "precompute-check"):
        body = _job_body(job)
        assert not re.search(r"^\s+needs:\s*security-audit\s*$", body, re.M), (
            f"D-J regression: job {job!r} is blocked on security-audit again. "
            "A red pip-audit on an Apple-only file must not skip Unit Tests."
        )


def test_security_audit_still_exists_as_parallel_gate():
    assert "  security-audit:" in CI
    assert "check_cves_osv.py" in _job_body("security-audit")
    assert "pip-audit --requirement requirements.txt" in CI
    assert "pip-audit --requirement requirements-linux.txt" in CI


def test_ubuntu_does_not_pip_audit_macos_or_windows_files():
    assert "pip-audit --requirement requirements-macos.txt" not in CI
    assert "pip-audit --requirement requirements-windows.txt" not in CI
    assert "requirements-macos.txt is NOT pip-audited" in CI
    assert "requirements-windows.txt is NOT pip-audited" in CI


def test_base_cryptography_is_50_windows_stays_46():
    """J2b: base pin closes GHSA-g6cj-pr64-35w5. Windows ARM64 has no wheel."""
    base = (REPO / "requirements.txt").read_text(encoding="utf-8")
    win = (REPO / "requirements-windows.txt").read_text(encoding="utf-8")
    assert re.search(r"^cryptography==50\.0\.0\b", base, re.M), (
        "requirements.txt must pin cryptography==50.0.0 (OSV 49.0.0 has "
        "GHSA-g6cj-pr64-35w5; 50.0.0 had 0 vulns on 2026-08-18)"
    )
    assert re.search(r"^cryptography==46\.0\.3\b", win, re.M), (
        "requirements-windows.txt must stay on 46.0.3 — no win_arm64 wheel "
        "after that (ADR-004). Do not copy the base pin."
    )
