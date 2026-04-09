"""
Tests for plugins/web_ui_module/messages.py::get_i18n FastAPI dependency.

Codex P1 i18n bypass fix — Q3:
Web UI routes were calling get_message(None, ...) which forced fallback
to English regardless of the user's language. The fix injects i18n via
Depends(get_i18n) in every Web UI route handler.

Cirurgia post-BUS Q3.
"""

from unittest.mock import MagicMock

from plugins.web_ui_module.messages import get_message, get_i18n, FALLBACK_MESSAGES


def _request_with_i18n(i18n_obj):
    req = MagicMock()
    req.app.state.i18n = i18n_obj
    return req


def _request_without_i18n():
    req = MagicMock()
    req.app.state = MagicMock(spec=[])  # no i18n attribute
    return req


class TestGetI18nDependency:
    def test_returns_i18n_from_app_state(self):
        """When app.state.i18n exists, get_i18n returns it."""
        mock_i18n = MagicMock()
        req = _request_with_i18n(mock_i18n)
        result = get_i18n(req)
        assert result is mock_i18n

    def test_returns_none_when_no_i18n_attribute(self):
        """When app.state has no i18n, get_i18n returns None (test/dev fallback)."""
        req = _request_without_i18n()
        result = get_i18n(req)
        assert result is None

    def test_request_type_hint_present(self):
        """get_i18n must have `request: Request` type hint, otherwise FastAPI
        treats it as a query param and returns 422 Unprocessable Entity."""
        from fastapi import Request
        annotations = get_i18n.__annotations__
        assert "request" in annotations
        assert annotations["request"] is Request


class TestI18nIntegratedWithGetMessage:
    """Integration: get_message must use the i18n returned by get_i18n."""

    def test_get_message_translates_via_i18n_from_state(self):
        """When the dependency returns a real i18n, get_message must use it."""
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Clau API no vàlida o no proporcionada"
        req = _request_with_i18n(mock_i18n)

        i18n = get_i18n(req)
        result = get_message(i18n, "webui.auth.invalid_key")

        assert result == "Clau API no vàlida o no proporcionada"
        mock_i18n.t.assert_called_once_with("webui.auth.invalid_key")

    def test_get_message_falls_back_when_no_i18n(self):
        """When the dependency returns None, get_message uses fallback dict."""
        req = _request_without_i18n()

        i18n = get_i18n(req)
        result = get_message(i18n, "webui.auth.invalid_key")

        # Falls back to English fallback
        assert result == FALLBACK_MESSAGES["webui.auth.invalid_key"]

    def test_anti_regression_no_i18n_bypass(self):
        """Anti-regression: get_message(get_i18n(request), ...) must NEVER
        equal get_message(None, ...) when request has a real i18n.

        Pre-fix Web UI routes called get_message(None, ...) directly,
        bypassing translation. This test ensures the dependency wiring works.
        """
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "TRANSLATED"
        req = _request_with_i18n(mock_i18n)

        # Simulating the Q3 fix path
        result_with_dependency = get_message(get_i18n(req), "webui.chat.message_required")
        # Simulating the pre-fix bypass path
        result_with_bypass = get_message(None, "webui.chat.message_required")

        assert result_with_dependency == "TRANSLATED"
        assert result_with_bypass == FALLBACK_MESSAGES["webui.chat.message_required"]
        assert result_with_dependency != result_with_bypass
