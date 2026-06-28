"""
Bundle integration tests — PyTorch + torchvision availability.

Guards against regressions where torch/torchvision get removed from the
wheels bundle and Qwen3 VL (or other multimodal models) crash at runtime
with MissingDependencyError.

Marked @pytest.mark.integration: requires the wheels to actually be
present in the bundle (supply-side) and importable in the test env
(runtime-side, may differ from client install).

Author: Jordi Goy
Refs: PLA-v1.0.4-beta TODO 1.5 + PLA-20260502-tests-bundle (TODO 1.3 + 1.5 closure)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
WHEELS_DIR = PROJECT_ROOT / "InstallNexe.app" / "Contents" / "Resources" / "wheels"
CHECKSUMS_FILE = PROJECT_ROOT / "installer" / "wheels-checksums.txt"


pytestmark = pytest.mark.integration



def _bundle_built() -> bool:
    """True when the wheels bundle is actually BUILT.

    The wheels are gitignored binaries: on a dev tree the directory exists
    but is empty, which is not a regression — it just means nobody ran
    installer/build-wheels-bundle.sh here. The supply-side guards only have
    teeth against a built bundle; an empty dir must skip, not fail.
    """
    return WHEELS_DIR.is_dir() and any(WHEELS_DIR.glob("*.whl"))


def test_torch_wheel_present() -> None:
    """Supply-side guard: torch wheel must exist in the bundle."""
    if not _bundle_built():
        pytest.skip(
            "Wheels bundle not built — run installer/build-wheels-bundle.sh"
        )
    matches = list(
        WHEELS_DIR.glob("torch-*-cp312-cp312-macosx_*_arm64.whl")
    )
    assert matches, (
        f"No torch wheel for cp312/macosx_arm64 under {WHEELS_DIR}. "
        f"Available: {sorted(p.name for p in WHEELS_DIR.glob('torch*'))}"
    )


def test_torchvision_wheel_present() -> None:
    """Supply-side guard: torchvision wheel must exist in the bundle."""
    if not _bundle_built():
        pytest.skip("Wheels bundle not built")
    matches = list(
        WHEELS_DIR.glob("torchvision-*-cp312-cp312-macosx_*_arm64.whl")
    )
    assert matches, (
        f"No torchvision wheel for cp312/macosx_arm64 under {WHEELS_DIR}. "
        f"Available: {sorted(p.name for p in WHEELS_DIR.glob('torchvision*'))}"
    )


def test_torch_importable() -> None:
    """Runtime guard: torch must import cleanly in the active Python."""
    pytest.importorskip("torch", reason="torch not installed in test env")
    import torch  # noqa: E402

    assert torch.__version__, "torch.__version__ empty"


def test_torchvision_importable() -> None:
    """Runtime guard: torchvision must import cleanly in the active Python."""
    pytest.importorskip(
        "torchvision", reason="torchvision not installed in test env"
    )
    import torchvision  # noqa: E402

    assert torchvision.__version__, "torchvision.__version__ empty"


def test_wheels_checksums_match_bundle() -> None:
    """SHA256 in installer/wheels-checksums.txt must match the actual bundled wheels.

    Closes the loop between TODO 1.3 (wheel pinning) and TODO 1.5 (regression
    guard): if anyone replaces a wheel without updating the checksum file
    (or vice versa), this test fails.
    """
    if not CHECKSUMS_FILE.is_file():
        pytest.skip("wheels-checksums.txt not present (legacy DMG?)")
    if not _bundle_built():
        pytest.skip("Wheels bundle not built")

    for line_num, raw_line in enumerate(
        CHECKSUMS_FILE.read_text().splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        assert len(parts) == 2, (
            f"Malformed checksums line {line_num}: {raw_line!r}"
        )
        expected_hash, wheel_name = parts
        wheel_path = WHEELS_DIR / wheel_name
        assert wheel_path.is_file(), (
            f"Pinned wheel missing from bundle: {wheel_name}"
        )
        actual = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
        assert actual == expected_hash, (
            f"SHA256 mismatch for {wheel_name}: "
            f"pinned={expected_hash}, actual={actual}"
        )
