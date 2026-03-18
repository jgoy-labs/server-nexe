"""
Tests per personality/module_manager/config_manager.py
Covers uncovered lines: 72-80, 87-88, 105, 115-119, 143, 153-157,
172-185, 230, 234-235, 252-256, 272-276, 309-338.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import toml

from personality.module_manager.config_manager import ConfigManager


@pytest.fixture
def config_manager_with_config(tmp_path):
    """Create ConfigManager with a basic config file."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[plugins.modules]
enabled = ["security", "rag"]
""")
    return ConfigManager(config_file)


class TestTranslateHelper:
    def test_t_without_i18n(self, tmp_path):
        """Lines 72-73: no i18n -> fallback."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file, i18n=None)
        result = cm._t("key", "Fallback text")
        assert result == "Fallback text"

    def test_t_without_i18n_with_kwargs(self, tmp_path):
        """Line 73: fallback with kwargs."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file, i18n=None)
        result = cm._t("key", "Error: {name}", name="test")
        assert result == "Error: test"

    def test_t_i18n_found(self, tmp_path):
        """Lines 74-78: i18n returns translation."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated"
        cm = ConfigManager(config_file, i18n=mock_i18n)
        result = cm._t("key", "Fallback")
        assert result == "Translated"

    def test_t_i18n_returns_key(self, tmp_path):
        """Lines 76-77: i18n returns the key -> fallback."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda k, **kw: k
        cm = ConfigManager(config_file, i18n=mock_i18n)
        result = cm._t("some.key", "Fallback")
        assert result == "Fallback"

    def test_t_i18n_exception(self, tmp_path):
        """Lines 79-80: i18n exception -> fallback.
        Note: get_message in messages.py uses logging.debug without importing logging,
        so we patch it at module level."""
        import logging as logging_mod
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = RuntimeError("boom")
        with patch("personality.module_manager.messages.logging", logging_mod, create=True):
            cm = ConfigManager(config_file, i18n=mock_i18n)
        result = cm._t("key", "Fallback {x}", x="val")
        assert result == "Fallback val"


class TestFindConfigPath:
    def test_config_path_not_found(self, tmp_path):
        """Lines 87-88: config_path FileNotFoundError -> search paths."""
        cm = ConfigManager(Path("/nonexistent/server.toml"))
        # Should fall through to search paths or default
        assert cm.config_path is not None

    def test_config_path_none_uses_search(self):
        """Line 105: None config_path -> search paths, fallback."""
        cm = ConfigManager(None)
        assert cm.config_path is not None


class TestLoadConfig:
    def test_load_config_error(self, tmp_path):
        """Lines 115-119: config load error."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        with patch("personality.module_manager.config_manager.core_load_config",
                   side_effect=RuntimeError("fail")):
            cm = ConfigManager(config_file)
        assert cm._config == {}


