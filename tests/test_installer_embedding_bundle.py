"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_embedding_bundle.py
Description: Integrity tests for the DMG-bundled fastembed model
             (internal security review AUD-INT-001 §2.7).

Covers:
  * ``verify_embedding_bundle`` at runtime — happy path, manifest missing
    (legacy DMG), tampered file, file missing from bundle, invalid JSON.
  * The generator in ``build-embedding-bundle.sh`` — bash syntax check
    plus a smoke test that the Step 6 block writes the manifest with the
    three critical fields.
────────────────────────────────────
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.integrity.hashing import sha256_of_file
from installer.download_verify import (
    DownloadIntegrityError,
    verify_embedding_bundle,
)


# ════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════


def _make_bundle(root: Path, *, write_manifest: bool = True) -> dict:
    """Build a minimal bundle with the 3 critical files + optional manifest.

    Returns the manifest dict so callers can tamper with it.
    """
    root.mkdir(parents=True, exist_ok=True)
    contents = {
        "model.onnx": b"onnx-weights",
        "tokenizer.json": b'{"type": "WordPiece"}',
        "config.json": b'{"hidden_size": 768}',
    }
    for name, data in contents.items():
        (root / name).write_bytes(data)
    manifest = {
        "schema_version": 1,
        "model_name": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "generated_at": "2026-04-23T00:00:00Z",
        "files": {name: sha256_of_file(root / name) for name in contents},
    }
    if write_manifest:
        (root / "embeddings.manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    return manifest


# ════════════════════════════════════════════════════════════════════════
# verify_embedding_bundle
# ════════════════════════════════════════════════════════════════════════


def test_verify_embedding_bundle_happy_path(tmp_path: Path) -> None:
    bundle = tmp_path / "embeddings"
    _make_bundle(bundle)
    assert verify_embedding_bundle(bundle) is True


def test_verify_embedding_bundle_locates_nested_files(tmp_path: Path) -> None:
    """Real DMG bundles place files inside models--org--name/snapshots/rev/.
    The validator must recursively locate them."""
    bundle = tmp_path / "embeddings"
    nested = bundle / "models--org--name" / "snapshots" / "abcd"
    nested.mkdir(parents=True)
    for name, data in {
        "model.onnx": b"x",
        "tokenizer.json": b"y",
        "config.json": b"z",
    }.items():
        (nested / name).write_bytes(data)
    manifest = {
        "schema_version": 1,
        "model_name": "org/name",
        "generated_at": "2026-04-23T00:00:00Z",
        "files": {name: sha256_of_file(nested / name) for name in ("model.onnx", "tokenizer.json", "config.json")},
    }
    (bundle / "embeddings.manifest.json").write_text(json.dumps(manifest))
    assert verify_embedding_bundle(bundle) is True


def test_verify_embedding_bundle_missing_manifest_is_legacy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging
    caplog.set_level(logging.WARNING, logger="installer.download_verify")
    bundle = tmp_path / "embeddings"
    _make_bundle(bundle, write_manifest=False)
    assert verify_embedding_bundle(bundle) is False
    assert any(
        "legacy" in rec.getMessage().lower() or "no integrity manifest" in rec.getMessage().lower()
        for rec in caplog.records
    )


def test_verify_embedding_bundle_tampered_file_raises(tmp_path: Path) -> None:
    bundle = tmp_path / "embeddings"
    _make_bundle(bundle)
    # Tamper with one of the files AFTER manifest is written.
    (bundle / "tokenizer.json").write_bytes(b"tampered-content")
    with pytest.raises(DownloadIntegrityError) as excinfo:
        verify_embedding_bundle(bundle)
    msg = str(excinfo.value)
    assert "tokenizer.json" in msg
    assert "tampered" in msg.lower() or "mismatch" in msg.lower() or "corrupted" in msg.lower()


def test_verify_embedding_bundle_missing_file_raises(tmp_path: Path) -> None:
    bundle = tmp_path / "embeddings"
    _make_bundle(bundle)
    (bundle / "config.json").unlink()
    with pytest.raises(DownloadIntegrityError) as excinfo:
        verify_embedding_bundle(bundle)
    assert "config.json" in str(excinfo.value)


def test_verify_embedding_bundle_invalid_json_raises(tmp_path: Path) -> None:
    bundle = tmp_path / "embeddings"
    _make_bundle(bundle)
    (bundle / "embeddings.manifest.json").write_text("{not json")
    with pytest.raises(DownloadIntegrityError) as excinfo:
        verify_embedding_bundle(bundle)
    assert "manifest" in str(excinfo.value).lower()


def test_verify_embedding_bundle_empty_files_legacy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Manifest present but ``files`` empty — treat as legacy (warning,
    not a raise) to keep bisection between old and new DMGs painless."""
    import logging
    caplog.set_level(logging.WARNING, logger="installer.download_verify")
    bundle = tmp_path / "embeddings"
    _make_bundle(bundle)
    manifest = json.loads((bundle / "embeddings.manifest.json").read_text())
    manifest["files"] = {}
    (bundle / "embeddings.manifest.json").write_text(json.dumps(manifest))
    assert verify_embedding_bundle(bundle) is False


def test_verify_embedding_bundle_missing_dir_returns_false(tmp_path: Path) -> None:
    """A caller may pass a path to a bundle that was never downloaded.
    Verifier returns False instead of crashing — the outer copy step
    already handles the missing-bundle case."""
    assert verify_embedding_bundle(tmp_path / "does-not-exist") is False


def test_verify_embedding_bundle_rejects_symlink_escape(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A tampered bundle could point the ``model.onnx`` entry at a file
    outside the bundle root (say ``/etc/passwd``) whose hash happens to
    match the pin. The verifier must refuse symlinks that escape."""
    import logging
    caplog.set_level(logging.WARNING, logger="installer.download_verify")
    bundle = tmp_path / "embeddings"
    bundle.mkdir()
    # Create a victim file OUTSIDE the bundle.
    outside = tmp_path / "outside" / "secret"
    outside.parent.mkdir()
    outside.write_bytes(b"secret-content")
    # Tokenizer + config live honestly inside the bundle.
    (bundle / "tokenizer.json").write_bytes(b"{}")
    (bundle / "config.json").write_bytes(b"{}")
    # model.onnx is a symlink to the outside file.
    (bundle / "model.onnx").symlink_to(outside)
    manifest = {
        "schema_version": 1,
        "model_name": "x",
        "generated_at": "2026-04-23T00:00:00Z",
        # Use a pin that MATCHES the outside file so absent of the symlink
        # check the verifier would accept it.
        "files": {
            "model.onnx": sha256_of_file(outside),
            "tokenizer.json": sha256_of_file(bundle / "tokenizer.json"),
            "config.json": sha256_of_file(bundle / "config.json"),
        },
    }
    (bundle / "embeddings.manifest.json").write_text(json.dumps(manifest))
    # With the symlink escape check in place, the verifier treats the
    # symlinked file as missing and raises DownloadIntegrityError.
    with pytest.raises(DownloadIntegrityError) as excinfo:
        verify_embedding_bundle(bundle)
    assert "model.onnx" in str(excinfo.value)
    assert any(
        "escapes bundle root" in rec.getMessage() for rec in caplog.records
    )


# ════════════════════════════════════════════════════════════════════════
# Build script — Step 6 must emit the manifest
# ════════════════════════════════════════════════════════════════════════


_ROOT = Path(__file__).parent.parent
_BUILD_SCRIPT = _ROOT / "installer" / "build-embedding-bundle.sh"


def test_build_script_has_manifest_generation_step() -> None:
    """Fast grep test — ensures the Step 6 block survives edits to the
    script without running the whole bash pipeline."""
    text = _BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "embeddings.manifest.json" in text, (
        "build-embedding-bundle.sh must emit embeddings.manifest.json "
        "(internal security review AUD-INT-001 §2.7)"
    )
    assert "sha256" in text.lower()
    assert "Step 6" in text or "step 6" in text.lower()


def test_build_script_still_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_BUILD_SCRIPT)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"bash -n failed:\nstderr: {result.stderr}"
