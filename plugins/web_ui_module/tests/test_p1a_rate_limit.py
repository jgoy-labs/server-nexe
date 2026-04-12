"""
Tests P1-A — Rate limit de fallades d'autenticació a la Web UI per IP.

Problema: make_require_ui_auth() no tenia cap límit de freqüència.
25 requests amb keys invàlides → 25 × 401, cap 429. Brute force invisible.

Fix: dict en memòria _ui_auth_failures per IP, finestra 60s, màxim 20 intents.
Passat el límit: 429 Too Many Requests.

Patró de test: funcions helpers (_check_ui_rate_limit, _record_ui_auth_failure)
testejades directament + make_require_ui_auth() via mock, igual que P1-B.

www.jgoy.net · https://server-nexe.org
"""

from unittest.mock import patch, MagicMock
import pytest

try:
    from plugins.web_ui_module.api.routes_auth import (
        _check_ui_rate_limit,
        _record_ui_auth_failure,
        _ui_auth_failures,
        _UI_RATE_LIMIT,
        _UI_RATE_WINDOW,
        make_require_ui_auth,
    )
    from fastapi import HTTPException
except ImportError as e:
    pytest.skip(f"Rate limit helpers not available: {e}", allow_module_level=True)


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_rate_limit_state():
    """Neteja el dict de fallades entre tests per evitar interferències."""
    _ui_auth_failures.clear()
    yield
    _ui_auth_failures.clear()


def _mock_request(host="1.2.3.4", path="/ui/chat"):
    req = MagicMock()
    req.app.state = MagicMock(spec=[])
    req.client.host = host
    req.url.path = path
    return req


# ─── Tests dels helpers de rate limit ──────────────────────────────────────────

class TestRateLimitHelpers:
    def test_no_failures_not_limited(self):
        """IP sense historial → no limitada."""
        assert _check_ui_rate_limit("10.0.0.1") is False

    def test_below_limit_not_limited(self):
        """< 20 fallades → no limitada."""
        for _ in range(_UI_RATE_LIMIT - 1):
            _record_ui_auth_failure("10.0.0.1")
        assert _check_ui_rate_limit("10.0.0.1") is False

    def test_at_limit_is_limited(self):
        """Exactament 20 fallades → limitada."""
        for _ in range(_UI_RATE_LIMIT):
            _record_ui_auth_failure("10.0.0.1")
        assert _check_ui_rate_limit("10.0.0.1") is True

    def test_over_limit_is_limited(self):
        """25 fallades → limitada."""
        for _ in range(25):
            _record_ui_auth_failure("10.0.0.1")
        assert _check_ui_rate_limit("10.0.0.1") is True

    def test_different_ips_independent(self):
        """IPs independents — la limitació d'una no afecta l'altra."""
        for _ in range(_UI_RATE_LIMIT):
            _record_ui_auth_failure("192.168.1.1")
        # Una altra IP no ha d'estar limitada
        assert _check_ui_rate_limit("10.0.0.2") is False

    def test_window_expiry_resets_limit(self):
        """Timestamps fora de la finestra de 60s s'ignoren."""
        import time as _time
        old_time = _time.monotonic() - _UI_RATE_WINDOW - 1.0
        # Injectem timestamps antics directament al dict
        _ui_auth_failures["10.0.0.3"] = [old_time] * _UI_RATE_LIMIT
        # Tots els timestamps han expirat → no limitada
        assert _check_ui_rate_limit("10.0.0.3") is False


# ─── Tests d'integració amb make_require_ui_auth ────────────────────────────────

@pytest.mark.asyncio
class TestRateLimitIntegration:
    async def test_21_failures_last_returns_429(self):
        """21 intents invàlids des de la mateixa IP → l'últim retorna 429."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="real_key",
        ):
            # Primers 20 → 401
            for _ in range(_UI_RATE_LIMIT):
                with pytest.raises(HTTPException) as exc_info:
                    await require(_mock_request(host="5.5.5.5"), x_api_key="wrong")
                assert exc_info.value.status_code == 401

            # Nº 21 → 429
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(host="5.5.5.5"), x_api_key="wrong")
            assert exc_info.value.status_code == 429

    async def test_valid_key_not_counted(self):
        """Key vàlida no s'ha de comptar com a fallada."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="real_key",
        ):
            # 19 invàlides
            for _ in range(_UI_RATE_LIMIT - 1):
                with pytest.raises(HTTPException):
                    await require(_mock_request(host="6.6.6.6"), x_api_key="wrong")

            # 1 vàlida → 200 (sense excepció)
            result = await require(_mock_request(host="6.6.6.6"), x_api_key="real_key")
            assert result is None

            # La 20a invàlida → 401 (no 429 perquè la vàlida no compta)
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(host="6.6.6.6"), x_api_key="wrong")
            assert exc_info.value.status_code == 401
