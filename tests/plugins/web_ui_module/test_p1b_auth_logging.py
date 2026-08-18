"""
Tests P1-B — Web UI auth failures must be logged to the security log.

Problem: make_require_ui_auth() was not calling security_logger.log_auth_failure()
on authentication failures. A brute force on /ui/chat was invisible in logs.

Fix: add lazy import + log_auth_failure() same as auth_dependencies.py:185-193.

www.jgoy.net · https://server-nexe.org
"""

from unittest.mock import patch, MagicMock
import pytest
from fastapi import HTTPException

from plugins.security.core.auth_models import ApiKeyConfig, ApiKeyData
from plugins.web_ui_module.api.routes_auth import make_require_ui_auth

_LOAD = "plugins.security.core.auth_dependencies.load_api_keys"
_KEYS = ApiKeyConfig(primary=ApiKeyData(key="real_key"))


def _mock_request(host="1.2.3.4", path="/ui/chat"):
    """Minimal request with client.host and url.path."""
    req = MagicMock()
    req.app.state = MagicMock(spec=[])
    req.client.host = host
    req.url.path = path
    return req


@pytest.mark.asyncio
class TestP1BAuthLogging:
    async def test_invalid_key_logs_auth_failure(self):
        """Invalid key → log_auth_failure() is called on the security logger."""
        require = make_require_ui_auth()
        mock_sec_logger = MagicMock()
        with patch(_LOAD, return_value=_KEYS):
            with patch(
                "plugins.security.security_logger.get_security_logger",
                return_value=mock_sec_logger,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await require(_mock_request(host="1.2.3.4"), x_api_key="wrong_key")
                assert exc_info.value.status_code == 401
                mock_sec_logger.log_auth_failure.assert_called_once()
                kwargs = mock_sec_logger.log_auth_failure.call_args
                # Verify the correct IP was passed
                all_args = str(kwargs)
                assert "1.2.3.4" in all_args

    async def test_no_key_logs_auth_failure(self):
        """Without key (None header) → log_auth_failure() is called."""
        require = make_require_ui_auth()
        mock_sec_logger = MagicMock()
        with patch(_LOAD, return_value=_KEYS):
            with patch(
                "plugins.security.security_logger.get_security_logger",
                return_value=mock_sec_logger,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await require(_mock_request(), x_api_key=None)
                assert exc_info.value.status_code == 401
                mock_sec_logger.log_auth_failure.assert_called_once()

    async def test_valid_key_no_auth_failure_log(self):
        """Valid key → log_auth_failure() must NOT be called."""
        require = make_require_ui_auth()
        mock_sec_logger = MagicMock()
        with patch(_LOAD, return_value=_KEYS):
            with patch(
                "plugins.security.security_logger.get_security_logger",
                return_value=mock_sec_logger,
            ):
                result = await require(_mock_request(), x_api_key="real_key")
                assert result is None
                mock_sec_logger.log_auth_failure.assert_not_called()
