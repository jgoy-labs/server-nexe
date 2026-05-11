"""Tests for plugins/web_ui_module/core/compactor.py — coverage gaps."""
from unittest.mock import MagicMock, patch


class TestCompactorHelpers:
    def test_clean_for_compact(self):
        from plugins.web_ui_module.core.compactor import _clean_for_compact
        result = _clean_for_compact("<think>inner thought</think>visible text")
        assert "visible text" in result

    def test_clean_for_compact_no_tags(self):
        from plugins.web_ui_module.core.compactor import _clean_for_compact
        result = _clean_for_compact("plain text")
        assert result == "plain text"

    def test_is_ollama_engine(self):
        from plugins.web_ui_module.core.compactor import _is_ollama_engine
        mock_engine = MagicMock()
        mock_engine.__class__.__name__ = "OllamaModule"
        assert _is_ollama_engine(mock_engine) is True

    def test_is_not_ollama_engine(self):
        from plugins.web_ui_module.core.compactor import _is_ollama_engine
        mock_engine = MagicMock()
        mock_engine.__class__.__name__ = "MLXModule"
        assert _is_ollama_engine(mock_engine) is False
