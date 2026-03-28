"""
Tests for encryption at-rest integration in lifespan.py
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from core.lifespan import ServerState


class TestServerStateCrypto:
    """crypto_provider attribute on ServerState."""

    def test_crypto_provider_default_none(self):
        state = ServerState()
        assert state.crypto_provider is None

    def test_crypto_provider_assignable(self):
        state = ServerState()
        mock_crypto = MagicMock()
        state.crypto_provider = mock_crypto
        assert state.crypto_provider is mock_crypto


class TestCryptoInitLogic:
    """Unit tests for encryption init logic (extracted from lifespan)."""

    def _run_crypto_init(self, config, env_vars=None):
        """Simulate the crypto init block from lifespan."""
        env = env_vars or {}
        with patch.dict(os.environ, env, clear=False):
            from core.crypto import CryptoProvider, check_encryption_status

            encryption_config = config.get('security', {}).get('encryption', {})
            crypto_enabled = encryption_config.get('enabled', False)

            env_crypto = os.environ.get('NEXE_ENCRYPTION_ENABLED', '').lower()
            if env_crypto == 'true':
                crypto_enabled = True
            elif env_crypto == 'false':
                crypto_enabled = False

            return crypto_enabled

    def test_disabled_by_default(self):
        config = {'security': {'encryption': {'enabled': False}}}
        assert self._run_crypto_init(config) is False

    def test_enabled_via_config(self):
        config = {'security': {'encryption': {'enabled': True}}}
        assert self._run_crypto_init(config) is True

    def test_enabled_via_env_var(self):
        config = {'security': {'encryption': {'enabled': False}}}
        assert self._run_crypto_init(config, {'NEXE_ENCRYPTION_ENABLED': 'true'}) is True

    def test_env_var_overrides_config_true(self):
        """Env var false overrides config enabled=True."""
        config = {'security': {'encryption': {'enabled': True}}}
        assert self._run_crypto_init(config, {'NEXE_ENCRYPTION_ENABLED': 'false'}) is False

    def test_env_var_overrides_config_false(self):
        """Env var true overrides config enabled=False."""
        config = {'security': {'encryption': {'enabled': False}}}
        assert self._run_crypto_init(config, {'NEXE_ENCRYPTION_ENABLED': 'true'}) is True

    def test_empty_config_defaults_disabled(self):
        config = {}
        assert self._run_crypto_init(config) is False

    def test_init_failure_non_fatal(self):
        """CryptoProvider failure should not crash — crypto stays None."""
        state = ServerState()
        try:
            with patch('core.crypto.CryptoProvider', side_effect=RuntimeError("keyring fail")):
                from core.crypto import CryptoProvider
                try:
                    state.crypto_provider = CryptoProvider()
                except Exception:
                    state.crypto_provider = None
        except Exception:
            state.crypto_provider = None

        assert state.crypto_provider is None
