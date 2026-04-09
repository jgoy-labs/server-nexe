"""
Tests per a F2 — NEXE_SERVER_PORT env var override a load_config().

Verifica que NEXE_SERVER_PORT té prioritat sobre server.toml i el DEFAULT_PORT.
"""
import os
import pytest
from unittest.mock import patch
from core.config import load_config, DEFAULT_PORT


# TOML mínim per als tests (port 9119 per defecte)
_MINIMAL_TOML = b"""
[core.server]
port = 9119
"""

# TOML amb port diferent al default
_CUSTOM_TOML = b"""
[core.server]
port = 8080
"""


class TestLoadConfigEnvPortOverride:
    """F2 — NEXE_SERVER_PORT env var sobreescriu el port llegit de TOML."""

    def test_env_overrides_toml_port(self, tmp_path):
        """NEXE_SERVER_PORT=9200 ha de sobreescriure el port de server.toml."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_MINIMAL_TOML)
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "9200"}, clear=False):
            result = load_config(config_path=config_file)
        assert result['core']['server']['port'] == 9200

    def test_env_overrides_custom_toml_port(self, tmp_path):
        """NEXE_SERVER_PORT ha de sobreescriure qualsevol valor de TOML, no només el default."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_CUSTOM_TOML)
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "7777"}, clear=False):
            result = load_config(config_path=config_file)
        assert result['core']['server']['port'] == 7777

    def test_no_env_var_uses_toml_port(self, tmp_path):
        """Sense NEXE_SERVER_PORT, el port ve del TOML."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_CUSTOM_TOML)
        env_clean = {k: v for k, v in os.environ.items() if k != "NEXE_SERVER_PORT"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = load_config(config_path=config_file)
        assert result['core']['server']['port'] == 8080

    def test_no_env_var_no_config_uses_default(self):
        """Sense env var ni config file, el port és DEFAULT_PORT."""
        env_clean = {k: v for k, v in os.environ.items() if k != "NEXE_SERVER_PORT"}
        with patch.dict(os.environ, env_clean, clear=True):
            result = load_config(project_root=None, config_path=None)
        assert result['core']['server']['port'] == DEFAULT_PORT

    def test_env_overrides_when_no_config_file(self):
        """NEXE_SERVER_PORT ha de funcionar fins i tot quan no hi ha config file."""
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "9300"}, clear=False):
            result = load_config(project_root=None, config_path=None)
        assert result['core']['server']['port'] == 9300

    def test_invalid_env_var_raises_value_error(self, tmp_path):
        """NEXE_SERVER_PORT no numèrica ha de llençar ValueError (fail-fast)."""
        config_file = tmp_path / "server.toml"
        config_file.write_bytes(_MINIMAL_TOML)
        with patch.dict(os.environ, {"NEXE_SERVER_PORT": "not-a-port"}, clear=False):
            with pytest.raises(ValueError):
                load_config(config_path=config_file)
