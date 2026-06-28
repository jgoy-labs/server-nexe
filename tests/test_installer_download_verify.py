"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_download_verify.py
Description: Unit tests for installer.download_verify — post-download SHA256
             enforcement for Hugging Face MLX snapshots, GGUF files and
             Ollama models (internal security review AUD-INT-001 §2.7).

             TDD RED → GREEN flow. Tests mock subprocess / filesystem so
             they stay in the default fast suite (no network, no real
             ollama daemon, no HF downloads).
────────────────────────────────────
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from installer.download_verify import (
    DownloadIntegrityError,
    verify_download_integrity,
)


_VALID_HEX = "0" * 64
_OTHER_HEX = "f" * 64


# ════════════════════════════════════════════════════════════════════════
# verify_download_integrity — GGUF (file)
# ════════════════════════════════════════════════════════════════════════


def _known_gguf_url() -> str:
    return (
        "https://huggingface.co/hdnh2006/BSC-LT-salamandra-7b-instruct-gguf/"
        "resolve/main/salamandra-7b-instruct-Q4_K_M.gguf"
    )


def test_verify_gguf_legacy_when_catalog_unpinned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a GGUF entry has pin=None, legacy mode returns False + warning."""
    caplog.set_level(logging.WARNING)
    from installer import installer_catalog_data
    # Force the entry to None to test the unpinned path
    original = installer_catalog_data.MODEL_WEIGHT_SHA256.copy()
    monkeypatch.setattr(
        installer_catalog_data, "MODEL_WEIGHT_SHA256",
        {**original, ("gguf", _known_gguf_url()): None},
    )
    target = tmp_path / "weights.gguf"
    target.write_bytes(b"arbitrary content")
    result = verify_download_integrity("gguf", _known_gguf_url(), target)
    assert result is False  # unpinned → False + warning
    assert any(
        "legacy" in rec.getMessage().lower() or "no SHA256" in rec.getMessage()
        for rec in caplog.records
    )


def test_verify_gguf_pinned_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "weights.gguf"
    payload = b"deterministic bytes"
    target.write_bytes(payload)
    # Pin the URL to its real hash so this test is stable.
    from core.integrity.hashing import sha256_of_bytes
    expected = sha256_of_bytes(payload)
    url = _known_gguf_url()
    monkeypatch.setitem(
        __import__("installer.installer_catalog_data", fromlist=["MODEL_WEIGHT_SHA256"]).MODEL_WEIGHT_SHA256,
        ("gguf", url),
        expected,
    )
    assert verify_download_integrity("gguf", url, target) is True


def test_verify_gguf_pinned_mismatch_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "weights.gguf"
    target.write_bytes(b"actual content")
    url = _known_gguf_url()
    # Pin to a digest the file does not match.
    monkeypatch.setitem(
        __import__("installer.installer_catalog_data", fromlist=["MODEL_WEIGHT_SHA256"]).MODEL_WEIGHT_SHA256,
        ("gguf", url),
        _OTHER_HEX,
    )
    with pytest.raises(DownloadIntegrityError) as excinfo:
        verify_download_integrity("gguf", url, target)
    err = excinfo.value
    assert "SHA256 mismatch" in str(err)
    assert "ollama rm" not in str(err)  # engine-specific retry text only
    assert "rm " in str(err)
    # The partial file must remain on disk for post-mortem.
    assert target.exists()


def test_download_gguf_interactive_mismatch_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the F4.1 review finding A: in interactive mode
    (``headless=False``), a ``DownloadIntegrityError`` raised by
    ``verify_download_integrity`` was caught by the generic
    ``except Exception`` branch and downgraded into "show manual
    instructions" — letting the install continue past a failed integrity
    check. The dedicated ``except DownloadIntegrityError: raise`` block
    must propagate unconditionally."""
    from installer.installer_setup_models import _download_gguf_model

    gguf_url = _known_gguf_url()
    monkeypatch.setitem(
        __import__("installer.installer_catalog_data", fromlist=["MODEL_WEIGHT_SHA256"]).MODEL_WEIGHT_SHA256,
        ("gguf", gguf_url),
        _OTHER_HEX,  # anything the file won't match after curl writes it
    )

    project_root = tmp_path

    def fake_run(cmd, check=False, **kwargs):
        # Emulate curl: write a payload whose sha256 will NOT match the pin.
        models_dir = project_root / "storage" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        (models_dir / gguf_url.split("/")[-1]).write_bytes(b"payload-not-matching-pin")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch(
        "installer.installer_setup_models.subprocess.run", side_effect=fake_run
    ), pytest.raises(DownloadIntegrityError):
        _download_gguf_model(
            {"id": gguf_url, "name": "test", "disk_size": "~1 GB"},
            project_root,
            headless=False,  # <<< the path that used to silently downgrade
        )


# ════════════════════════════════════════════════════════════════════════
# verify_download_integrity — MLX (directory)
# ════════════════════════════════════════════════════════════════════════


def _mlx_id() -> str:
    return "mlx-community/gemma-3-4b-it-4bit"


def test_verify_mlx_pinned_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    (snapshot / "config.json").write_bytes(b'{"k": 1}')
    (snapshot / "weights.safetensors").write_bytes(b"weights")
    from core.integrity.hashing import sha256_of_dir
    expected = sha256_of_dir(snapshot)
    monkeypatch.setitem(
        __import__("installer.installer_catalog_data", fromlist=["MODEL_WEIGHT_SHA256"]).MODEL_WEIGHT_SHA256,
        ("mlx", _mlx_id()),
        expected,
    )
    assert verify_download_integrity("mlx", _mlx_id(), snapshot) is True


