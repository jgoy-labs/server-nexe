"""
Tests for plugins/security/core/auth_dependencies.py - targeting uncovered lines.
Covers: _is_loopback_ip, secondary key metrics, dev mode bypass, secondary key
auth, expired key reasons, auth failure logging, and optional_api_key paths.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from datetime import datetime, timezone, timedelta


class TestIsLoopbackIp:
    """Test lines 42-46."""

    def test_loopback_ipv4(self):
        from plugins.security.core.auth_dependencies import _is_loopback_ip
        assert _is_loopback_ip("127.0.0.1") is True

    def test_loopback_ipv6(self):
        from plugins.security.core.auth_dependencies import _is_loopback_ip
        assert _is_loopback_ip("::1") is True

    def test_non_loopback(self):
        from plugins.security.core.auth_dependencies import _is_loopback_ip
        assert _is_loopback_ip("192.168.1.1") is False

    def test_invalid_ip(self):
        from plugins.security.core.auth_dependencies import _is_loopback_ip
        assert _is_loopback_ip("not-an-ip") is False


class TestRequireApiKeyMetrics:
    """Test lines 89-94: secondary key metrics update."""

    @pytest.mark.asyncio
    async def test_secondary_key_with_expiry_updates_metrics(self, monkeypatch):
        """Lines 89-94: secondary key with expires_at triggers metric update."""
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig

        future = datetime.now(timezone.utc) + timedelta(days=30)
        secondary = ApiKeyData(key="secondary-key-123", expires_at=future)
        primary = ApiKeyData(key="primary-key-123")
        config = ApiKeyConfig(primary=primary, secondary=secondary)

        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "primary-key-123")
        monkeypatch.setenv("NEXE_SECONDARY_API_KEY", "secondary-key-123")
        monkeypatch.delenv("NEXE_DEV_MODE", raising=False)

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/test"

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False), \
             patch("plugins.security.core.auth_dependencies.update_key_expiry_days") as mock_expiry, \
             patch("plugins.security.core.auth_dependencies.update_key_status") as mock_status, \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"), \
             patch("plugins.security.core.auth_dependencies.record_auth_attempt"):
            from plugins.security.core.auth_dependencies import require_api_key
            result = await require_api_key(mock_request, x_api_key="primary-key-123")
            assert result == "primary-key-123"
            # Verify secondary key metrics were updated
            mock_expiry.assert_any_call('secondary', pytest.approx(30, abs=1))
            mock_status.assert_any_call('secondary', 'active')

    @pytest.mark.asyncio
    async def test_secondary_key_no_expiry_updates_metrics(self, monkeypatch):
        """Lines 92-93: secondary key without expires_at sets -1."""
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig

        secondary = ApiKeyData(key="secondary-no-exp")
        primary = ApiKeyData(key="primary-key-xyz")
        config = ApiKeyConfig(primary=primary, secondary=secondary)

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/test"

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False), \
             patch("plugins.security.core.auth_dependencies.update_key_expiry_days") as mock_expiry, \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"), \
             patch("plugins.security.core.auth_dependencies.record_auth_attempt"):
            from plugins.security.core.auth_dependencies import require_api_key
            result = await require_api_key(mock_request, x_api_key="primary-key-xyz")
            mock_expiry.assert_any_call('secondary', -1)


class TestDevModeBypass:
    """Test lines 102-118: dev mode bypass logic."""

    @pytest.mark.asyncio
    async def test_dev_mode_bypass_localhost(self, monkeypatch):
        """Lines 102-120: dev mode bypass from localhost."""
        from plugins.security.core.auth_models import ApiKeyConfig

        config = ApiKeyConfig()  # no keys configured

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=True), \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"):
            from plugins.security.core.auth_dependencies import require_api_key
            result = await require_api_key(mock_request, x_api_key=None)
            assert result == "dev-mode-bypass"

    @pytest.mark.asyncio
    async def test_dev_mode_blocked_remote(self, monkeypatch):
        """Lines 104-108: dev mode blocked from remote IP."""
        from plugins.security.core.auth_models import ApiKeyConfig

        config = ApiKeyConfig()

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "192.168.1.100"

        monkeypatch.delenv("NEXE_DEV_MODE_ALLOW_REMOTE", raising=False)

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=True), \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"):
            from plugins.security.core.auth_dependencies import require_api_key
            with pytest.raises(HTTPException) as exc_info:
                await require_api_key(mock_request, x_api_key=None)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_keys_no_dev_mode_raises_500(self):
        """Lines 121-125: no valid keys, no dev mode -> 500."""
        from plugins.security.core.auth_models import ApiKeyConfig

        config = ApiKeyConfig()

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False), \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"):
            from plugins.security.core.auth_dependencies import require_api_key
            with pytest.raises(HTTPException) as exc_info:
                await require_api_key(mock_request, x_api_key=None)
            assert exc_info.value.status_code == 500


class TestSecondaryKeyAuth:
    """Test lines 158-176: secondary key authentication."""

    @pytest.mark.asyncio
    async def test_secondary_key_auth_success(self):
        """Lines 157-176: auth with valid secondary key."""
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig

        # Primary key exists but doesn't match
        primary = ApiKeyData(key="primary-abc")
        secondary = ApiKeyData(key="secondary-xyz")
        config = ApiKeyConfig(primary=primary, secondary=secondary)

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/test"

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False), \
             patch("plugins.security.core.auth_dependencies.update_key_expiry_days"), \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"), \
             patch("plugins.security.core.auth_dependencies.record_auth_attempt"):
            from plugins.security.core.auth_dependencies import require_api_key
            result = await require_api_key(mock_request, x_api_key="secondary-xyz")
            assert result == "secondary-xyz"


class TestExpiredKeyReasons:
    """Test lines 179-182: expired key failure reasons."""

    @pytest.mark.asyncio
    async def test_primary_expired_reason(self):
        """Line 180: primary_key_expired reason. Need a valid secondary so it doesn't go to 500."""
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig

        past = datetime.now(timezone.utc) - timedelta(days=10)
        primary = ApiKeyData(key="old-primary", expires_at=past)
        # A valid secondary key so has_any_valid_key is True
        secondary = ApiKeyData(key="valid-secondary")
        config = ApiKeyConfig(primary=primary, secondary=secondary)

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/test"

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False), \
             patch("plugins.security.core.auth_dependencies.update_key_expiry_days"), \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"), \
             patch("plugins.security.core.auth_dependencies.record_auth_failure") as mock_failure:
            from plugins.security.core.auth_dependencies import require_api_key
            with pytest.raises(HTTPException) as exc_info:
                await require_api_key(mock_request, x_api_key="wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_secondary_expired_reason(self):
        """Line 182: secondary_key_expired reason."""
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig

        past = datetime.now(timezone.utc) - timedelta(days=10)
        primary = ApiKeyData(key="primary-key")
        secondary = ApiKeyData(key="old-secondary", expires_at=past)
        config = ApiKeyConfig(primary=primary, secondary=secondary)

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/test"

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False), \
             patch("plugins.security.core.auth_dependencies.update_key_expiry_days"), \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"), \
             patch("plugins.security.core.auth_dependencies.record_auth_failure"), \
             patch("plugins.security.core.auth_dependencies.record_auth_attempt"):
            from plugins.security.core.auth_dependencies import require_api_key
            with pytest.raises(HTTPException) as exc_info:
                await require_api_key(mock_request, x_api_key="wrong-key")
            assert exc_info.value.status_code == 401


