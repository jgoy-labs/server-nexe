"""Tests for plugins/ollama_module/core/errors.py — coverage gaps."""
import pytest
from unittest.mock import MagicMock


class TestOllamaSemanticError:
    def test_with_status_code(self):
        from plugins.ollama_module.core.errors import OllamaSemanticError
        err = OllamaSemanticError("test error", status_code=400)
        assert err.status_code == 400
        assert "test error" in str(err)

    def test_raises(self):
        from plugins.ollama_module.core.errors import OllamaSemanticError
        with pytest.raises(OllamaSemanticError):
            raise OllamaSemanticError("bad request", 400)


class TestModelNotFoundError:
    def test_inherits_semantic(self):
        from plugins.ollama_module.core.errors import ModelNotFoundError, OllamaSemanticError
        assert issubclass(ModelNotFoundError, OllamaSemanticError)

    def test_default_message(self):
        from plugins.ollama_module.core.errors import ModelNotFoundError
        err = ModelNotFoundError("llama3.1:70b")
        assert err.status_code == 404
        assert "llama3.1:70b" in str(err)
        assert err.model_name == "llama3.1:70b"

    def test_custom_message(self):
        from plugins.ollama_module.core.errors import ModelNotFoundError
        err = ModelNotFoundError("phi3", message="Custom msg")
        assert "Custom msg" in str(err)


class TestIsSemanticHttpError:
    def test_semantic_error_instance(self):
        from plugins.ollama_module.core.errors import is_semantic_http_error, OllamaSemanticError
        err = OllamaSemanticError("bad", 400)
        assert is_semantic_http_error(err, MagicMock()) is True

    def test_httpx_none_returns_false(self):
        from plugins.ollama_module.core.errors import is_semantic_http_error
        assert is_semantic_http_error(Exception("test"), None) is False

    def test_non_httpx_exception(self):
        from plugins.ollama_module.core.errors import is_semantic_http_error
        import httpx
        assert is_semantic_http_error(ValueError("oops"), httpx) is False
