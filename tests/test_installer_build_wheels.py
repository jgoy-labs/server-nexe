"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_build_wheels.py
Description: Smoke tests for installer/build-wheels-bundle.sh — the script
             that pre-downloads all Python wheels (arm64 macOS 13+) into
             InstallNexe.app/Contents/Resources/wheels/ so the client
             installer can run fully offline (pip --no-index --find-links).

             These tests do NOT invoke pip download (network + slow). They
             verify: file existence, executable bit, bash syntax, and the
             presence of the critical constants (platform, python version,
             ABI, required engines). Regression-catching, not integration.
────────────────────────────────────
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "installer" / "build-wheels-bundle.sh"


# ═══════════════════════════════════════════════════════════════════════
# Existence and executable bit
# ═══════════════════════════════════════════════════════════════════════


def test_build_wheels_script_exists() -> None:
    assert _SCRIPT.exists(), f"Build script missing: {_SCRIPT}"
    assert _SCRIPT.is_file()


def test_build_wheels_script_is_executable() -> None:
    import os

    assert os.access(_SCRIPT, os.X_OK), f"Script not executable: {_SCRIPT}"


# ═══════════════════════════════════════════════════════════════════════
# Bash syntax
# ═══════════════════════════════════════════════════════════════════════


def test_build_wheels_script_bash_syntax() -> None:
    """bash -n validates syntax without running the script."""
    result = subprocess.run(
        ["bash", "-n", str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"bash -n failed:\nstderr: {result.stderr}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Critical constants — regression guards
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def script_content() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def test_build_wheels_target_platform_is_macos_13_arm64(script_content: str) -> None:
    """Platform must match Jordi's decision: macOS 13 Ventura, arm64 only."""
    assert "macosx_13_0_arm64" in script_content


def test_build_wheels_python_version_matches_bundle(script_content: str) -> None:
    """Bundled Python is 3.12 — wheels must target the same minor."""
    assert 'PY_TARGET_VERSION="3.12"' in script_content
    assert 'PY_TARGET_ABI="cp312"' in script_content


def test_build_wheels_enforces_only_binary(script_content: str) -> None:
    """No source distributions — guarantees no compilation, no CLT prompt."""
    assert "--only-binary=:all:" in script_content


def test_build_wheels_includes_inference_engines(script_content: str) -> None:
    """llama-cpp-python + mlx-lm + mlx-vlm must be in the engines list."""
    assert "llama-cpp-python" in script_content
    assert "mlx-lm==0.31.2" in script_content
    assert "mlx-vlm==0.4.4" in script_content


def test_build_wheels_reads_requirements(script_content: str) -> None:
    """Both requirements files must be pip download sources."""
    assert "requirements.txt" in script_content
    assert "requirements-macos.txt" in script_content


def test_build_wheels_target_dir_inside_app_bundle(script_content: str) -> None:
    """Output must land in InstallNexe.app/Contents/Resources/wheels/ so
    the DMG build_dmg.sh picks it up automatically."""
    assert "InstallNexe.app" in script_content
    assert 'WHEELS_DIR="$RESOURCES/wheels"' in script_content


def test_build_wheels_has_size_sanity_check(script_content: str) -> None:
    """Script must fail if the bundle is obviously too small — catches
    silent pip failures (e.g. all deps already cached, nothing downloaded)."""
    assert "SIZE_MB" in script_content
    assert "-lt 100" in script_content  # fail if <100 MB


def test_build_wheels_verifies_critical_wheels_present(script_content: str) -> None:
    """After download, the script must assert critical wheels are there.
    Catches platform mismatches that would otherwise surface only at client install."""
    for critical in (
        "llama_cpp_python-",
        "mlx_lm-",
        "mlx_vlm-",
        "fastapi-",
        "pydantic-",
        "fastembed-",
        "onnxruntime-",
        "sqlcipher3-",
        "cryptography-",
    ):
        assert critical in script_content, f"Missing critical wheel check: {critical}"


def test_build_wheels_has_safe_bash_flags(script_content: str) -> None:
    """Script must fail fast on errors, unset vars, and pipe failures."""
    assert "set -euo pipefail" in script_content


def test_build_wheels_uses_abetlen_llama_cpp_index(script_content: str) -> None:
    """llama-cpp-python has no Metal wheels on PyPI — only sdist, which would
    require a C toolchain on the client (breaks clean-M1 install). The
    upstream maintainer (abetlen) publishes pre-built Metal wheels at
    abetlen.github.io/llama-cpp-python/whl/metal/. The script must add it
    as an --extra-index-url so pip download finds a ready-to-use wheel."""
    assert "abetlen.github.io/llama-cpp-python/whl/metal" in script_content
    assert "--extra-index-url" in script_content


def test_build_wheels_uses_bundle_python(script_content: str) -> None:
    """pip must run under the bundled Python 3.12, not host python3.
    Reason: pip evaluates dependency environment markers (python_version,
    platform_system, …) against the *running* interpreter even when
    --python-version/--abi are given. Build Macs with Python 3.13+ would
    dispatch markers like `numpy>=2.1.0 ; python_version >= "3.13"`, making
    resolution fail against our pinned numpy==1.26.4."""
    assert 'BUNDLE_PY="$APP_DIR/Contents/Resources/python/bin/python3"' in script_content
    assert 'PIP_BIN=("$BUNDLE_PY" -m pip)' in script_content


def test_build_wheels_handles_sdist_only_packages(script_content: str) -> None:
    """Some pure-Python deps (e.g. rumps) ship only as sdist on PyPI. The
    script must: (1) filter them out of pip-download (which uses
    --only-binary=:all:), and (2) build wheels locally from sdist with
    `pip wheel --no-deps` so the client install stays 100% offline."""
    assert "SDIST_ONLY_PKGS" in script_content
    assert '"rumps"' in script_content  # current whitelist entry
    assert 'wheel "$SPEC" --wheel-dir "$WHEELS_DIR" --no-deps' in script_content
