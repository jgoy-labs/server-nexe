"""
Bundle integration tests — int8 embedding model.

Guards against regressions in installer/build-embedding-bundle.sh that
would re-introduce the FP32 default (~1058 MB) or break the manifest
contract that download_verify.py relies on.

Marked @pytest.mark.integration because they require the build artefacts
under InstallNexe.app/Contents/Resources/embeddings/ — skipped in CI fast
loop, run pre-release.

Note (2026-05-02): originally drafted for FP16 (prompt 05 v1.0.4). Adapted
to int8 after TODO 1.2 forced int8 due to FP16/ORT 1.25 InsertedPrecisionFreeCast
incompatibility. The basename remains `model.onnx` (Xenova HF cache redirect to
the int8 quantized variant). Bundle size dropped from 1058 MB FP32 → 282 MB int8.

Author: Jordi Goy
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
EMBEDDINGS_DIR = (
    PROJECT_ROOT / "InstallNexe.app" / "Contents" / "Resources" / "embeddings"
)
MANIFEST_PATH = EMBEDDINGS_DIR / "embeddings.manifest.json"


pytestmark = pytest.mark.integration


def _bundle_built() -> bool:
    return MANIFEST_PATH.is_file()


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not _bundle_built():
        pytest.skip(
            "Embedding bundle not built — run installer/build-embedding-bundle.sh"
        )
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_has_three_files(manifest: dict) -> None:
    """Manifest must declare exactly 3 SHA256 entries (basenames)."""
    files = manifest.get("files", {})
    assert len(files) == 3, f"Expected 3 entries, got {len(files)}: {list(files)}"


def test_manifest_basename_is_model_onnx(manifest: dict) -> None:
    """The ONNX model basename must be model.onnx (Xenova int8 redirect target)."""
    files = manifest.get("files", {})
    onnx_names = [n for n in files if n.endswith(".onnx")]
    assert len(onnx_names) == 1, f"Expected exactly 1 .onnx entry, got {onnx_names}"
    assert onnx_names[0] == "model.onnx", (
        f"basename regression: expected model.onnx, got {onnx_names[0]}"
    )


def test_manifest_sha256_matches_files(manifest: dict) -> None:
    """Re-hash each file under the bundle and assert the manifest digest matches."""
    files = manifest.get("files", {})
    for basename, expected_hash in files.items():
        # HF cache layout: snapshots/<rev>/<basename> is a symlink → blobs/<sha>
        matches = list(EMBEDDINGS_DIR.rglob(basename))
        assert matches, f"File {basename} not found under {EMBEDDINGS_DIR}"
        # Resolve the first match (follow symlink to actual blob)
        file_path = matches[0].resolve()
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, (
            f"SHA256 mismatch for {basename}: "
            f"manifest={expected_hash}, actual={actual_hash}"
        )


def test_bundle_size_int8_envelope() -> None:
    """int8 bundle must sit in the [200, 350] MB envelope.

    Lower bound: catches missing model file (sanity).
    Upper bound: catches regressions to FP32 (~1058 MB) or FP16 (~530 MB).

    Counting note: HF cache layout uses snapshots/<rev>/<basename> as symlinks
    pointing to blobs/<sha>. `stat()` follows symlinks by default, which would
    double-count the blob payload. Filter out symlinks (`is_symlink()`) so the
    measure matches what `du -sh` reports.
    """
    if not _bundle_built():
        pytest.skip("Embedding bundle not built")
    total_bytes = sum(
        f.stat().st_size
        for f in EMBEDDINGS_DIR.rglob("*")
        if f.is_file() and not f.is_symlink()
    )
    total_mb = total_bytes / (1024 * 1024)
    assert total_mb <= 350, (
        f"Bundle is {total_mb:.0f} MB — FP32/FP16 regression suspected "
        f"(int8 should be ~282 MB, FP32 was 1058 MB)"
    )
    assert total_mb >= 200, (
        f"Bundle is only {total_mb:.0f} MB — model file may be missing or empty"
    )
