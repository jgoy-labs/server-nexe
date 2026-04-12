"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/tests/test_simple_embedder.py
Description: Tests per memory/embeddings/simple_embedder.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def clear_instances():
    """Netejar singleton instances entre tests."""
    from memory.embeddings.simple_embedder import SimpleEmbedder
    SimpleEmbedder._instances.clear()
    yield
    SimpleEmbedder._instances.clear()


class TestSimpleEmbedderInit:

    def test_creates_instance(self):
        from memory.embeddings.simple_embedder import SimpleEmbedder

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([[0.1] * 768])

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            embedder = SimpleEmbedder("test-model")

        assert embedder.model_name == "test-model"
        assert embedder._initialized is True

    def test_singleton_same_model(self):
        """Mateixa clau → mateixa instància."""
        from memory.embeddings.simple_embedder import SimpleEmbedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            e1 = SimpleEmbedder("model-abc")
            e2 = SimpleEmbedder("model-abc")

        assert e1 is e2

    def test_different_models_different_instances(self):
        """Models diferentes → instàncies diferents."""
        from memory.embeddings.simple_embedder import SimpleEmbedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            e1 = SimpleEmbedder("model-1")
            SimpleEmbedder._instances.pop("model-1")  # Clear first
            e2 = SimpleEmbedder("model-2")

        assert e1 is not e2

    def test_fallback_when_no_local_cache(self):
        """Si no hi ha cache local, llança RuntimeError (offline-only mode)."""
        from memory.embeddings.simple_embedder import SimpleEmbedder

        with patch("memory.embeddings.simple_embedder.TextEmbedding", side_effect=OSError("Not cached")):
            with pytest.raises(RuntimeError, match="not available locally"):
                SimpleEmbedder("test-model-nocache", device="cpu")


class TestSimpleEmbedderEncode:

    def _make_embedder(self, dim=768):
        from memory.embeddings.simple_embedder import SimpleEmbedder
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1] * dim)])

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            return SimpleEmbedder("test-model"), mock_model

    def test_encode_returns_list(self):
        embedder, mock = self._make_embedder()
        mock.embed.return_value = iter([np.array([0.1] * 768)])
        result = embedder.encode("hello world")
        assert isinstance(result, list)

    def test_encode_has_correct_dimension(self):
        embedder, mock = self._make_embedder(dim=768)
        mock.embed.return_value = iter([np.array([0.1] * 768)])
        result = embedder.encode("test")
        assert len(result) == 768

    def test_encode_converts_to_list_of_floats(self):
        embedder, mock = self._make_embedder()
        mock.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        result = embedder.encode("test")
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_encode_normalize_false(self):
        embedder, mock = self._make_embedder()
        mock.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        result = embedder.encode("test", normalize=False)
        assert isinstance(result, list)

    def test_encode_normalized_has_unit_norm(self):
        embedder, mock = self._make_embedder()
        mock.embed.return_value = iter([np.array([3.0, 4.0])])
        result = embedder.encode("test", normalize=True)
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-5


class TestSimpleEmbedderEncodeBatch:

    def _make_embedder(self, dim=768):
        from memory.embeddings.simple_embedder import SimpleEmbedder
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1] * dim), np.array([0.2] * dim)])

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            return SimpleEmbedder("test-model-batch"), mock_model

    def test_encode_batch_returns_list_of_lists(self):
        embedder, mock = self._make_embedder()
        mock.embed.return_value = iter([np.array([0.1] * 768), np.array([0.2] * 768)])
        result = embedder.encode_batch(["text1", "text2"])
        assert isinstance(result, list)
        assert isinstance(result[0], list)

    def test_encode_batch_normalize_false(self):
        embedder, mock = self._make_embedder()
        mock.embed.return_value = iter([np.array([0.1, 0.2]), np.array([0.3, 0.4])])
        result = embedder.encode_batch(["text1", "text2"], normalize=False)
        assert isinstance(result, list)

    def test_encode_batch_passes_batch_size(self):
        embedder, mock = self._make_embedder()
        mock.embed.return_value = iter([np.array([0.1] * 768)])
        embedder.encode_batch(["text1"], batch_size=16)
        call_kwargs = mock.embed.call_args[1]
        assert call_kwargs["batch_size"] == 16


class TestSimpleEmbedderDimensions:

    def test_dimensions_returns_768(self):
        from memory.embeddings.simple_embedder import SimpleEmbedder
        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            embedder = SimpleEmbedder("model-768")

        assert embedder.dimensions == 768


class TestGetEmbedder:

    def test_get_embedder_returns_instance(self):
        from memory.embeddings.simple_embedder import get_embedder, SimpleEmbedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            embedder = get_embedder("test-get-model")

        assert isinstance(embedder, SimpleEmbedder)

    def test_get_embedder_with_device(self):
        from memory.embeddings.simple_embedder import get_embedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.TextEmbedding", return_value=mock_model):
            embedder = get_embedder("test-device-model", device="mps")

        assert embedder.device == "mps"
