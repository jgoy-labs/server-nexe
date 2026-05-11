"""
Tests for personality/loading/messages.py
Covers uncovered lines: 105-108
"""
from unittest.mock import MagicMock
from personality.loading.messages import get_message, FALLBACK_MESSAGES


class TestGetMessage:
    """Tests for get_message function (lines 105-108)"""

    def test_with_i18n_returns_translation(self):
        """Line 106: i18n is provided, return i18n.t() result"""
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated text"
        result = get_message(mock_i18n, 'loading.starting', module="test")
        mock_i18n.t.assert_called_once_with('loading.starting', module="test")
        assert result == "Translated text"

    def test_without_i18n_returns_fallback(self):
        """Line 108: i18n is None, return fallback"""
        result = get_message(None, 'loading.starting')
        assert result == FALLBACK_MESSAGES['loading.starting']

    def test_without_i18n_unknown_key_returns_key(self):
        """Line 108: i18n is None, unknown key returns key itself"""
        result = get_message(None, 'nonexistent.key')
        assert result == 'nonexistent.key'

    def test_with_i18n_none_value_uses_fallback(self):
        """Line 105: i18n is falsy (None)"""
        result = get_message(None, 'loading.success')
        assert result == FALLBACK_MESSAGES['loading.success']
