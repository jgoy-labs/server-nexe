"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_sanitize_safetensors_index.py
Description: Regression guards for _sanitize_safetensors_index, the helper
             added on 2026-05-13 after empirically discovering that the
             upstream mlx-community/gemma-3-4b-it-4bit HuggingFace repo
             ships a model.safetensors.index.json declaring two shards
             (model-00001-of-00002.safetensors + model-00002-of-00002.safetensors)
             that do not exist in the repo at all — only a single
             model.safetensors is present. mlx_lm.load then tries to open
             the declared shards and raises FileNotFoundError.

  Contract:
    * If a model dir has a model.safetensors.index.json whose weight_map
      points to shards that do not exist on disk, rename it to .stale
      (preserving the original for inspection). mlx_lm then falls back
      to loading the single model.safetensors.
    * If the index is valid (all declared shards exist), leave it alone.
    * If no index is present, no-op.
    * Idempotent: re-running on a sanitized dir is a no-op.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json

import pytest

from plugins.mlx_module.core.chat import _sanitize_safetensors_index


def _write_index(model_dir, weight_map):
    idx_path = model_dir / "model.safetensors.index.json"
    idx_path.write_text(json.dumps({"weight_map": weight_map}))
    return idx_path


class TestStaleIndexDetected:
    """Index declaring missing shards must be renamed to .stale."""

    def test_stale_multi_shard_index_is_renamed(self, tmp_path):
        """The exact gemma-3-4b-it-4bit upstream bug pattern."""
        (tmp_path / "model.safetensors").write_bytes(b"\x00")
        _write_index(tmp_path, {
            "layer1": "model-00001-of-00002.safetensors",
            "layer2": "model-00002-of-00002.safetensors",
        })

        sanitized = _sanitize_safetensors_index(str(tmp_path))

        assert sanitized is True
        assert not (tmp_path / "model.safetensors.index.json").exists()
        assert (tmp_path / "model.safetensors.index.json.stale").is_file()

    def test_stale_index_preserves_original_content(self, tmp_path):
        """The .stale rename keeps the original JSON intact for inspection."""
        original = {"weight_map": {"x": "missing.safetensors"}}
        idx = tmp_path / "model.safetensors.index.json"
        idx.write_text(json.dumps(original))

        _sanitize_safetensors_index(str(tmp_path))

        stale = tmp_path / "model.safetensors.index.json.stale"
        assert json.loads(stale.read_text()) == original


class TestValidIndexLeftAlone:
    """A valid index (all shards exist) must NOT be touched."""

    def test_valid_single_shard_index_is_preserved(self, tmp_path):
        (tmp_path / "model.safetensors").write_bytes(b"\x00")
        _write_index(tmp_path, {"l1": "model.safetensors"})

        sanitized = _sanitize_safetensors_index(str(tmp_path))

        assert sanitized is False
        assert (tmp_path / "model.safetensors.index.json").is_file()

    def test_valid_multi_shard_index_is_preserved(self, tmp_path):
        for n in (1, 2):
            (tmp_path / f"model-0000{n}-of-00002.safetensors").write_bytes(b"\x00")
        _write_index(tmp_path, {
            "l1": "model-00001-of-00002.safetensors",
            "l2": "model-00002-of-00002.safetensors",
        })

        sanitized = _sanitize_safetensors_index(str(tmp_path))

        assert sanitized is False
        assert (tmp_path / "model.safetensors.index.json").is_file()


class TestNoIndexOrUnreadable:
    """Edge cases where there's nothing to sanitize."""

    def test_no_index_returns_false(self, tmp_path):
        (tmp_path / "model.safetensors").write_bytes(b"\x00")
        assert _sanitize_safetensors_index(str(tmp_path)) is False

    def test_empty_path_returns_false(self, tmp_path):
        assert _sanitize_safetensors_index("") is False

    def test_malformed_json_is_left_alone(self, tmp_path, caplog):
        """A garbled index should NOT be renamed — let mlx_lm surface its own
        error. We only act on the specific 'declares missing shards' pattern."""
        (tmp_path / "model.safetensors.index.json").write_text("{not json")

        with caplog.at_level("WARNING"):
            sanitized = _sanitize_safetensors_index(str(tmp_path))

        assert sanitized is False
        assert (tmp_path / "model.safetensors.index.json").is_file()
        assert any("could not parse" in r.getMessage() for r in caplog.records)


class TestIdempotent:
    """Running the sanitizer a second time after a fix is a no-op."""

    def test_second_run_after_rename_is_noop(self, tmp_path):
        (tmp_path / "model.safetensors").write_bytes(b"\x00")
        _write_index(tmp_path, {"l1": "ghost.safetensors"})

        first = _sanitize_safetensors_index(str(tmp_path))
        second = _sanitize_safetensors_index(str(tmp_path))

        assert first is True
        assert second is False
        # The .stale survives both runs, and the active index stays gone.
        assert (tmp_path / "model.safetensors.index.json.stale").is_file()
        assert not (tmp_path / "model.safetensors.index.json").exists()
