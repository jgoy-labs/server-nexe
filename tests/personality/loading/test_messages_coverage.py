"""Tests for personality/loading/messages.py — coverage gaps."""
from unittest.mock import MagicMock


class TestLoadingMessages:
    def test_fallback_messages_not_empty(self):
        from personality.loading.messages import FALLBACK_MESSAGES
        assert len(FALLBACK_MESSAGES) > 30

    def test_get_message_without_i18n(self):
        from personality.loading.messages import get_message
        result = get_message(None, "loading.starting")
        assert "module" in result or "Carregant" in result

    def test_get_message_unknown_key(self):
        from personality.loading.messages import get_message
        result = get_message(None, "nonexistent.key")
        assert result == "nonexistent.key"

    def test_get_message_with_i18n(self):
        from personality.loading.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated"
        result = get_message(mock_i18n, "loading.starting", module="x")
        assert result == "Translated"

    def test_validation_messages(self):
        from personality.loading.messages import get_message
        result = get_message(None, "validation.instance_missing")
        assert "instància" in result.lower() or "instance" in result.lower()

    def test_loader_pattern_keys(self):
        from personality.loading.messages import FALLBACK_MESSAGES
        assert "loader.patterns.api_module" in FALLBACK_MESSAGES
        assert "loader.init_methods.init" in FALLBACK_MESSAGES
        assert "loader.cleanup_methods.cleanup" in FALLBACK_MESSAGES
