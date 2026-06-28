"""
────────────────────────────────────
Server Nexe
Location: tests/test_mlx_per_file_pinning.py
Description: ADR B046b — tier-2 provider-published MLX pinning. Verifies the
             per-LFS-file integrity path: matching weights pass, a tampered or
             missing pinned weight fails CLOSED, the tier-1 dir-hash still
             wins, and the has_pin helper behaves. No network: provider pins
             are injected. (Ollama is not pinned — ADR B251 — so it has no
             coverage here.)
────────────────────────────────────
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from core.integrity.hashing import sha256_of_file
from installer import download_verify as dv
from installer import installer_catalog_data as cat
from installer.download_verify import DownloadIntegrityError, verify_download_integrity


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _pins(*, mlx=None):
    return {"mlx_file_hashes": mlx or {}}


# ═══════════════════════════════════════════════════════════════════════
# Accessors / has_pin
# ═══════════════════════════════════════════════════════════════════════
def test_get_mlx_file_hashes_reads_provider_pins():
    pins = _pins(mlx={"mlx-community/Foo-4bit": {"w.safetensors": "a" * 64}})
    with patch.object(cat, "_load_provider_pins", return_value=pins):
        assert cat.get_expected_mlx_file_hashes("mlx-community/Foo-4bit") == {
            "w.safetensors": "a" * 64}
        assert cat.get_expected_mlx_file_hashes("unknown/repo") is None


def test_has_pin_tiers():
    """has_pin: tier-1 (any engine) or tier-2 MLX. Ollama is never pinned
    (ADR B251: content-addressed pull) → has_pin('ollama', ...) is False."""
    pins = _pins(mlx={"mlx/repo": {"w.safetensors": "b" * 64}})
    with patch.object(cat, "_load_provider_pins", return_value=pins):
        with patch.object(cat, "get_expected_sha256", return_value=None):
            assert cat.has_pin("mlx", "mlx/repo") is True        # tier-2 mlx
            assert cat.has_pin("mlx", "mlx/unpinned") is False   # neither tier
            assert cat.has_pin("ollama", "oll:1b") is False      # never pinned
            assert cat.has_pin("gguf", "ghost") is False


# ═══════════════════════════════════════════════════════════════════════
# _verify_mlx_files — the security core
# ═══════════════════════════════════════════════════════════════════════
def test_mlx_all_files_match_returns_true(tmp_path):
    sha1 = _write(tmp_path / "model-00001.safetensors", b"weights-A")
    sha2 = _write(tmp_path / "model-00002.safetensors", b"weights-B")
    _write(tmp_path / "config.json", b"{}")  # non-LFS, not pinned, ignored
    expected = {
        "model-00001.safetensors": sha1,
        "model-00002.safetensors": sha2,
    }
    assert dv._verify_mlx_files(tmp_path, "mlx/repo", expected) is True


def test_mlx_tampered_weight_fails_closed(tmp_path):
    _write(tmp_path / "model.safetensors", b"tampered-bytes")
    expected = {"model.safetensors": "9" * 64}  # wrong hash
    with pytest.raises(DownloadIntegrityError) as ei:
        dv._verify_mlx_files(tmp_path, "mlx/repo", expected)
    assert "mismatch" in str(ei.value).lower()
    assert (tmp_path / "model.safetensors").exists()  # preserved


def test_mlx_missing_pinned_weight_fails_closed(tmp_path):
    _write(tmp_path / "config.json", b"{}")
    expected = {"model.safetensors": "a" * 64}  # file not present
    with pytest.raises(DownloadIntegrityError) as ei:
        dv._verify_mlx_files(tmp_path, "mlx/repo", expected)
    assert "missing" in str(ei.value).lower()


def test_mlx_finds_file_in_nested_snapshot(tmp_path):
    nested = tmp_path / "snapshots" / "abc"
    nested.mkdir(parents=True)
    sha = _write(nested / "model.safetensors", b"deep-weights")
    assert dv._verify_mlx_files(tmp_path, "mlx/repo", {"model.safetensors": sha}) is True


def test_locate_rejects_symlink_escape(tmp_path):
    """A pinned name symlinked outside the snapshot root is not accepted."""
    outside = tmp_path.parent / "evil.bin"
    outside.write_bytes(b"attacker")
    root = tmp_path / "snap"
    root.mkdir()
    (root / "model.safetensors").symlink_to(outside)
    assert dv._locate_in_dir(root, "model.safetensors") is None


# ═══════════════════════════════════════════════════════════════════════
# verify_download_integrity — end to end (MLX tier-2)
# ═══════════════════════════════════════════════════════════════════════
def test_integrity_mlx_tier2_match(tmp_path):
    sha = _write(tmp_path / "model.safetensors", b"good")
    pins = _pins(mlx={"mlx/repo": {"model.safetensors": sha}})
    with patch.object(cat, "_load_provider_pins", return_value=pins):
        with patch.object(cat, "get_expected_sha256", return_value=None):
            assert verify_download_integrity("mlx", "mlx/repo", tmp_path) is True


def test_integrity_mlx_tier2_mismatch_raises(tmp_path):
    _write(tmp_path / "model.safetensors", b"bad")
    pins = _pins(mlx={"mlx/repo": {"model.safetensors": "0" * 64}})
    with patch.object(cat, "_load_provider_pins", return_value=pins):
        with patch.object(cat, "get_expected_sha256", return_value=None):
            with pytest.raises(DownloadIntegrityError):
                verify_download_integrity("mlx", "mlx/repo", tmp_path)


def test_integrity_mlx_tier1_dirhash_still_wins(tmp_path):
    """When a self-computed dir-hash exists, tier-1 path runs (not per-file)."""
    _write(tmp_path / "model.safetensors", b"x")
    real_dir_hash = dv.sha256_of_dir(tmp_path)
    # tier-1 present (patch the shared data dict so both module references see
    # it) → must use dir-hash; the deliberately-wrong provider pins are ignored.
    pins = _pins(mlx={"mlx-tier1/repo": {"model.safetensors": "deadbeef" * 8}})
    with patch.object(cat, "_load_provider_pins", return_value=pins):
        with patch.dict(cat.MODEL_WEIGHT_SHA256,
                        {("mlx", "mlx-tier1/repo"): real_dir_hash}):
            assert verify_download_integrity("mlx", "mlx-tier1/repo", tmp_path) is True


def test_integrity_mlx_unpinned_returns_false(tmp_path):
    """No tier-1, no tier-2 → unpinned → False (caller gates on consent)."""
    _write(tmp_path / "model.safetensors", b"x")
    with patch.object(cat, "_load_provider_pins", return_value=_pins()):
        with patch.object(cat, "get_expected_sha256", return_value=None):
            assert verify_download_integrity("mlx", "mlx/repo", tmp_path) is False
