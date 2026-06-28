"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_cve_gate_wired.py
Description: B070 — the bundle CVE gate (installer/check_cves_osv.py) must be
             invoked by CI, never left orphan. The gate pins torch / torchvision /
             llama-cpp-python / transformers, which pip-audit on
             requirements*.txt does NOT cover (bundle-only, installed dynamically).
             Anti-regression guard so the gate cannot silently become orphan again.
────────────────────────────────────
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ci_invokes_bundle_cve_gate():
    # B070: the OSV bundle CVE gate was orphan — no CI/ship step ran it.
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "check_cves_osv.py" in ci, (
        "B070 regression: the OSV bundle CVE gate is orphan again. Wire "
        "`python installer/check_cves_osv.py` into the security-audit job of "
        ".github/workflows/ci.yml — otherwise torch/transformers/llama-cpp CVEs "
        "ship unscanned (pip-audit only sees requirements*.txt)."
    )


def test_cve_gate_covers_packages_absent_from_requirements():
    # The gate exists precisely to cover bundle-only deps that pip-audit cannot
    # see in requirements*.txt. If these drop out of BUNDLE_PINS the gate is moot.
    from installer.check_cves_osv import BUNDLE_PINS

    pinned = {name for name, _ in BUNDLE_PINS}
    for pkg in ("torch", "torchvision", "transformers", "llama-cpp-python"):
        assert pkg in pinned, (
            f"{pkg} must stay in BUNDLE_PINS — it is bundle-only and invisible "
            "to pip-audit on requirements*.txt."
        )
