"""F2.2 part 2: tests for env-aware path resolvers.

Validates that the path helpers (core/paths/helpers.py + core/crypto/keys.py)
respect Tauri-injected env vars in sidecar mode:
- NEXE_DATA_DIR    → get_data_dir()
- NEXE_CACHE_DIR   → get_cache_dir()
- NEXE_SIDECAR_DIR → _resolve_key_file_dir() (master key location, BUG-NC-36)

Without these, the F2.A10 manifestation persisted: sidecar logs showed paths
relative to cwd instead of the Tauri-managed sidecar directory.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.crypto.keys import _resolve_key_file_dir, _resolve_key_file_path
from core.paths.helpers import get_cache_dir, get_data_dir


class TestGetDataDir:
    def test_respects_nexe_data_dir(self, monkeypatch, tmp_path):
        """F2.2 part 2: NEXE_DATA_DIR set → returns Path(NEXE_DATA_DIR)."""
        custom = tmp_path / "custom_data"
        monkeypatch.setenv("NEXE_DATA_DIR", str(custom))
        assert get_data_dir() == custom
        assert custom.exists()  # mkdir parents=True

    def test_falls_back_to_storage_data(self, monkeypatch):
        """No NEXE_DATA_DIR → fallback to project_root/storage/data/ (legacy)."""
        monkeypatch.delenv("NEXE_DATA_DIR", raising=False)
        result = get_data_dir()
        assert "storage" in str(result)
        assert "data" in str(result)

    def test_subdir_appended(self, monkeypatch, tmp_path):
        """Subdir arg works with NEXE_DATA_DIR."""
        custom = tmp_path / "custom_data"
        monkeypatch.setenv("NEXE_DATA_DIR", str(custom))
        result = get_data_dir("subfolder")
        assert result == custom / "subfolder"


class TestGetCacheDir:
    def test_respects_nexe_cache_dir(self, monkeypatch, tmp_path):
        """F2.2 part 2: NEXE_CACHE_DIR set → returns Path(NEXE_CACHE_DIR)."""
        custom = tmp_path / "custom_cache"
        monkeypatch.setenv("NEXE_CACHE_DIR", str(custom))
        assert get_cache_dir() == custom

    def test_falls_back_to_storage_cache(self, monkeypatch):
        """No NEXE_CACHE_DIR → fallback to project_root/storage/cache/."""
        monkeypatch.delenv("NEXE_CACHE_DIR", raising=False)
        result = get_cache_dir()
        assert "storage" in str(result)
        assert "cache" in str(result)

    def test_subdir_appended(self, monkeypatch, tmp_path):
        """Subdir arg works with NEXE_CACHE_DIR."""
        custom = tmp_path / "custom_cache"
        monkeypatch.setenv("NEXE_CACHE_DIR", str(custom))
        result = get_cache_dir("embeddings")
        assert result == custom / "embeddings"


class TestResolveKeyFileDir:
    def test_respects_nexe_sidecar_dir(self, monkeypatch, tmp_path):
        """F2.2 part 2 (BUG-NC-36): NEXE_SIDECAR_DIR set → returns it."""
        custom = tmp_path / "custom_sidecar"
        monkeypatch.setenv("NEXE_SIDECAR_DIR", str(custom))
        assert _resolve_key_file_dir() == custom

    def test_falls_back_to_home_dot_nexe(self, monkeypatch):
        """No NEXE_SIDECAR_DIR → fallback to ~/.nexe (legacy)."""
        monkeypatch.delenv("NEXE_SIDECAR_DIR", raising=False)
        result = _resolve_key_file_dir()
        assert result == Path.home() / ".nexe"


class TestResolveKeyFilePath:
    def test_uses_resolved_dir_with_master_key(self, monkeypatch, tmp_path):
        """F2.2 part 2: master.key file lives in resolved dir."""
        custom = tmp_path / "custom_sidecar"
        monkeypatch.setenv("NEXE_SIDECAR_DIR", str(custom))
        assert _resolve_key_file_path() == custom / "master.key"

    def test_falls_back_to_home_default(self, monkeypatch):
        """Default: ~/.nexe/master.key."""
        monkeypatch.delenv("NEXE_SIDECAR_DIR", raising=False)
        result = _resolve_key_file_path()
        assert result == Path.home() / ".nexe" / "master.key"