class TestOptionalApiKey:
    """Test lines 224, 227, 238."""

    @pytest.mark.asyncio
    async def test_dev_mode_no_admin_key(self):
        """Line 224: dev mode without admin key returns None."""
        from plugins.security.core.auth_models import ApiKeyConfig

        config = ApiKeyConfig()

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.get_admin_api_key", return_value=""), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=True):
            from plugins.security.core.auth_dependencies import optional_api_key
            result = await optional_api_key(x_api_key=None)
            assert result is None

    @pytest.mark.asyncio
    async def test_no_key_provided(self):
        """Line 227: no key provided returns None."""
        from plugins.security.core.auth_models import ApiKeyConfig

        config = ApiKeyConfig()

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.get_admin_api_key", return_value="admin-key"), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False):
            from plugins.security.core.auth_dependencies import optional_api_key
            result = await optional_api_key(x_api_key=None)
            assert result is None

    @pytest.mark.asyncio
    async def test_admin_key_match(self):
        """Line 238: matches admin/legacy key."""
        from plugins.security.core.auth_models import ApiKeyConfig

        config = ApiKeyConfig()

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.get_admin_api_key", return_value="admin-key-match"), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False):
            from plugins.security.core.auth_dependencies import optional_api_key
            result = await optional_api_key(x_api_key="admin-key-match")
            assert result == "admin-key-match"

    @pytest.mark.asyncio
    async def test_expired_primary_not_accepted_via_admin(self):
        """A-004: an EXPIRED primary key must NOT be re-accepted via the admin branch.
        get_admin_api_key() returns primary.key by default, so without the
        admin_key != primary guard an expired primary would slip through."""
        from datetime import datetime, timedelta, timezone
        from plugins.security.core.auth_models import ApiKeyConfig, ApiKeyData

        expired = ApiKeyData(
            key="pk-expired",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        config = ApiKeyConfig(primary=expired)
        assert not config.primary.is_valid  # sanity: la primary està caducada

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.get_admin_api_key", return_value="pk-expired"), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False):
            from plugins.security.core.auth_dependencies import optional_api_key
            result = await optional_api_key(x_api_key="pk-expired")
            assert result is None  # caducada → rebutjada, no acceptada per la via admin

    @pytest.mark.asyncio
    async def test_invalid_key_returns_none(self):
        """No match returns None."""
        from plugins.security.core.auth_models import ApiKeyConfig

        config = ApiKeyConfig()

        with patch("plugins.security.core.auth_dependencies.load_api_keys", return_value=config), \
             patch("plugins.security.core.auth_dependencies.get_admin_api_key", return_value="real-key"), \
             patch("plugins.security.core.auth_dependencies.is_dev_mode", return_value=False):
            from plugins.security.core.auth_dependencies import optional_api_key
            result = await optional_api_key(x_api_key="wrong-key")
            assert result is None


# ── Helpers directes ─────────────────────────────────────────────────────────

class TestUpdateKeyMetrics:
    """Direct tests for _update_key_metrics."""

    def test_no_keys_configured(self):
        from plugins.security.core.auth_models import ApiKeyConfig
        from plugins.security.core.auth_dependencies import _update_key_metrics

        config = ApiKeyConfig()
        with patch("plugins.security.core.auth_dependencies.update_key_status") as mock_status, \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active") as mock_grace:
            _update_key_metrics(config)
            mock_status.assert_any_call('primary', 'not_configured')
            mock_status.assert_any_call('secondary', 'not_configured')
            # None and ... = None (Python short-circuit), falsy is correct here
            assert not mock_grace.call_args[0][0]

    def test_primary_with_expiry(self):
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig

        future = datetime.now(timezone.utc) + timedelta(days=15)
        primary = ApiKeyData(key="pk", expires_at=future)
        config = ApiKeyConfig(primary=primary)

        with patch("plugins.security.core.auth_dependencies.update_key_expiry_days") as mock_expiry, \
             patch("plugins.security.core.auth_dependencies.update_key_status"), \
             patch("plugins.security.core.auth_dependencies.set_grace_period_active"):
            from plugins.security.core.auth_dependencies import _update_key_metrics
            _update_key_metrics(config)
            mock_expiry.assert_any_call('primary', pytest.approx(15, abs=1))


class TestCheckDevMode:
    """Direct tests for _check_dev_mode."""

    def test_dev_mode_true_localhost_returns_bypass(self):
        from plugins.security.core.auth_dependencies import _check_dev_mode

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        result = _check_dev_mode(mock_request, dev_mode=True)
        assert result == "dev-mode-bypass"

    def test_dev_mode_true_remote_allowed_via_env(self, monkeypatch):
        from plugins.security.core.auth_dependencies import _check_dev_mode

        monkeypatch.setenv("NEXE_DEV_MODE_ALLOW_REMOTE", "true")
        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.5"

        result = _check_dev_mode(mock_request, dev_mode=True)
        assert result == "dev-mode-bypass"

    def test_dev_mode_false_raises_500(self):
        from plugins.security.core.auth_dependencies import _check_dev_mode

        mock_request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            _check_dev_mode(mock_request, dev_mode=False)
        assert exc_info.value.status_code == 500

    def test_dev_mode_true_remote_blocked(self, monkeypatch):
        from plugins.security.core.auth_dependencies import _check_dev_mode

        monkeypatch.delenv("NEXE_DEV_MODE_ALLOW_REMOTE", raising=False)
        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.50"

        with pytest.raises(HTTPException) as exc_info:
            _check_dev_mode(mock_request, dev_mode=True)
        assert exc_info.value.status_code == 403


class TestAuthenticatePrimary:
    """Direct tests for _authenticate_primary."""

    def test_valid_primary_match_returns_key(self):
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig
        from plugins.security.core.auth_dependencies import _authenticate_primary

        primary = ApiKeyData(key="primary-key-ok")
        config = ApiKeyConfig(primary=primary)

        mock_request = MagicMock()
        mock_request.url.path = "/test"

        with patch("plugins.security.core.auth_dependencies.record_auth_attempt"):
            result = _authenticate_primary("primary-key-ok", config, mock_request)
        assert result == "primary-key-ok"

    def test_valid_primary_no_match_returns_none(self):
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig
        from plugins.security.core.auth_dependencies import _authenticate_primary

        primary = ApiKeyData(key="primary-key-ok")
        config = ApiKeyConfig(primary=primary)

        mock_request = MagicMock()
        result = _authenticate_primary("wrong-key", config, mock_request)
        assert result is None

    def test_no_primary_returns_none(self):
        from plugins.security.core.auth_models import ApiKeyConfig
        from plugins.security.core.auth_dependencies import _authenticate_primary

        config = ApiKeyConfig()
        mock_request = MagicMock()
        result = _authenticate_primary("any-key", config, mock_request)
        assert result is None


class TestAuthenticateSecondary:
    """Direct tests for _authenticate_secondary."""

    def test_valid_secondary_match_returns_key(self):
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig
        from plugins.security.core.auth_dependencies import _authenticate_secondary

        secondary = ApiKeyData(key="secondary-key-ok")
        config = ApiKeyConfig(secondary=secondary)

        mock_request = MagicMock()
        mock_request.url.path = "/test"

        with patch("plugins.security.core.auth_dependencies.record_auth_attempt"):
            result = _authenticate_secondary("secondary-key-ok", config, mock_request)
        assert result == "secondary-key-ok"

    def test_valid_secondary_no_match_returns_none(self):
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig
        from plugins.security.core.auth_dependencies import _authenticate_secondary

        secondary = ApiKeyData(key="secondary-key-ok")
        config = ApiKeyConfig(secondary=secondary)

        mock_request = MagicMock()
        result = _authenticate_secondary("wrong-key", config, mock_request)
        assert result is None

    def test_no_secondary_returns_none(self):
        from plugins.security.core.auth_models import ApiKeyConfig
        from plugins.security.core.auth_dependencies import _authenticate_secondary

        config = ApiKeyConfig()
        mock_request = MagicMock()
        result = _authenticate_secondary("any-key", config, mock_request)
        assert result is None


class TestLogFailure:
    """Direct tests for _log_failure."""

    def test_invalid_key_reason(self):
        from plugins.security.core.auth_models import ApiKeyConfig
        from plugins.security.core.auth_dependencies import _log_failure

        config = ApiKeyConfig()
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch("plugins.security.core.auth_dependencies.record_auth_failure") as mock_fail:
            _log_failure(mock_request, config)
            mock_fail.assert_called_once_with("invalid_api_key")

    def test_primary_expired_reason(self):
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig
        from plugins.security.core.auth_dependencies import _log_failure

        past = datetime.now(timezone.utc) - timedelta(days=5)
        primary = ApiKeyData(key="old-pk", expires_at=past)
        config = ApiKeyConfig(primary=primary)

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch("plugins.security.core.auth_dependencies.record_auth_failure") as mock_fail:
            _log_failure(mock_request, config)
            mock_fail.assert_called_once_with("primary_key_expired")

    def test_secondary_expired_reason(self):
        from plugins.security.core.auth_models import ApiKeyData, ApiKeyConfig
        from plugins.security.core.auth_dependencies import _log_failure

        past = datetime.now(timezone.utc) - timedelta(days=3)
        secondary = ApiKeyData(key="old-sk", expires_at=past)
        primary = ApiKeyData(key="valid-pk")
        config = ApiKeyConfig(primary=primary, secondary=secondary)

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch("plugins.security.core.auth_dependencies.record_auth_failure") as mock_fail:
            _log_failure(mock_request, config)
            mock_fail.assert_called_once_with("secondary_key_expired")

    def test_logger_exception_does_not_raise(self):
        """#909: a broken IRONCLAD logger must not turn a 401 into a 500."""
        from plugins.security.core.auth_models import ApiKeyConfig
        from plugins.security.core.auth_dependencies import _log_failure

        config = ApiKeyConfig()
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch(
            "plugins.security.security_logger.get_security_logger",
            side_effect=RuntimeError("logger down"),
        ):
            _log_failure(mock_request, config)
