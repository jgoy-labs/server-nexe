"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_mlx_pin_consistency.py
Description: Adversarial cross-consistency guardrail for the MLX engine pins
             (mlx-lm, mlx-vlm). Regression test for finding B069.

             The MLX inference engines are pinned in FOUR independent places:
               1. requirements-macos.txt           — declared dependency
               2. installer/installer_setup_env.py — what the installer
                  actually `pip install`s at runtime (_install_mlx_engines)
               3. installer/build-wheels-bundle.sh — which wheels get bundled
                  for offline install (ENGINES array)
               4. installer/check_cves_osv.py       — which version the CVE
                  audit (OSV) actually vets (BUNDLE_PINS)

             B069 root cause: requirements-macos.txt declared mlx-lm==0.31.3
             while the installer downgraded to ==0.31.2 at runtime, the bundle
             shipped 0.31.2 wheels, and the CVE audit vetted 0.31.2. Net result:
             declared (.3) != shipped/audited (.2) — a CVE fixed only in .3
             would report "patched" while the product runs .2.

             Existing tests (test_installer_build_wheels.py) only assert each
             file's INTERNAL constants; nothing cross-checked the four sources
             against each other. This test closes that gap: it parses the
             pinned version out of each source and asserts they all agree.

             Pure text parsing — no pip, no network, no install.
────────────────────────────────────
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_REQ_MACOS = _ROOT / "requirements-macos.txt"
_SETUP_ENV = _ROOT / "installer" / "installer_setup_env.py"
_BUILD_WHEELS = _ROOT / "installer" / "build-wheels-bundle.sh"
_CHECK_CVES = _ROOT / "installer" / "check_cves_osv.py"

# Engines whose pin MUST be identical across all four sources.
_ENGINES = ("mlx-lm", "mlx-vlm")


def _pin_in_requirements(text: str, pkg: str) -> str | None:
    """Parse `<pkg>==X.Y.Z` from a pip requirements file (one spec per line)."""
    pat = re.compile(rf"^\s*{re.escape(pkg)}==([0-9][^\s#]*)", re.MULTILINE)
    m = pat.search(text)
    return m.group(1) if m else None


def _pin_in_pip_spec(text: str, pkg: str) -> str | None:
    """Parse `"<pkg>==X.Y.Z"` from a quoted pip spec literal (py tuple / bash array)."""
    pat = re.compile(rf'["\']{re.escape(pkg)}==([0-9][^"\'\s]*)["\']')
    m = pat.search(text)
    return m.group(1) if m else None


def _pin_in_bundle_pins(text: str, pkg: str) -> str | None:
    """Parse `("<pkg>", "X.Y.Z")` from check_cves_osv.py BUNDLE_PINS tuples."""
    pat = re.compile(
        rf'\(\s*["\']{re.escape(pkg)}["\']\s*,\s*["\']([0-9][^"\']*)["\']\s*\)'
    )
    m = pat.search(text)
    return m.group(1) if m else None


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    for p in (_REQ_MACOS, _SETUP_ENV, _BUILD_WHEELS, _CHECK_CVES):
        assert p.exists(), f"Pin source missing: {p}"
    return {
        "requirements-macos.txt": _REQ_MACOS.read_text(encoding="utf-8"),
        "installer_setup_env.py": _SETUP_ENV.read_text(encoding="utf-8"),
        "build-wheels-bundle.sh": _BUILD_WHEELS.read_text(encoding="utf-8"),
        "check_cves_osv.py": _CHECK_CVES.read_text(encoding="utf-8"),
    }


def _collect_pins(sources: dict[str, str], pkg: str) -> dict[str, str]:
    """Resolve the pinned version of `pkg` in each of the four sources."""
    pins = {
        "requirements-macos.txt": _pin_in_requirements(sources["requirements-macos.txt"], pkg),
        "installer_setup_env.py": _pin_in_pip_spec(sources["installer_setup_env.py"], pkg),
        "build-wheels-bundle.sh": _pin_in_pip_spec(sources["build-wheels-bundle.sh"], pkg),
        "check_cves_osv.py": _pin_in_bundle_pins(sources["check_cves_osv.py"], pkg),
    }
    # Every source must actually pin the engine — a None means the parser
    # (or the pin) silently went missing, which would mask a real divergence.
    missing = [src for src, v in pins.items() if v is None]
    assert not missing, f"{pkg} pin not found in: {missing} (pins={pins})"
    return pins  # type: ignore[return-value]


@pytest.mark.parametrize("pkg", _ENGINES)
def test_mlx_pin_is_identical_across_all_four_sources(sources: dict[str, str], pkg: str) -> None:
    """The pin for each MLX engine must be byte-identical in all four sources.

    requirements-macos.txt (declared), installer_setup_env.py (installed at
    runtime), build-wheels-bundle.sh (bundled wheels) and check_cves_osv.py
    (CVE-audited) must NEVER diverge: declared == shipped == audited. A
    mismatch here is finding B069 reappearing.
    """
    pins = _collect_pins(sources, pkg)
    distinct = set(pins.values())
    assert len(distinct) == 1, (
        f"{pkg} pin diverges across sources (B069): {pins}. "
        f"All four must declare the SAME version (declared == shipped == audited)."
    )


def test_mlx_lm_pin_matches_audited_version(sources: dict[str, str]) -> None:
    """Anchor: the declared mlx-lm pin must equal the CVE-audited one.

    Opção A of B069 aligned requirements-macos.txt down to the version that
    actually ships and is OSV-audited (0.31.2). This asserts the declaration
    can never silently drift ahead of the audit again.
    """
    pins = _collect_pins(sources, "mlx-lm")
    assert pins["requirements-macos.txt"] == pins["check_cves_osv.py"], (
        f"Declared mlx-lm ({pins['requirements-macos.txt']}) must match the "
        f"CVE-audited version ({pins['check_cves_osv.py']}) — otherwise the "
        f"OSV audit vets a version the product does not actually run (B069)."
    )
