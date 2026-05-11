"""Tests for plugins/web_ui_module/messages.py — coverage gaps."""
from unittest.mock import MagicMock


class TestWebUIMessages:
    def test_fallback_messages_not_empty(self):
        from plugins.web_ui_module.messages import FALLBACK_MESSAGES
        assert len(FALLBACK_MESSAGES) > 5

    def test_get_message_without_i18n(self):
        from plugins.web_ui_module.messages import get_message
        result = get_message(None, "web_ui.error.generic")
        assert isinstance(result, str)

    def test_get_message_unknown_key(self):
        from plugins.web_ui_module.messages import get_message
        result = get_message(None, "nonexistent.key.xyz")
        assert result == "nonexistent.key.xyz"

    def test_get_message_with_i18n(self):
        from plugins.web_ui_module.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated"
        result = get_message(mock_i18n, "web_ui.some.key")
        assert result == "Translated"

    def test_get_message_i18n_returns_key_fallback(self):
        from plugins.web_ui_module.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "web_ui.some.key"
        result = get_message(mock_i18n, "web_ui.some.key")
        assert isinstance(result, str)
