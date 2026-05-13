"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/embeddings/test_paths.py
Description: Tests for memory/embeddings/paths.py — fastembed cache directory SSOT.

Covers the universal contract introduced 2026-05-13:
  All `TextEmbedding(...)` call-sites must pass a `cache_dir=` argument
  resolved via `default_fastembed_cache_dir()`. The helper resolves
  FASTEMBED_CACHE_DIR > ~/.cache/fastembed (cross-platform fastembed
  convention, also where the DMG installer seeds the bundled model).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDefaultFastembedCacheDir:
    """Resolution of the canonical fastembed cache directory."""

    def test_default_falls_back_to_home_cache(self, monkeypatch):
        """Without FASTEMBED_CACHE_DIR exported, returns ~/.cache/fastembed."""
        monkeypatch.delenv("FASTEMBED_CACHE_DIR", raising=False)
        from memory.embeddings.paths import default_fastembed_cache_dir
        assert default_fastembed_cache_dir() == Path.home() / ".cache" / "fastembed"

    def test_env_override_is_respected(self, monkeypatch, tmp_path):
        """FASTEMBED_CACHE_DIR env var wins over the default."""
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path))
        from memory.embeddings.paths import default_fastembed_cache_dir
        assert default_fastembed_cache_dir() == tmp_path

    def test_env_override_expands_tilde(self, monkeypatch):
        """A leading ~ in FASTEMBED_CACHE_DIR is expanded to $HOME."""
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", "~/custom/fastembed")
        from memory.embeddings.paths import default_fastembed_cache_dir
        result = default_fastembed_cache_dir()
        assert result == Path.home() / "custom" / "fastembed"

    def test_returns_path_object(self, monkeypatch, tmp_path):
        """The return value is always a `Path`, not a str."""
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path))
        from memory.embeddings.paths import default_fastembed_cache_dir
        assert isinstance(default_fastembed_cache_dir(), Path)


class TestInstallerWrapperDelegates:
    """The installer's _default_fastembed_cache_dir must delegate to the SSOT."""

    def test_installer_helper_calls_module(self, monkeypatch, tmp_path):
        """installer/_default_fastembed_cache_dir returns the same path."""
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path))
        from installer.installer_setup_env import _default_fastembed_cache_dir
        from memory.embeddings.paths import default_fastembed_cache_dir as canonical
        assert _default_fastembed_cache_dir() == canonical()


class TestCallSitesPassCacheDir:
    """Runtime call-sites of TextEmbedding(...) must pass cache_dir."""

    @pytest.fixture(autouse=True)
    def clear_simple_embedder(self):
        from memory.embeddings.simple_embedder import SimpleEmbedder
        SimpleEmbedder._instances.clear()
        yield
        SimpleEmbedder._instances.clear()

    def test_simple_embedder_passes_cache_dir(self, monkeypatch, tmp_path):
        """SimpleEmbedder.__init__ forwards cache_dir to TextEmbedding."""
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path))
        from memory.embeddings.simple_embedder import SimpleEmbedder

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([[0.1] * 768])

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model) as fake:
            SimpleEmbedder("test-model")

        fake.assert_called_once()
        kwargs = fake.call_args.kwargs
        assert kwargs.get("cache_dir") == str(tmp_path)

    def test_async_encoder_passes_cache_dir(self, monkeypatch, tmp_path):
        """AsyncEmbedder._load_model forwards cache_dir to TextEmbedding."""
        monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(tmp_path))
        from memory.embeddings.core.async_encoder import AsyncEmbedder

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([[0.1] * 768])

        encoder = AsyncEmbedder.__new__(AsyncEmbedder, "test-model")
        encoder.model_name = "test-model"

        with patch("fastembed.TextEmbedding", return_value=mock_model) as fake:
            encoder._load_model()

        fake.assert_called_once()
        kwargs = fake.call_args.kwargs
        assert kwargs.get("cache_dir") == str(tmp_path)