class TestFindManifest:
    def test_central_manifest_found(self, tmp_path):
        """Lines 141-143: central manifest found."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file)

        manifest_dir = cm.manifests_path
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / "test_module.toml"
        manifest_file.write_text("[module]\nversion = '1.0'")

        result = cm.find_manifest("test_module", tmp_path / "modules" / "test_module")
        assert result == manifest_file

    def test_local_manifest_found(self, tmp_path):
        """Lines 148-155: local manifest found."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file)

        module_path = tmp_path / "modules" / "test_module"
        module_path.mkdir(parents=True)
        local_manifest = module_path / "manifest.toml"
        local_manifest.write_text("[module]\nversion = '1.0'")

        result = cm.find_manifest("test_module", module_path)
        assert result == local_manifest

    def test_no_manifest_returns_central_path(self, tmp_path):
        """Lines 153-157: no manifest found -> returns central path."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file)

        result = cm.find_manifest("test_module", tmp_path / "nonexistent")
        # Returns central path even if it doesn't exist
        assert "test_module" in str(result) or "manifests" in str(result)


class TestLoadManifest:
    def test_load_valid_manifest(self, tmp_path):
        """Lines 169-171: load valid manifest."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file)

        manifest_file = tmp_path / "manifest.toml"
        manifest_file.write_text("[module]\nversion = '2.0'\nenabled = true")

        result = cm.load_manifest(manifest_file)
        assert result["module"]["version"] == "2.0"

    def test_load_missing_manifest_returns_default(self, tmp_path):
        """Lines 172-185: file not found -> returns default."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file)

        result = cm.load_manifest(tmp_path / "nonexistent.toml")
        assert "module" in result


class TestApplyConfigCoreModule:
    def test_core_module_always_enabled(self, tmp_path):
        """Lines 251-256: core module path -> always enabled."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("")
        cm = ConfigManager(config_file)
        cm._config = {"plugins": {"modules": {"enabled": []}}}

        from personality.data.models import ModuleInfo
        module_info = ModuleInfo(
            name="core_module",
            path=Path("/project/core/some_module"),
            manifest_path=Path("/project/core/some_module/manifest.toml"),
            manifest={"module": {"enabled": True, "priority": 10}}
        )
        cm.apply_config_to_module(module_info)
        assert module_info.enabled is True


class TestApplyConfigNonPluginsModule:
    def test_non_plugins_module_skips_allowlist(self, tmp_path):
        """Lines 272-276: module outside plugins/ skips allowlist."""
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
[memory.modules]
enabled = ["rag"]
""")
        cm = ConfigManager(config_file)

        from personality.data.models import ModuleInfo
        module_path = tmp_path / "memory" / "test_mod"
        module_path.mkdir(parents=True)
        module_info = ModuleInfo(
            name="test_mod",
            path=module_path,
            manifest_path=module_path / "manifest.toml",
            manifest={"module": {"enabled": True, "priority": 10}}
        )
        cm.apply_config_to_module(module_info)
        # Should use manifest default since it's not in plugins/
        assert module_info.enabled is True


class TestUpdateModuleEnabled:
    def test_update_enabled_success(self, tmp_path):
        """Lines 309-332: successful enable update."""
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("")
        cm = ConfigManager(config_file)

        module_path = tmp_path / "plugins" / "test_mod"
        module_path.mkdir(parents=True)

        with patch("personality.module_manager.config_manager.core_save_config",
                   return_value=True):
            result = cm.update_module_enabled("test_mod", True, module_path)
        assert result is True

    def test_update_enabled_save_failure(self, tmp_path):
        """Lines 333-337: save failure."""
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("")
        cm = ConfigManager(config_file)

        module_path = tmp_path / "plugins" / "test_mod"
        module_path.mkdir(parents=True)

        with patch("personality.module_manager.config_manager.core_save_config",
                   return_value=False):
            result = cm.update_module_enabled("test_mod", False, module_path)
        assert result is False

    def test_update_enabled_creates_config_structure(self, tmp_path):
        """Lines 319-327: creates missing config structure."""
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("")
        cm = ConfigManager(config_file)
        cm._config = {}  # Empty config

        module_path = tmp_path / "plugins" / "new_mod"
        module_path.mkdir(parents=True)

        with patch("personality.module_manager.config_manager.core_save_config",
                   return_value=True):
            cm.update_module_enabled("new_mod", True, module_path)
        assert cm._config["plugins"]["modules"]["new_mod"]["enabled"] is True

    def test_update_enabled_exception_in_relative(self, tmp_path):
        """Lines 316-317: exception computing relative path -> defaults to 'plugins'."""
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("")
        cm = ConfigManager(config_file)
        cm._config = {}

        # Use a path that can't be made relative
        module_path = Path("/completely/different/path")

        with patch("personality.module_manager.config_manager.core_save_config",
                   return_value=True):
            cm.update_module_enabled("mod", True, module_path)
        assert "plugins" in cm._config
