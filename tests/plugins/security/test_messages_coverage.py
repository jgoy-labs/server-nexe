"""
Tests for plugins/security/core/messages.py - targeting uncovered lines.
Lines: 69 (i18n path), 74-75 (format KeyError fallback).
"""

from plugins.security.core.messages import get_message


class TestGetMessage:

    def test_with_i18n_uses_translator(self):
        """Line 69: when i18n is provided, use i18n.t()."""
        mock_i18n = type('MockI18n', (), {
            't': lambda self, key, **kwargs: f"translated:{key}"
        })()
        result = get_message(mock_i18n, "security.auth.missing_key")
        assert result == "translated:security.auth.missing_key"

    def test_without_i18n_uses_fallback(self):
        """Line 71: i18n=None uses FALLBACK_MESSAGES."""
        result = get_message(None, "security.auth.missing_key")
        assert result == "Missing API key"

    def test_with_kwargs_format(self):
        """Line 73: template.format(**kwargs) works."""
        result = get_message(None, "security.validators.file_not_found", filename="test.txt")
        assert "test.txt" in result

    def test_format_key_error_returns_template(self):
        """Lines 74-75: KeyError in format returns unformatted template."""
        result = get_message(None, "security.validators.file_not_found", wrong_param="value")
        # Should return the template string without formatting
        assert "{filename}" in result

    def test_unknown_key_returns_key(self):
        """Line 71: unknown key returns the key itself."""
        result = get_message(None, "unknown.key.here")
        assert result == "unknown.key.here"

    def test_i18n_with_kwargs(self):
        """Line 69: i18n.t receives kwargs."""
        mock_i18n = type('MockI18n', (), {
            't': lambda self, key, **kwargs: f"translated:{key}:{kwargs}"
        })()
        result = get_message(mock_i18n, "security.validators.file_not_found", filename="doc.pdf")
        assert "filename" in result
        assert "doc.pdf" in result
