"""
Tests for core/server/factory_security.py::validate_production_security.

Codex P1 fix: validate_production_security() must pass `config` to
get_module_allowlist() so production mode detection works via
server.toml [core.environment.mode], not only NEXE_ENV env var.

Cirurgia post-BUS Q2.2.
"""

import os
import pytest
from unittest.mock import MagicMock

from core.server.factory_security import validate_production_security


@pytest.fixture
def clean_env(monkeypatch):
    """Ensure test environment is clean."""
    monkeypatch.delenv("NEXE_ENV", raising=False)
    monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
    yield monkeypatch


@pytest.fixture
def mock_i18n():
    i18n = MagicMock()
    i18n.t.side_effect = lambda key, **kw: key
    return i18n


class TestValidateProductionSecurityConfig:
    def test_production_via_config_toml_without_allowlist_raises(self, clean_env, mock_i18n):
        """Production mode declared in server.toml [core.environment.mode]
        but NEXE_APPROVED_MODULES not set → must raise ValueError.
        Pre-fix: validate_production_security ignored config and only checked
        NEXE_ENV env var, so it would NOT raise here.
        """
        config = {"core": {"environment": {"mode": "production"}}}
        with pytest.raises(ValueError, match="NEXE_APPROVED_MODULES"):
            validate_production_security(mock_i18n, config=config)

    def test_production_via_config_toml_with_allowlist_passes(self, clean_env, mock_i18n):
        """Production mode in server.toml + NEXE_APPROVED_MODULES set → OK."""
        clean_env.setenv("NEXE_APPROVED_MODULES", "security,memory")
        config = {"core": {"environment": {"mode": "production"}}}
        # Should not raise
        validate_production_security(mock_i18n, config=config)

    def test_development_mode_no_allowlist_passes(self, clean_env, mock_i18n):
        """Development mode is OK without allowlist."""
        config = {"core": {"environment": {"mode": "development"}}}
        validate_production_security(mock_i18n, config=config)

    def test_production_via_env_var_without_allowlist_raises(self, clean_env, mock_i18n):
        """Production mode via NEXE_ENV without allowlist → still raises (regression test)."""
        clean_env.setenv("NEXE_ENV", "production")
        with pytest.raises(ValueError, match="NEXE_APPROVED_MODULES"):
            validate_production_security(mock_i18n, config=None)

    def test_no_config_no_env_passes(self, clean_env, mock_i18n):
        """No config + no env var → development mode → OK."""
        validate_production_security(mock_i18n, config=None)
