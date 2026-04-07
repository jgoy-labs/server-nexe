"""
Tests for plugins/web_ui_module/api/routes_auth.py::make_require_ui_auth.

Codex P1 fix: FAIL CLOSED when no admin API key is configured.
Pre-fix the dependency was FAIL OPEN: if NEXE_PRIMARY_API_KEY/NEXE_ADMIN_API_KEY
were unset, all UI routes were accessible without authentication.

Cirurgia post-BUS Q2.1.
"""

from unittest.mock import patch, MagicMock
import pytest
from fastapi import HTTPException

from plugins.web_ui_module.api.routes_auth import make_require_ui_auth


def _mock_request():
    """Build a minimal mock Request with no i18n in app.state."""
    req = MagicMock()
    req.app.state = MagicMock(spec=[])  # no i18n attribute
    return req


@pytest.mark.asyncio
class TestMakeRequireUiAuthFailClosed:
    async def test_no_key_configured_fails_closed_503(self):
        """When no admin API key is set, ANY request must be rejected with 503."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="",
        ):
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(), x_api_key="some_key")
            assert exc_info.value.status_code == 503
            assert "FAIL CLOSED" in exc_info.value.detail or "not configured" in str(exc_info.value.detail).lower()

    async def test_no_key_configured_none_fails_closed_503(self):
        """When get_admin_api_key returns None, also FAIL CLOSED."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(), x_api_key=None)
            assert exc_info.value.status_code == 503

    async def test_no_key_configured_no_header_fails_closed_503(self):
        """When no key configured AND no header, still 503 (not 401)."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="",
        ):
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(), x_api_key=None)
            assert exc_info.value.status_code == 503

    async def test_key_configured_invalid_header_returns_401(self):
        """When key is set, invalid header returns 401 (normal behavior)."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="real_key_123",
        ):
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(), x_api_key="wrong_key")
            assert exc_info.value.status_code == 401

    async def test_key_configured_no_header_returns_401(self):
        """When key is set, missing header returns 401."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="real_key_123",
        ):
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(), x_api_key=None)
            assert exc_info.value.status_code == 401

    async def test_key_configured_valid_header_passes(self):
        """When key is set and header matches, no exception raised."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="real_key_123",
        ):
            # Should not raise
            result = await require(_mock_request(), x_api_key="real_key_123")
            assert result is None  # dependency returns None on success
