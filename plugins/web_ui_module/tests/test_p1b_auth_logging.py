"""
Tests P1-B — Auth failures de la Web UI s'han de loggar al security log.

Problema: make_require_ui_auth() no cridava security_logger.log_auth_failure()
en fallades d'autenticació. Un brute force sobre /ui/chat no apareixia als logs.

Fix: afegir import lazy + log_auth_failure() igual que auth_dependencies.py:185-193.

www.jgoy.net · https://server-nexe.org
"""

from unittest.mock import patch, MagicMock
import pytest
from fastapi import HTTPException

from plugins.web_ui_module.api.routes_auth import make_require_ui_auth


def _mock_request(host="1.2.3.4", path="/ui/chat"):
    """Request mínim amb client.host i url.path."""
    req = MagicMock()
    req.app.state = MagicMock(spec=[])
    req.client.host = host
    req.url.path = path
    return req


@pytest.mark.asyncio
class TestP1BAuthLogging:
    async def test_invalid_key_logs_auth_failure(self):
        """Key invàlida → log_auth_failure() es crida al security logger."""
        require = make_require_ui_auth()
        mock_sec_logger = MagicMock()
        with patch("plugins.web_ui_module.api.routes_auth.get_admin_api_key", return_value="real_key"):
            with patch(
                "plugins.security.security_logger.get_security_logger",
                return_value=mock_sec_logger,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await require(_mock_request(host="1.2.3.4"), x_api_key="wrong_key")
                assert exc_info.value.status_code == 401
                mock_sec_logger.log_auth_failure.assert_called_once()
                kwargs = mock_sec_logger.log_auth_failure.call_args
                # Verificar que s'ha passat la IP correcta
                all_args = str(kwargs)
                assert "1.2.3.4" in all_args

    async def test_no_key_logs_auth_failure(self):
        """Sense key (None header) → log_auth_failure() es crida."""
        require = make_require_ui_auth()
        mock_sec_logger = MagicMock()
        with patch("plugins.web_ui_module.api.routes_auth.get_admin_api_key", return_value="real_key"):
            with patch(
                "plugins.security.security_logger.get_security_logger",
                return_value=mock_sec_logger,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await require(_mock_request(), x_api_key=None)
                assert exc_info.value.status_code == 401
                mock_sec_logger.log_auth_failure.assert_called_once()

    async def test_valid_key_no_auth_failure_log(self):
        """Key vàlida → NO s'ha de cridar log_auth_failure()."""
        require = make_require_ui_auth()
        mock_sec_logger = MagicMock()
        with patch("plugins.web_ui_module.api.routes_auth.get_admin_api_key", return_value="real_key"):
            with patch(
                "plugins.security.security_logger.get_security_logger",
                return_value=mock_sec_logger,
            ):
                result = await require(_mock_request(), x_api_key="real_key")
                assert result is None
                mock_sec_logger.log_auth_failure.assert_not_called()
