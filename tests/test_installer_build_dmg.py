"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_build_dmg.py
Description: Smoke tests for installer/build_dmg.sh — the orchestrator
             that builds InstallNexe.app, creates the DMG, signs, and
             notarizes. These tests verify bash syntax and the wiring
             of the offline install phase (bundle build + size validation).

             They do NOT run the actual DMG build (slow + network +
             Apple signing keychain). That's covered by /dmg-nexe.
────────────────────────────────────
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "installer" / "build_dmg.sh"


def test_build_dmg_script_exists() -> None:
    assert _SCRIPT.exists(), f"Build script missing: {_SCRIPT}"


def test_build_dmg_script_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"bash -n failed:\nstderr: {result.stderr}"


@pytest.fixture(scope="module")
def script_content() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def test_invokes_wheels_build_script(script_content: str) -> None:
    """build_dmg.sh must orchestrate build-wheels-bundle.sh."""
    assert "build-wheels-bundle.sh" in script_content


def test_invokes_embedding_build_script(script_content: str) -> None:
    """build_dmg.sh must orchestrate build-embedding-bundle.sh."""
    assert "build-embedding-bundle.sh" in script_content


def test_exposes_skip_bundles_flag(script_content: str) -> None:
    """--skip-bundles flag lets dev iterations reuse existing bundles."""
    assert "--skip-bundles" in script_content
    assert "SKIP_BUNDLES" in script_content


def test_validates_wheels_bundle_size(script_content: str) -> None:
    """Step 5b must fail hard if the wheels bundle is too small."""
    assert "WHEELS_SIZE_MB" in script_content
    # Catch silent failures: bundle present but empty or partial
    assert 'WHEELS_SIZE_MB" -lt 100' in script_content


def test_validates_embedding_bundle_size(script_content: str) -> None:
    """Step 5b must fail hard if the embedding bundle is too small."""
    assert "EMBEDDINGS_SIZE_MB" in script_content
    assert 'EMBEDDINGS_SIZE_MB" -lt 400' in script_content


def test_uses_exit_code_14_for_bundle_errors(script_content: str) -> None:
    """Bundle failures must exit with code 14 (distinct from generic exit 1)
    so /dmg-nexe can handle them with a specific message."""
    assert "bundle_error" in script_content
    assert "exit 14" in script_content


def test_has_safe_bash_flags(script_content: str) -> None:
    assert "set -euo pipefail" in script_content