def test_verify_mlx_mismatch_includes_mlx_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    (snapshot / "config.json").write_bytes(b"v2")
    monkeypatch.setitem(
        __import__("installer.installer_catalog_data", fromlist=["MODEL_WEIGHT_SHA256"]).MODEL_WEIGHT_SHA256,
        ("mlx", _mlx_id()),
        _OTHER_HEX,
    )
    with pytest.raises(DownloadIntegrityError) as excinfo:
        verify_download_integrity("mlx", _mlx_id(), snapshot)
    assert "rm -rf" in str(excinfo.value)  # mlx retry template
    assert snapshot.exists()


# ════════════════════════════════════════════════════════════════════════
# verify_download_integrity — Ollama (content-addressed, ADR B251)
# ════════════════════════════════════════════════════════════════════════


def test_verify_ollama_short_circuits_to_true(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Ollama integrity is delegated to its content-addressed pull (ADR B251):
    verify_download_integrity short-circuits to True with an info log, never
    raises, and ignores any catalog pin (tags are mutable upstream)."""
    caplog.set_level(logging.INFO, logger="installer.download_verify")
    result = verify_download_integrity("ollama", "gemma3:4b", tmp_path)
    assert result is True
    assert any(
        "content-addressed pull" in rec.getMessage() for rec in caplog.records
    )


def test_verify_ollama_ignores_any_catalog_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if a stale digest lingers in MODEL_WEIGHT_SHA256, Ollama is never
    compared against it — no false DownloadIntegrityError on a mutable tag."""
    monkeypatch.setitem(
        __import__("installer.installer_catalog_data", fromlist=["MODEL_WEIGHT_SHA256"]).MODEL_WEIGHT_SHA256,
        ("ollama", "gemma3:4b"),
        _OTHER_HEX,  # a digest that would mismatch reality, were it ever read
    )
    # Must not raise; short-circuits to True regardless of the pin.
    assert verify_download_integrity("ollama", "gemma3:4b", tmp_path) is True


def test_verify_ollama_never_runs_subprocess(tmp_path: Path) -> None:
    """The dead `ollama show --json` path is gone — verify must not shell out."""
    with patch("subprocess.run") as run:
        result = verify_download_integrity("ollama", "gemma3:4b", tmp_path)
    assert result is True
    run.assert_not_called()


def test_download_verify_has_no_ollama_show_machinery() -> None:
    """Import-level guard: the dead `ollama show --json` code is fully removed
    (B251). A future re-introduction of get_ollama_digest / subprocess / shutil
    in this module must fail this test, not silently revive the no-op verify."""
    import installer.download_verify as dv
    assert not hasattr(dv, "get_ollama_digest")
    assert not hasattr(dv, "_run_ollama_show")
    assert not hasattr(dv, "_parse_ollama_digest")
    assert "subprocess" not in vars(dv)
    assert "shutil" not in vars(dv)


# ════════════════════════════════════════════════════════════════════════
# Invalid engine
# ════════════════════════════════════════════════════════════════════════


def test_verify_unknown_engine_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        verify_download_integrity("mlx-vlm", "x", tmp_path)  # type: ignore[arg-type]


# ════════════════════════════════════════════════════════════════════════
# DownloadIntegrityError carries context
# ════════════════════════════════════════════════════════════════════════


def test_download_integrity_error_carries_artifact() -> None:
    cause = RuntimeError("boom")
    err = DownloadIntegrityError("gemma3:4b", "msg", cause=cause)
    assert err.artifact == "gemma3:4b"
    assert err.cause is cause
    assert str(err) == "msg"


# ════════════════════════════════════════════════════════════════════════
# Smoke: the whole catalog is still consumable by verify_download_integrity
# ════════════════════════════════════════════════════════════════════════


def test_verify_download_integrity_accepts_every_catalog_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every (engine, model_id) from the catalog is dispatched without raising.
    Pins are forced to None so only the dispatch path is exercised with stub
    files: MLX/GGUF → unpinned False; Ollama → content-addressed True (B251)."""
    from installer.installer_catalog_data import iter_catalog_model_ids
    from installer import installer_catalog_data
    # Force all pins to None so stub files don't trigger hash mismatch
    monkeypatch.setattr(
        installer_catalog_data, "MODEL_WEIGHT_SHA256",
        {k: None for k in installer_catalog_data.MODEL_WEIGHT_SHA256},
    )
    # Also clear tier-2 provider pins (ADR B046b) so the MLX dispatch path stays
    # "unpinned → False" rather than entering MLX per-file verification.
    monkeypatch.setattr(
        installer_catalog_data, "_load_provider_pins",
        lambda: {"mlx_file_hashes": {}},
    )
    file_target = tmp_path / "f.gguf"
    file_target.write_bytes(b"x")
    dir_target = tmp_path / "snap"
    dir_target.mkdir()
    (dir_target / "config.json").write_bytes(b"{}")

    for engine, model_id in iter_catalog_model_ids():
        target: Any
        if engine == "gguf":
            target = file_target
        elif engine == "mlx":
            target = dir_target
        else:
            target = tmp_path
        result = verify_download_integrity(engine, model_id, target)
        # ADR B251: Ollama is content-addressed → True; MLX/GGUF unpinned → False.
        expected = engine == "ollama"
        assert result is expected, (engine, model_id)
