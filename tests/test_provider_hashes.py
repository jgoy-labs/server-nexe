"""
────────────────────────────────────
Server Nexe
Location: tests/test_provider_hashes.py
Description: Unit tests for installer.provider_hashes — fetching
             provider-published checksums (HF LFS sha256 per file) over the
             metadata API only.

             ADR B046b. All network is mocked: no HF download — stays in the
             fast suite. Ollama is NOT pinned here (ADR B251: content-addressed
             pull), so there is no Ollama coverage in this module.
────────────────────────────────────
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from installer import provider_hashes


# ── helpers ────────────────────────────────────────────────────────────
def _sibling(rfilename: str, sha256: str | None):
    """Fake a huggingface_hub RepoSibling: LFS files carry lfs.sha256."""
    lfs = SimpleNamespace(sha256=sha256) if sha256 is not None else None
    return SimpleNamespace(rfilename=rfilename, size=1, blob_id="x", lfs=lfs)


# ═══════════════════════════════════════════════════════════════════════
# Hugging Face
# ═══════════════════════════════════════════════════════════════════════
def test_hf_returns_only_lfs_files():
    """LFS files are pinned; non-LFS (config/tokenizer, lfs=None) are skipped."""
    info = SimpleNamespace(siblings=[
        _sibling("model-00001-of-00002.safetensors", "a" * 64),
        _sibling("model-00002-of-00002.safetensors", "b" * 64),
        _sibling("config.json", None),         # non-LFS → skipped
        _sibling("tokenizer.json", None),       # non-LFS → skipped
    ])
    fake_api = MagicMock()
    fake_api.model_info.return_value = info
    with patch("huggingface_hub.HfApi", return_value=fake_api):
        out = provider_hashes.fetch_hf_lfs_hashes("mlx-community/Foo-4bit")
    assert out == {
        "model-00001-of-00002.safetensors": "a" * 64,
        "model-00002-of-00002.safetensors": "b" * 64,
    }
    fake_api.model_info.assert_called_once()
    # metadata-only: files_metadata must be requested
    assert fake_api.model_info.call_args.kwargs.get("files_metadata") is True


def test_hf_network_error_returns_empty(caplog):
    """A failed metadata fetch degrades to {} + WARNING, never raises."""
    fake_api = MagicMock()
    fake_api.model_info.side_effect = RuntimeError("429 rate limit")
    with patch("huggingface_hub.HfApi", return_value=fake_api):
        with caplog.at_level(logging.WARNING):
            out = provider_hashes.fetch_hf_lfs_hashes("mlx-community/Foo-4bit")
    assert out == {}
    assert any("could not fetch HF metadata" in r.message for r in caplog.records)


def test_hf_repo_without_lfs_returns_empty(caplog):
    """A repo exposing no LFS sha256 stays unpinned with a WARNING."""
    info = SimpleNamespace(siblings=[_sibling("config.json", None)])
    fake_api = MagicMock()
    fake_api.model_info.return_value = info
    with patch("huggingface_hub.HfApi", return_value=fake_api):
        with caplog.at_level(logging.WARNING):
            out = provider_hashes.fetch_hf_lfs_hashes("some/repo")
    assert out == {}
    assert any("no LFS sha256" in r.message for r in caplog.records)


# ═══════════════════════════════════════════════════════════════════════
# bootstrap_catalog_pins — Ollama is never pinned (ADR B251)
# ═══════════════════════════════════════════════════════════════════════
def test_bootstrap_skips_ollama(monkeypatch):
    """ADR B251: bootstrap never fetches/stores an Ollama pin — every Ollama
    artefact lands in `skipped`, and the provider-pins schema has no
    `ollama_digests` key."""
    from installer import bootstrap_catalog_pins as bcp

    # No network: MLX metadata fetch returns empty so the run stays offline.
    monkeypatch.setattr(bcp, "fetch_hf_lfs_hashes", lambda *a, **k: {})
    summary = bcp.bootstrap(dry_run=True)

    assert any(s.startswith("ollama:") for s in summary["skipped"])
    assert all(not p.startswith("ollama:") for p in summary["pinned"])
    assert "ollama_digests" not in bcp._load()
