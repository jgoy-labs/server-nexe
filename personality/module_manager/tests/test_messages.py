"""
Tests per personality/module_manager/messages.py
Covers uncovered lines: 74-76, 83-85.
"""

import pytest
from unittest.mock import MagicMock, patch
from personality.module_manager.messages import get_message, FALLBACK_MESSAGES


class TestGetMessage:
    def test_i18n_translates_successfully(self):
        """Lines 71-74: i18n translates the key."""
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated message"
        result = get_message(mock_i18n, "init.started")
        assert result == "Translated message"

    def test_i18n_returns_key_uses_fallback(self):
        """Lines 73-74: i18n returns the key -> use fallback."""
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key, **kw: key
        result = get_message(mock_i18n, "init.started")
        assert result == FALLBACK_MESSAGES["init.started"]

    def test_i18n_exception_uses_fallback(self):
        """Lines 75-76: i18n raises exception -> use fallback (with patched logger)."""
        import logging as logging_mod
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = RuntimeError("translation error")
        with patch("personality.module_manager.messages.logging", logging_mod):
            result = get_message(mock_i18n, "init.started")
        assert result == FALLBACK_MESSAGES["init.started"]

    def test_i18n_exception_no_nameerror_after_fix(self, caplog):
        """Anti-regression: verifies that logging is properly imported in messages.py.

        Pre-fix this would raise NameError because logging.debug was called
        without `import logging`. This test does NOT patch logging — it relies
        on the real import being present. Codex P1 / F821 fix.
        """
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = RuntimeError("translation error")
        with caplog.at_level("DEBUG", logger="personality.module_manager.messages"):
            result = get_message(mock_i18n, "init.started")
        assert result == FALLBACK_MESSAGES["init.started"]

    def test_no_i18n_uses_fallback(self):
        """Line 79: no i18n -> direct fallback."""
        result = get_message(None, "init.started")
        assert result == "ModuleManager initialized"

    def test_fallback_with_format_kwargs(self):
        """Lines 81-82: fallback message with kwargs."""
        result = get_message(None, "loading.not_found", module="test_mod")
        assert result == "Module test_mod not found"

    def test_non_string_fallback_converted(self):
        """Line 83: non-string fallback converted to str."""
        result = get_message(None, "manifest.default.enabled")
        assert result == "True"  # FALLBACK_MESSAGES has True (bool)

    def test_format_error_returns_raw(self):
        """Lines 84-85: format error returns raw message."""
        result = get_message(None, "loading.not_found")
        # Missing 'module' kwarg -> KeyError caught
        assert "Module {module} not found" == result

    def test_unknown_key_returns_key(self):
        """Line 79: key not in FALLBACK_MESSAGES -> returns key itself."""
        result = get_message(None, "nonexistent.key")
        assert result == "nonexistent.key"
