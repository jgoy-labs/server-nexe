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


def test_build_wheels_target_platform_is_macos_14_arm64(script_content: str) -> None:
    """Platform must match project decision: macOS 14 Sonoma, arm64 only.
    macOS 13 Ventura was dropped 2026-04-16: mlx 0.30.4+ (required by our
    pinned mlx-lm 0.31.3) publishes wheels only for macosx_14_0_arm64+."""
    assert "macosx_14_0_arm64" in script_content
    assert "macosx_13_0_arm64" not in script_content  # regression guard


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
    assert "mlx-lm==0.31.3" in script_content
    assert "mlx-vlm==0.4.4" in script_content


def test_build_wheels_includes_pytorch_torchvision(script_content: str) -> None:
    """torch + torchvision must be in the engines list with EXACT version pins.
    They are required at runtime by Qwen3 VL and other multimodal models
    (Qwen3VLVideoProcessor needs torchvision for image preprocessing).
    The compat matrix is tight: torchvision pins torch via Requires-Dist exactly,
    so bumping torch ALWAYS requires bumping torchvision in lockstep — empirical
    pin policy, not just a coincidence (v1.0.4-beta TODO 1.3)."""
    assert "torch==2.11.0" in script_content, (
        "torch must be pinned EXACTLY (no `>=`, no `~=`) in the ENGINES list — "
        "supply chain stability requires reproducible builds."
    )
    assert "torchvision==0.26.0" in script_content, (
        "torchvision must be pinned EXACTLY to the version that pairs with the "
        "torch pin (Requires-Dist: torch (==2.11.0) in torchvision METADATA)."
    )


def test_build_wheels_expected_substrings_includes_pytorch(script_content: str) -> None:
    """Post-download sanity check must verify torch/torchvision wheels landed.
    This catches platform/ABI mismatches that would otherwise surface only at
    client install (when pip --no-index --find-links could not resolve them)."""
    assert '"torch-"' in script_content, (
        "EXPECTED_SUBSTRINGS must include 'torch-' so missing torch wheel "
        "is caught at build time, not on the user's first install."
    )
    assert '"torchvision-"' in script_content, (
        "EXPECTED_SUBSTRINGS must include 'torchvision-'."
    )


def test_build_wheels_invokes_sha256_verification(script_content: str) -> None:
    """Step 4b (B8 supply chain check) must be wired in: the script must
    define _sha256(), reference wheels-checksums.txt, and contain the abort
    branches exit 7 (missing pinned wheel) and exit 8 (SHA mismatch)."""
    code_only = "\n".join(
        line for line in script_content.splitlines() if not line.lstrip().startswith("#")
    )
    assert "_sha256()" in script_content, "_sha256() helper definition missing"
    assert "_sha256" in code_only, "_sha256 not invoked outside comments"
    assert "wheels-checksums.txt" in code_only, (
        "wheels-checksums.txt not referenced in executable code — "
        "the supply chain check is missing or commented out."
    )
    assert "exit 7" in code_only, "exit 7 (missing pinned wheel) branch missing"
    assert "exit 8" in code_only, "exit 8 (SHA256 mismatch) branch missing"


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
    silent pip failures (e.g. all deps already cached, nothing downloaded).

    Floor was raised from 100 MB → 250 MB after v1.0.4-beta TODO 1.3 added
    torch + torchvision (~92 MB net delta); the new floor catches a silent
    failure that leaves only the original ~220 MB worth of wheels (i.e.
    torch+torchvision did NOT download). Ceiling raised 500 → 600 MB to
    avoid a false-positive WARN against the new ~330 MB baseline while
    still catching an accidental Linux/CUDA transitive."""
    assert "SIZE_MB" in script_content
    assert "-lt 250" in script_content, (
        "Bundle floor must be 250 MB (post torch+torchvision baseline ~330 MB)"
    )
    assert "-gt 600" in script_content, (
        "Bundle ceiling must be 600 MB to avoid false-positive WARN"
    )
    assert "-lt 100" not in script_content, (
        "Old 100 MB floor must be removed — would no longer catch the case "
        "where torch+torchvision silently failed to download (bundle 220 MB)."
    )


def test_build_wheels_verifies_critical_wheels_present(script_content: str) -> None:
    """After download, the script must assert critical wheels are there.
    Catches platform mismatches that would otherwise surface only at client install."""
    for critical in (
        "llama_cpp_python-",
        "mlx_lm-",
        "mlx_vlm-",
        "torch-",          # v1.0.4-beta TODO 1.3 — Qwen3 VL multimodal runtime
        "torchvision-",    # paired with torch — image preprocessing
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
