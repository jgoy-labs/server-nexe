"""
Tests per core/config.py
"""
import os
import pytest
import toml
from pathlib import Path
from unittest.mock import patch

from core.config import (
    find_config_path,
    load_config,
    save_config,
    get_environment_mode,
    is_production,
    is_development,
    _deep_merge,
    get_config,
    get_config_path,
    reset_config,
    DEFAULT_CONFIG,
    CONFIG_SEARCH_PATHS,
)


class TestFindConfigPath:
    def test_no_config_found_returns_none(self, tmp_path):
        result = find_config_path(tmp_path)
        assert result is None

    def test_finds_server_toml(self, tmp_path):
        config_file = tmp_path / "server.toml"
        config_file.write_text("[core]\n")
        result = find_config_path(tmp_path)
        assert result is not None
        assert result.name == "server.toml"

    def test_finds_personality_server_toml(self, tmp_path):
        personality_dir = tmp_path / "personality"
        personality_dir.mkdir()
        config_file = personality_dir / "server.toml"
        config_file.write_text("[core]\n")
        result = find_config_path(tmp_path)
        assert result is not None

    def test_uses_cwd_when_no_root(self):
        # Sense project_root → usa cwd (pot ser None)
        result = find_config_path(None)
        # No llencem excepcions, el resultat pot ser None o un Path
        assert result is None or isinstance(result, Path)


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        config = load_config(project_root=tmp_path)
        assert "core" in config
        assert config["core"]["server"]["host"] == "127.0.0.1"

    def test_loads_valid_toml(self, tmp_path):
        config_file = tmp_path / "server.toml"
        config_file.write_text('[core.server]\nhost = "0.0.0.0"\nport = 8080\n')
        config = load_config(project_root=tmp_path)
        assert config["core"]["server"]["host"] == "0.0.0.0"
        assert config["core"]["server"]["port"] == 8080

    def test_merges_with_defaults(self, tmp_path):
        config_file = tmp_path / "server.toml"
        config_file.write_text('[plugins]\nenabled = true\n')
        config = load_config(project_root=tmp_path)
        # Ha de mantenir els defaults i afegir plugins
        assert "core" in config
        assert "plugins" in config

    def test_returns_defaults_on_toml_error(self, tmp_path):
        config_file = tmp_path / "server.toml"
        config_file.write_text("INVALID TOML CONTENT !!!{}")
        config = load_config(project_root=tmp_path)
        assert "core" in config  # fallback als defaults

    def test_with_direct_config_path(self, tmp_path):
        config_file = tmp_path / "custom.toml"
        config_file.write_text('[core.server]\nport = 7777\n')
        config = load_config(config_path=config_file)
        assert config["core"]["server"]["port"] == 7777

    def test_with_i18n(self, tmp_path):
        from unittest.mock import MagicMock
        i18n = MagicMock()
        i18n.t.return_value = "Missatge traduit"
        config = load_config(project_root=tmp_path, i18n=i18n)
        assert "core" in config  # retorna defaults

    def test_with_i18n_and_valid_config(self, tmp_path):
        from unittest.mock import MagicMock
        config_file = tmp_path / "server.toml"
        config_file.write_text('[core]\n')
        i18n = MagicMock()
        i18n.t.return_value = "Traduit"
        config = load_config(project_root=tmp_path, i18n=i18n)
        assert "core" in config


class TestSaveConfig:
    def test_saves_config_successfully(self, tmp_path):
        config_file = tmp_path / "output.toml"
        config = {"core": {"server": {"host": "127.0.0.1"}}}
        result = save_config(config, config_file)
        assert result is True
        assert config_file.exists()
        loaded = toml.load(str(config_file))
        assert loaded["core"]["server"]["host"] == "127.0.0.1"

    def test_returns_false_on_error(self, tmp_path):
        # Directori no existent
        invalid_path = tmp_path / "no_dir" / "output.toml"
        config = {"core": {}}
        result = save_config(config, invalid_path)
        assert result is False


class TestGetEnvironmentMode:
    def test_from_env_production(self):
        with patch.dict(os.environ, {"NEXE_ENV": "production"}):
            result = get_environment_mode({})
        assert result == "production"

    def test_from_env_development(self):
        with patch.dict(os.environ, {"NEXE_ENV": "development"}):
            result = get_environment_mode({})
        assert result == "development"

    def test_from_config(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("NEXE_ENV", "ENV")}
        with patch.dict(os.environ, env_clean, clear=True):
            config = {"core": {"environment": {"mode": "development"}}}
            result = get_environment_mode(config)
        assert result == "development"

    def test_default_production(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("NEXE_ENV", "ENV")}
        with patch.dict(os.environ, env_clean, clear=True):
            result = get_environment_mode({})
        assert result == "production"

    def test_env_var_takes_priority_over_config(self):
        with patch.dict(os.environ, {"NEXE_ENV": "production"}):
            config = {"core": {"environment": {"mode": "development"}}}
            result = get_environment_mode(config)
        assert result == "production"

    def test_invalid_env_var_falls_to_config(self):
        env_with_invalid = {"NEXE_ENV": "staging"}
        env_clean = {k: v for k, v in os.environ.items() if k not in ("NEXE_ENV", "ENV")}
        env_clean.update(env_with_invalid)
        with patch.dict(os.environ, env_clean, clear=True):
            config = {"core": {"environment": {"mode": "development"}}}
            result = get_environment_mode(config)
        assert result == "development"


class TestIsProductionDevelopment:
    def test_is_production_true(self):
        with patch.dict(os.environ, {"NEXE_ENV": "production"}):
            assert is_production({}) is True
            assert is_development({}) is False

    def test_is_development_true(self):
        with patch.dict(os.environ, {"NEXE_ENV": "development"}):
            assert is_development({}) is True
            assert is_production({}) is False


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"core": {"server": {"host": "127.0.0.1", "port": 9119}}}
        override = {"core": {"server": {"port": 8080}}}
        result = _deep_merge(base, override)
        assert result["core"]["server"]["host"] == "127.0.0.1"
        assert result["core"]["server"]["port"] == 8080

    def test_override_non_dict_with_dict(self):
        base = {"key": "string_value"}
        override = {"key": {"nested": "dict"}}
        result = _deep_merge(base, override)
        assert result["key"] == {"nested": "dict"}

    def test_empty_override(self):
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}


class TestConfigSingleton:
    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_get_config_returns_dict(self):
        config = get_config()
        assert isinstance(config, dict)
        assert "core" in config

    def test_get_config_singleton(self):
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_get_config_reload(self):
        config1 = get_config()
        config2 = get_config(reload=True)
        # Pot ser el mateix contingut però és una nova càrrega
        assert isinstance(config2, dict)

    def test_get_config_path(self):
        get_config()
        path = get_config_path()
        assert path is None or isinstance(path, Path)

    def test_reset_config(self):
        get_config()
        reset_config()
        # Ara l'singleton és None de nou
        # La propera crida el reinicialitzarà
        config = get_config()
        assert isinstance(config, dict)
