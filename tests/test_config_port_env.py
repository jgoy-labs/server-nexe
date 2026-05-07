"""
Tests for F2 — NEXE_SERVER_PORT env var override in load_config().

Verifies that NEXE_SERVER_PORT takes priority over server.toml and DEFAULT_PORT.
"""
import os
import pytest
from unittest.mock import patch
from core.config import load_config, DEFAULT_PORT


# Minimal TOML for tests (default port 9119)
_MINIMAL_TOML = b"""
[core.server]
port = 9119
"""

# TOML with a port different from the default
_CUSTOM_TOML = b"""
[core.server]
port = 8080
"""


class TestLoadConfigEnvPortOverride:
    """F2 — NEXE_SERVER_PORT env var overrides the port read from TOML."""

    def test_env_overrides_toml_port(self, tmp_path):
        """NEXE_SERVER_PORT=9200 must override the port from server.toml."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_MINIMAL_TOML)
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "9200"}, clear=False):
            result = load_config(config_path=config_file)
        assert result['core']['server']['port'] == 9200

    def test_env_overrides_custom_toml_port(self, tmp_path):
        """NEXE_SERVER_PORT must override any TOML value, not just the default."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_CUSTOM_TOML)
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "7777"}, clear=False):
            result = load_config(config_path=config_file)
        assert result['core']['server']['port'] == 7777

    def test_no_env_var_uses_toml_port(self, tmp_path):
        """Without NEXE_SERVER_PORT, the port comes from TOML."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_CUSTOM_TOML)
        env_clean = {k: v for k, v in os.environ.items() if k != "NEXE_SERVER_PORT"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = load_config(config_path=config_file)
        assert result['core']['server']['port'] == 8080

    def test_no_env_var_no_config_uses_default(self):
        """Without env var or config file, the port is DEFAULT_PORT."""
        env_clean = {k: v for k, v in os.environ.items() if k != "NEXE_SERVER_PORT"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = load_config(project_root=None, config_path=None)
        assert result['core']['server']['port'] == DEFAULT_PORT

    def test_env_overrides_when_no_config_file(self):
        """NEXE_SERVER_PORT must work even when there is no config file."""
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "9300"}, clear=False):
            result = load_config(project_root=None, config_path=None)
        assert result['core']['server']['port'] == 9300

    def test_invalid_env_var_raises_value_error(self, tmp_path):
        """Non-numeric NEXE_SERVER_PORT must raise ValueError (fail-fast)."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_MINIMAL_TOML)
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "not-a-port"}, clear=False):
            with pytest.raises(ValueError):
                load_config(config_path=config_file)
