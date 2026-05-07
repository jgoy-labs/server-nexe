"""
Tests P1-A — Rate limit for authentication failures in the Web UI per IP.

Problem: make_require_ui_auth() had no rate limiting.
25 requests with invalid keys → 25 × 401, no 429. Invisible brute force.

Fix: in-memory dict _ui_auth_failures per IP, 60s window, maximum 20 attempts.
Past the limit: 429 Too Many Requests.

Test pattern: helper functions (_check_ui_rate_limit, _record_ui_auth_failure)
tested directly + make_require_ui_auth() via mock, same as P1-B.

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


# ─── Tests for rate limit helpers ──────────────────────────────────────────

class TestRateLimitHelpers:
    def test_no_failures_not_limited(self):
        """IP without history → not limited."""
        assert _check_ui_rate_limit("10.0.0.1") is False

    def test_below_limit_not_limited(self):
        """< 20 failures → not limited."""
        for _ in range(_UI_RATE_LIMIT - 1):
            _record_ui_auth_failure("10.0.0.1")
        assert _check_ui_rate_limit("10.0.0.1") is False

    def test_at_limit_is_limited(self):
        """Exactly 20 failures → limited."""
        for _ in range(_UI_RATE_LIMIT):
            _record_ui_auth_failure("10.0.0.1")
        assert _check_ui_rate_limit("10.0.0.1") is True

    def test_over_limit_is_limited(self):
        """25 failures → limited."""
        for _ in range(25):
            _record_ui_auth_failure("10.0.0.1")
        assert _check_ui_rate_limit("10.0.0.1") is True

    def test_different_ips_independent(self):
        """Independent IPs — limiting one does not affect the other."""
        for _ in range(_UI_RATE_LIMIT):
            _record_ui_auth_failure("192.168.1.1")
        # Another IP must not be limited
        assert _check_ui_rate_limit("10.0.0.2") is False

    def test_window_expiry_resets_limit(self):
        """Timestamps outside the 60s window are ignored."""
        import time as _time
        old_time = _time.monotonic() - _UI_RATE_WINDOW - 1.0
        # Inject old timestamps directly into the dict
        _ui_auth_failures["10.0.0.3"] = [old_time] * _UI_RATE_LIMIT
        # All timestamps expired → not limited
        assert _check_ui_rate_limit("10.0.0.3") is False


# ─── Integration tests with make_require_ui_auth ────────────────────────────────

@pytest.mark.asyncio
class TestRateLimitIntegration:
    async def test_21_failures_last_returns_429(self):
        """21 invalid attempts from the same IP → the last returns 429."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="real_key",
        ):
            # First 20 → 401
            for _ in range(_UI_RATE_LIMIT):
                with pytest.raises(HTTPException) as exc_info:
                    await require(_mock_request(host="5.5.5.5"), x_api_key="wrong")
                assert exc_info.value.status_code == 401

            # No. 21 → 429
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(host="5.5.5.5"), x_api_key="wrong")
            assert exc_info.value.status_code == 429

    async def test_valid_key_not_counted(self):
        """Valid key must not be counted as a failure."""
        require = make_require_ui_auth()
        with patch(
            "plugins.web_ui_module.api.routes_auth.get_admin_api_key",
            return_value="real_key",
        ):
            # 19 invalid
            for _ in range(_UI_RATE_LIMIT - 1):
                with pytest.raises(HTTPException):
                    await require(_mock_request(host="6.6.6.6"), x_api_key="wrong")

            # 1 valid → 200 (no exception)
            result = await require(_mock_request(host="6.6.6.6"), x_api_key="real_key")
            assert result is None

            # The 20th invalid → 401 (not 429 because the valid one doesn't count)
            with pytest.raises(HTTPException) as exc_info:
                await require(_mock_request(host="6.6.6.6"), x_api_key="wrong")
            assert exc_info.value.status_code == 401
