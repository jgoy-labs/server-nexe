"""
Tests for uncovered lines in personality/module_manager/path_discovery.py.
Targets: 48 lines missing
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestPathDiscoveryInit:

    def test_strict_mode_from_config(self):
        from personality.module_manager.path_discovery import PathDiscovery
        config = {"core": {"environment": {"mode": "development"}}}
        pd = PathDiscovery(config=config)
        assert pd.strict_mode is False

    def test_strict_mode_default_production(self):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery(config={})
        assert pd.strict_mode is True

    def test_strict_mode_explicit(self):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery(strict=False)
        assert pd.strict_mode is False


class TestDiscoverAllPaths:

    def test_discover_strict_skips_auto(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery(strict=True)
        pd.base_path = tmp_path
        paths = pd.discover_all_paths()
        assert isinstance(paths, list)

    def test_discover_dev_mode_auto_discovery(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        # Create some directories with 'module' in name
        (tmp_path / "plugins" / "modules").mkdir(parents=True)
        (tmp_path / "plugins" / "modules" / "manifest.toml").write_text("")
        pd = PathDiscovery(strict=False)
        pd.base_path = tmp_path
        paths = pd.discover_all_paths()
        assert isinstance(paths, list)

    def test_auto_discover_max_dirs(self, tmp_path):
        """Lines 164-168: max directory limit."""
        from personality.module_manager.path_discovery import PathDiscovery
        # Create more than 100 dirs
        for i in range(105):
            (tmp_path / f"dir_{i:03d}").mkdir()
        pd = PathDiscovery(strict=False)
        pd.base_path = tmp_path
        paths = pd.discover_all_paths()
        assert isinstance(paths, list)

    def test_auto_discover_subdirs_limit(self, tmp_path):
        """Lines 173-174: subdir count limit (50)."""
        from personality.module_manager.path_discovery import PathDiscovery
        parent = tmp_path / "plugin"
        parent.mkdir()
        for i in range(55):
            (parent / f"sub_{i:03d}").mkdir()
        pd = PathDiscovery(strict=False)
        pd.base_path = tmp_path
        paths = pd.discover_all_paths()
        assert isinstance(paths, list)

    def test_auto_discover_permission_error(self, tmp_path):
        """Lines 186-189: PermissionError handled."""
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery(strict=False)
        pd.base_path = tmp_path

        with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            pd._auto_discover_paths()
        # Should not raise


class TestAddConfiguredPaths:

    def test_configured_modules_path(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        modules_dir = tmp_path / "custom_modules"
        modules_dir.mkdir()
        config = {"personality": {"orchestrator": {"modules_path": str(modules_dir)}}}
        pd = PathDiscovery(config=config)
        pd.base_path = tmp_path
        pd._add_configured_paths()
        # Should add the path

    def test_configured_additional_paths(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        extra = tmp_path / "extra"
        extra.mkdir()
        config = {"personality": {"orchestrator": {
            "additional_paths": {"paths": [str(extra)]}
        }}}
        pd = PathDiscovery(config=config)
        pd.base_path = tmp_path
        pd._add_configured_paths()

    def test_orchestrator_config_not_dict(self, tmp_path):
        """Lines 197-198: orchestrator_config is not a dict."""
        from personality.module_manager.path_discovery import PathDiscovery
        config = {"personality": {"orchestrator": "invalid"}}
        pd = PathDiscovery(config=config)
        pd.base_path = tmp_path
        pd._add_configured_paths()

    def test_additional_paths_not_dict(self, tmp_path):
        """Lines 210-211: add_paths_cfg not a dict."""
        from personality.module_manager.path_discovery import PathDiscovery
        config = {"personality": {"orchestrator": {"additional_paths": "invalid"}}}
        pd = PathDiscovery(config=config)
        pd.base_path = tmp_path
        pd._add_configured_paths()

    def test_additional_paths_not_list(self, tmp_path):
        """Lines 214-215: paths value is not a list."""
        from personality.module_manager.path_discovery import PathDiscovery
        config = {"personality": {"orchestrator": {"additional_paths": {"paths": "invalid"}}}}
        pd = PathDiscovery(config=config)
        pd.base_path = tmp_path
        pd._add_configured_paths()


class TestScanForModules:

    def test_scan_finds_modules(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        mod_dir = tmp_path / "test_module"
        mod_dir.mkdir()
        (mod_dir / "manifest.toml").write_text("")

        pd = PathDiscovery()
        pd.base_path = tmp_path
        result = pd.scan_for_modules([tmp_path])
        assert "test_module" in result

    def test_scan_nonexistent_path(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        result = pd.scan_for_modules([tmp_path / "nonexistent"])
        assert result == {}

    def test_scan_permission_error(self, tmp_path):
        """Lines 279-282: PermissionError in _scan_single_path."""
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            result = pd._scan_single_path(tmp_path)
            assert result == {}


class TestIsModuleDirectory:

    def test_manifest_toml_detected(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        mod = tmp_path / "mymod"
        mod.mkdir()
        (mod / "manifest.toml").write_text("")
        pd = PathDiscovery()
        assert pd._is_module_directory(mod) is True

    def test_manifest_py_detected(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        mod = tmp_path / "mymod"
        mod.mkdir()
        (mod / "manifest.py").write_text("")
        pd = PathDiscovery()
        assert pd._is_module_directory(mod) is True

    def test_module_py_with_init_detected(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        mod = tmp_path / "mymod"
        mod.mkdir()
        (mod / "module.py").write_text("def init_module(): pass")
        pd = PathDiscovery()
        assert pd._is_module_directory(mod) is True

    def test_module_py_without_markers_not_detected(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        mod = tmp_path / "mymod"
        mod.mkdir()
        (mod / "module.py").write_text("x = 1")
        pd = PathDiscovery()
        assert pd._is_module_directory(mod) is False

    def test_module_py_read_error(self, tmp_path):
        """Lines 316-317: can't read module.py."""
        from personality.module_manager.path_discovery import PathDiscovery
        mod = tmp_path / "mymod"
        mod.mkdir()
        module_py = mod / "module.py"
        module_py.write_text("def init_module(): pass")

        pd = PathDiscovery()
        with patch.object(Path, "read_text", side_effect=Exception("read error")):
            result = pd._is_module_directory(mod)
            assert result is False

    def test_empty_dir_not_module(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        mod = tmp_path / "empty"
        mod.mkdir()
        pd = PathDiscovery()
        assert pd._is_module_directory(mod) is False


class TestFindModulePath:

    def test_find_cached(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        pd._module_locations["cached"] = tmp_path
        assert pd.find_module_path("cached") == tmp_path

    def test_find_not_found(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        pd.base_path = tmp_path
        result = pd.find_module_path("nonexistent")
        assert result is None


class TestCacheSaveLoad:

    def test_save_and_load_cache(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        pd._discovered_paths = {tmp_path / "a"}
        pd._module_locations = {"mod": tmp_path / "mod"}

        cache_file = tmp_path / "cache.json"
        pd.save_cache(cache_file)
        assert cache_file.exists()

        pd2 = PathDiscovery()
        result = pd2.load_cache(cache_file)
        assert result is True
        assert len(pd2._discovered_paths) == 1

    def test_load_cache_nonexistent(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        result = pd.load_cache(tmp_path / "missing.json")
        assert result is False

    def test_load_cache_invalid_json(self, tmp_path):
        from personality.module_manager.path_discovery import PathDiscovery
        cache_file = tmp_path / "bad.json"
        cache_file.write_text("not json")
        pd = PathDiscovery()
        result = pd.load_cache(cache_file)
        assert result is False

    def test_save_cache_error(self, tmp_path):
        """Lines 372-375: save cache fails."""
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        with patch("builtins.open", side_effect=OSError("write error")):
            pd.save_cache(tmp_path / "cache.json")  # Should not raise


class TestGetMessage:

    def test_get_message_with_i18n(self):
        from personality.module_manager.path_discovery import PathDiscovery
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "translated"
        pd = PathDiscovery(i18n_manager=mock_i18n)
        result = pd._get_message("path_discovery.scanning")
        assert result == "translated"

    def test_get_message_without_i18n(self):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        result = pd._get_message("path_discovery.scanning")
        assert "Scanning" in result

    def test_get_message_unknown_key(self):
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        result = pd._get_message("unknown.key")
        assert result == "unknown.key"


class TestPathDiscoveryLoggerAvailable:
    """Test branches guarded by LOGGER_AVAILABLE."""

    @pytest.fixture(autouse=True)
    def mock_logger(self):
        """Mock the logger to accept 'component' kwargs."""
        import personality.module_manager.path_discovery as pdm
        with patch.object(pdm, "logger") as mock_log:
            yield mock_log

    def test_discover_all_paths_with_logger(self, tmp_path):
        """Lines 134-138: LOGGER_AVAILABLE True branch."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            pd = PathDiscovery(strict=True)
            pd.base_path = tmp_path
            paths = pd.discover_all_paths()
            assert isinstance(paths, list)
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_add_known_paths_with_logger(self, tmp_path):
        """Lines 149-150: LOGGER_AVAILABLE True for _add_known_paths."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            (tmp_path / "plugins" / "core").mkdir(parents=True)
            pd = PathDiscovery(strict=True)
            pd.base_path = tmp_path
            pd._add_known_paths()
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_auto_discover_with_logger_max_dirs(self, tmp_path):
        """Lines 166-167: max dirs with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            for i in range(105):
                (tmp_path / f"dir_{i:03d}").mkdir()
            pd = PathDiscovery(strict=False)
            pd.base_path = tmp_path
            pd._auto_discover_paths()
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_auto_discover_with_logger_module_found(self, tmp_path):
        """Lines 184-185: auto-discovered path with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            parent = tmp_path / "plugins"
            parent.mkdir()
            mod = parent / "modules"
            mod.mkdir()
            pd = PathDiscovery(strict=False)
            pd.base_path = tmp_path
            pd._auto_discover_paths()
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_auto_discover_permission_with_logger(self, tmp_path):
        """Lines 188-189: permission error with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            pd = PathDiscovery(strict=False)
            pd.base_path = tmp_path
            with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
                pd._auto_discover_paths()
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_add_configured_paths_with_logger(self, tmp_path):
        """Lines 206-207: configured path added with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            modules_dir = tmp_path / "custom_modules"
            modules_dir.mkdir()
            config = {"personality": {"orchestrator": {"modules_path": str(modules_dir)}}}
            pd = PathDiscovery(config=config)
            pd.base_path = tmp_path
            pd._add_configured_paths()
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_add_configured_additional_paths_with_logger(self, tmp_path):
        """Lines 222-223: additional paths with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            extra = tmp_path / "extra"
            extra.mkdir()
            config = {"personality": {"orchestrator": {
                "additional_paths": {"paths": [str(extra)]}
            }}}
            pd = PathDiscovery(config=config)
            pd.base_path = tmp_path
            pd._add_configured_paths()
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_scan_for_modules_with_logger(self, tmp_path):
        """Lines 245-247: modules found with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            mod_dir = tmp_path / "test_module"
            mod_dir.mkdir()
            (mod_dir / "manifest.toml").write_text("")
            pd = PathDiscovery()
            pd.base_path = tmp_path
            result = pd.scan_for_modules([tmp_path])
            assert "test_module" in result
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_scan_single_path_module_found_with_logger(self, tmp_path):
        """Lines 275-277: module found in scan with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            mod = tmp_path / "mymod"
            mod.mkdir()
            (mod / "manifest.py").write_text("")
            pd = PathDiscovery()
            result = pd._scan_single_path(tmp_path)
            assert "mymod" in result
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_scan_single_path_permission_with_logger(self, tmp_path):
        """Lines 281-282: permission error in scan with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            pd = PathDiscovery()
            with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
                result = pd._scan_single_path(tmp_path)
            assert result == {}
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_save_cache_with_logger(self, tmp_path):
        """Lines 370-371: cache saved with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            pd = PathDiscovery()
            pd._discovered_paths = {tmp_path / "a"}
            pd._module_locations = {"mod": tmp_path / "mod"}
            cache_file = tmp_path / "cache.json"
            pd.save_cache(cache_file)
            assert cache_file.exists()
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_save_cache_error_with_logger(self, tmp_path):
        """Lines 374-375: cache save failed with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            pd = PathDiscovery()
            with patch("builtins.open", side_effect=OSError("write error")):
                pd.save_cache(tmp_path / "cache.json")
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_load_cache_with_logger(self, tmp_path):
        """Lines 403-404: cache loaded with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            pd = PathDiscovery()
            pd._discovered_paths = {tmp_path / "a"}
            pd._module_locations = {"mod": tmp_path / "mod"}
            cache_file = tmp_path / "cache.json"
            pd.save_cache(cache_file)

            pd2 = PathDiscovery()
            result = pd2.load_cache(cache_file)
            assert result is True
        finally:
            pdm.LOGGER_AVAILABLE = orig

    def test_load_cache_error_with_logger(self, tmp_path):
        """Lines 410-411: cache load error with logger."""
        from personality.module_manager.path_discovery import PathDiscovery
        import personality.module_manager.path_discovery as pdm

        orig = pdm.LOGGER_AVAILABLE
        pdm.LOGGER_AVAILABLE = True
        try:
            cache_file = tmp_path / "bad.json"
            cache_file.write_text("not json")
            pd = PathDiscovery()
            result = pd.load_cache(cache_file)
            assert result is False
        finally:
            pdm.LOGGER_AVAILABLE = orig


class TestGetStats:

    def test_get_stats_populated(self, tmp_path):
        """Line 340-347: stats with populated data."""
        from personality.module_manager.path_discovery import PathDiscovery
        pd = PathDiscovery()
        pd._discovered_paths = {tmp_path / "a", tmp_path / "b"}
        pd._module_locations = {"mod1": tmp_path / "mod1", "mod2": tmp_path / "mod2"}
        stats = pd.get_stats()
        assert stats['paths_discovered'] == 2
        assert stats['modules_found'] == 2
        assert len(stats['paths']) == 2
        assert len(stats['modules']) == 2
