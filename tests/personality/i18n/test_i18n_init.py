"""
Tests per personality/i18n/__init__.py
Covers uncovered lines: 43-49 (I18nHelper.t fallback/exception branches).
"""

import pytest
from unittest.mock import patch, MagicMock
from personality.i18n import I18nHelper, get_i18n, _global_i18n_lock
import personality.i18n as i18n_pkg


@pytest.fixture(autouse=True)
def reset_global_i18n():
    """Reset global i18n singleton between tests."""
    i18n_pkg._global_i18n = None
    yield
    i18n_pkg._global_i18n = None


class TestI18nHelper:
    def test_t_success(self):
        """Normal translation succeeds."""
        mock_manager = MagicMock()
        mock_manager.t.return_value = "Translated"
        helper = I18nHelper(mock_manager)
        result = helper.t("key", "fallback")
        assert result == "Translated"

    def test_t_exception_returns_fallback(self):
        """Lines 43-44: exception in manager.t -> fallback."""
        mock_manager = MagicMock()
        mock_manager.t.side_effect = KeyError("missing")
        helper = I18nHelper(mock_manager)
        result = helper.t("key", "My fallback")
        assert result == "My fallback"

    def test_t_exception_with_kwargs_formats_fallback(self):
        """Lines 44-46: fallback with kwargs formatted."""
        mock_manager = MagicMock()
        mock_manager.t.side_effect = RuntimeError("boom")
        helper = I18nHelper(mock_manager)
        result = helper.t("key", "Error: {msg}", msg="test")
        assert result == "Error: test"

    def test_t_exception_fallback_format_error(self):
        """Lines 47-48: fallback format itself fails."""
        mock_manager = MagicMock()
        mock_manager.t.side_effect = RuntimeError("boom")
        helper = I18nHelper(mock_manager)
        result = helper.t("key", "Error: {missing_key}", msg="test")
        assert result == "Error: {missing_key}"

    def test_t_exception_no_fallback_returns_key(self):
        """Line 49: no fallback -> returns key."""
        mock_manager = MagicMock()
        mock_manager.t.side_effect = RuntimeError("boom")
        helper = I18nHelper(mock_manager)
        result = helper.t("my.key")
        assert result == "my.key"

    def test_t_exception_empty_fallback_returns_key(self):
        """Line 49: empty fallback string -> returns key."""
        mock_manager = MagicMock()
        mock_manager.t.side_effect = RuntimeError("boom")
        helper = I18nHelper(mock_manager)
        result = helper.t("my.key", "")
        assert result == "my.key"

    # ── Manager returns the raw key on a miss (its real behaviour: I18nManager.t
    #    returns `key` without raising). The documented fallback must trigger here
    #    too, otherwise raw i18n keys leak into logs (e.g. the security audit log).
    def test_t_uses_fallback_when_manager_returns_raw_key(self):
        mock_manager = MagicMock()
        mock_manager.t.side_effect = lambda key, **kw: key  # real miss behaviour
        helper = I18nHelper(mock_manager)
        result = helper.t(
            "security_logger.auth.failure",
            "Authentication failed: {reason}",
            reason="bad token",
        )
        assert result == "Authentication failed: bad token"  # fail-before: the raw key

    def test_t_uses_fallback_without_kwargs_on_raw_key(self):
        mock_manager = MagicMock()
        mock_manager.t.side_effect = lambda key, **kw: key
        helper = I18nHelper(mock_manager)
        assert helper.t("some.missing.key", "Static fallback") == "Static fallback"

    def test_t_returns_key_on_raw_key_when_no_fallback(self):
        # No fallback provided → preserve existing behaviour (return the key).
        mock_manager = MagicMock()
        mock_manager.t.side_effect = lambda key, **kw: key
        helper = I18nHelper(mock_manager)
        assert helper.t("some.missing.key") == "some.missing.key"

    def test_t_returns_translation_when_resolved_not_fallback(self):
        # Guard: a resolved translation (differs from key) is returned untouched.
        mock_manager = MagicMock()
        mock_manager.t.return_value = "Resolved text"
        helper = I18nHelper(mock_manager)
        assert helper.t("some.key", "ignored fallback") == "Resolved text"


class TestGetI18n:
    def test_get_i18n_returns_helper(self):
        """get_i18n returns I18nHelper instance."""
        helper = get_i18n()
        assert isinstance(helper, I18nHelper)

    def test_get_i18n_singleton(self):
        """get_i18n returns same instance."""
        h1 = get_i18n()
        h2 = get_i18n()
        assert h1 is h2

    def test_get_i18n_thread_safety(self):
        """get_i18n is thread-safe (double-checked locking)."""
        import threading
        results = []

        def get():
            results.append(get_i18n())

        threads = [threading.Thread(target=get) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be the same instance
        assert all(r is results[0] for r in results)
