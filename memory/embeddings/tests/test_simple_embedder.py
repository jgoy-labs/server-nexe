"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: memory/embeddings/tests/test_simple_embedder.py
Description: Tests per memory/embeddings/simple_embedder.py.

www.jgoy.net
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
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            embedder = SimpleEmbedder("test-model")

        assert embedder.model_name == "test-model"
        assert embedder._initialized is True

    def test_singleton_same_model(self):
        """Mateixa clau → mateixa instància."""
        from memory.embeddings.simple_embedder import SimpleEmbedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            e1 = SimpleEmbedder("model-abc")
            e2 = SimpleEmbedder("model-abc")

        assert e1 is e2

    def test_different_models_different_instances(self):
        """Models diferentes → instàncies diferents."""
        from memory.embeddings.simple_embedder import SimpleEmbedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            e1 = SimpleEmbedder("model-1")
            SimpleEmbedder._instances.pop("model-1")  # Clear first
            e2 = SimpleEmbedder("model-2")

        assert e1 is not e2

    def test_fallback_when_no_local_cache(self):
        """Si no hi ha cache local, fa download."""
        from memory.embeddings.simple_embedder import SimpleEmbedder

        mock_model = MagicMock()
        call_count = [0]

        def mock_st(name, device=None, local_files_only=False):
            if local_files_only:
                raise OSError("Not cached")
            call_count[0] += 1
            return mock_model

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", side_effect=mock_st):
            embedder = SimpleEmbedder("test-model", device="cpu")

        assert call_count[0] == 1  # Fallback called
        assert embedder._initialized is True


class TestSimpleEmbedderEncode:

    def _make_embedder(self, dim=384):
        from memory.embeddings.simple_embedder import SimpleEmbedder
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1] * dim)
        mock_model.get_sentence_embedding_dimension.return_value = dim

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            return SimpleEmbedder("test-model"), mock_model

    def test_encode_returns_list(self):
        embedder, _ = self._make_embedder()
        result = embedder.encode("hello world")
        assert isinstance(result, list)

    def test_encode_has_correct_dimension(self):
        embedder, _ = self._make_embedder(dim=384)
        result = embedder.encode("test")
        assert len(result) == 384

    def test_encode_converts_ndarray_to_list(self):
        embedder, mock_model = self._make_embedder()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
        result = embedder.encode("test")
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_encode_non_ndarray_returned_directly(self):
        embedder, mock_model = self._make_embedder()
        # Return list directly (not ndarray)
        mock_model.encode.return_value = [0.1, 0.2, 0.3]
        result = embedder.encode("test")
        assert isinstance(result, list)

    def test_encode_passes_normalize_flag(self):
        embedder, mock_model = self._make_embedder()
        embedder.encode("test", normalize=False)
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs["normalize_embeddings"] is False


class TestSimpleEmbedderEncodeBatch:

    def _make_embedder(self, dim=384):
        from memory.embeddings.simple_embedder import SimpleEmbedder
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1] * dim, [0.2] * dim])
        mock_model.get_sentence_embedding_dimension.return_value = dim

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            return SimpleEmbedder("test-model-batch"), mock_model

    def test_encode_batch_returns_list_of_lists(self):
        embedder, _ = self._make_embedder()
        result = embedder.encode_batch(["text1", "text2"])
        assert isinstance(result, list)
        assert isinstance(result[0], list)

    def test_encode_batch_non_ndarray(self):
        embedder, mock_model = self._make_embedder()
        mock_model.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]
        result = embedder.encode_batch(["text1", "text2"])
        assert isinstance(result, list)

    def test_encode_batch_passes_batch_size(self):
        embedder, mock_model = self._make_embedder()
        embedder.encode_batch(["text1"], batch_size=16)
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs["batch_size"] == 16


class TestSimpleEmbedderDimensions:

    def test_dimensions_returns_int(self):
        from memory.embeddings.simple_embedder import SimpleEmbedder
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 768

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            embedder = SimpleEmbedder("model-768")

        assert embedder.dimensions == 768


class TestGetEmbedder:

    def test_get_embedder_returns_instance(self):
        from memory.embeddings.simple_embedder import get_embedder, SimpleEmbedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            embedder = get_embedder("test-get-model")

        assert isinstance(embedder, SimpleEmbedder)

    def test_get_embedder_with_device(self):
        from memory.embeddings.simple_embedder import get_embedder

        mock_model = MagicMock()

        with patch("memory.embeddings.simple_embedder.SentenceTransformer", return_value=mock_model):
            embedder = get_embedder("test-device-model", device="mps")

        assert embedder.device == "mps"
