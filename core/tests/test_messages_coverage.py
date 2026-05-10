"""Tests for core/messages.py — coverage gaps."""
from unittest.mock import MagicMock


class TestGetMessage:
    def test_without_i18n_returns_fallback(self):
        from core.messages import get_message
        result = get_message(None, "core.bootstrap.invalid_ip")
        assert result == "Invalid IP address"

    def test_unknown_key_returns_key(self):
        from core.messages import get_message
        result = get_message(None, "nonexistent.key")
        assert result == "nonexistent.key"

    def test_with_format_kwargs(self):
        from core.messages import get_message
        result = get_message(None, "core.ollama.http_error", status=500)
        assert "500" in result

    def test_with_i18n_found(self):
        from core.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated message"
        result = get_message(mock_i18n, "some.key")
        assert result == "Translated message"

    def test_with_i18n_returns_key_fallback(self):
        from core.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "some.key"
        result = get_message(mock_i18n, "some.key")
        assert result == "some.key"

    def test_with_i18n_exception(self):
        from core.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = Exception("i18n error")
        result = get_message(mock_i18n, "core.bootstrap.invalid_ip")
        assert result == "Invalid IP address"

    def test_format_key_error_returns_template(self):
        from core.messages import get_message
        result = get_message(None, "core.ollama.http_error")
        assert "status" in result or "http_error" in result.lower() or "{" in result
