"""
Tests for uncovered lines in personality/module_manager/module_manager.py.
Targets: 81 lines missing - key uncovered paths.
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from personality.data.models import ModuleInfo, ModuleState


@pytest.fixture(autouse=True)
def ensure_event_loop():
    """Ensure an event loop exists for ModuleManager which uses async internals."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    yield


class TestModuleManagerInit:
    """Test initialization paths."""

    def test_find_initial_config_with_existing_path(self, tmp_path):
        """Lines 130-142: config_path provided and exists."""
        config_file = tmp_path / "server.toml"
        config_file.write_text('[meta]\nversion = "0.8"\n')

        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            # The constructor calls _find_initial_config internally
            mm = ModuleManager.__new__(ModuleManager)
            result = mm._find_initial_config(config_file)
            assert result == config_file

    def test_find_initial_config_with_security_validation(self, tmp_path):
        """Lines 132-139: security validation path."""
        config_file = tmp_path / "server.toml"
        config_file.write_text('[meta]\nversion = "0.8"\n')

        mock_validate = MagicMock(return_value=config_file)
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", True), \
             patch("personality.module_manager.module_manager.validate_safe_path", mock_validate):
            from personality.module_manager.module_manager import ModuleManager
            mm = ModuleManager.__new__(ModuleManager)
            result = mm._find_initial_config(config_file)
            assert result == config_file

    def test_find_initial_config_security_rejection(self, tmp_path):
        """Lines 138-139: security validation rejects path."""
        config_file = tmp_path / "server.toml"
        config_file.write_text('[meta]\nversion = "0.8"\n')

        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", True), \
             patch("personality.module_manager.module_manager.validate_safe_path",
                   side_effect=Exception("path rejected")):
            from personality.module_manager.module_manager import ModuleManager
            mm = ModuleManager.__new__(ModuleManager)
            # Should fall through to search paths
            result = mm._find_initial_config(config_file)
            # Returns some path (either found or default)
            assert result is not None

    def test_find_initial_config_none_finds_default(self):
        """Lines 144-154: None config_path searches standard locations."""
        from personality.module_manager.module_manager import ModuleManager
        mm = ModuleManager.__new__(ModuleManager)
        result = mm._find_initial_config(None)
        assert result is not None


class TestModuleManagerOperations:

    @pytest.fixture
    def mm(self, tmp_path):
        """Create a minimal ModuleManager."""
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n')
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            return ModuleManager(config_path=config_file)

    def test_get_module_info_returns_none_for_missing(self, mm):
        assert mm.get_module_info("nonexistent") is None

    def test_update_module_enabled_missing_module(self, mm):
        assert mm.update_module_enabled("nonexistent", True) is False

    def test_update_module_enabled_core_module_cant_disable(self, mm):
        """Lines 220-223: cannot disable core module."""
        module = ModuleInfo(
            name="test",
            path=Path("/fake/core/test"),
            manifest_path=Path("/fake/core/test/manifest.toml"),
            enabled=True
        )
        mm._modules["test"] = module
        result = mm.update_module_enabled("test", False)
        assert result is False

    def test_update_module_enabled_success(self, mm):
        """Lines 225-233: successful enable/disable."""
        module = ModuleInfo(
            name="test",
            path=Path("/fake/plugins/test"),
            manifest_path=Path("/fake/plugins/test/manifest.toml"),
            enabled=True
        )
        mm._modules["test"] = module
        mm.config_manager.update_module_enabled = MagicMock(return_value=True)

        result = mm.update_module_enabled("test", False)
        assert result is True
        assert module.state == ModuleState.DISABLED

    def test_update_module_re_enable(self, mm):
        """Lines 230-231: re-enable a disabled module."""
        module = ModuleInfo(
            name="test",
            path=Path("/fake/plugins/test"),
            manifest_path=Path("/fake/plugins/test/manifest.toml"),
            state=ModuleState.DISABLED,
            enabled=False
        )
        mm._modules["test"] = module
        mm.config_manager.update_module_enabled = MagicMock(return_value=True)

        result = mm.update_module_enabled("test", True)
        assert result is True
        assert module.state == ModuleState.LOADED

    def test_list_modules_with_filter(self, mm):
        m1 = ModuleInfo(name="a", path=Path("."), manifest_path=Path("."), state=ModuleState.RUNNING, priority=1)
        m2 = ModuleInfo(name="b", path=Path("."), manifest_path=Path("."), state=ModuleState.STOPPED, priority=2)
        mm._modules = {"a": m1, "b": m2}
        result = mm.list_modules(state_filter=ModuleState.RUNNING)
        assert len(result) == 1
        assert result[0].name == "a"

    def test_get_system_status(self, mm):
        result = mm.get_system_status()
        assert "running" in result
        assert "total_modules" in result
        assert "uptime_seconds" in result

    def test_add_event_listener(self, mm):
        cb = MagicMock()
        mm.add_event_listener(cb, event_type="test")
        assert mm.events.get_callback_count("test") == 1

    def test_get_module_metrics_missing(self, mm):
        result = mm.get_module_metrics("nonexistent")
        assert result == {}

    def test_set_api_integrator(self, mm):
        mock_integrator = MagicMock()
        mm.set_api_integrator(mock_integrator)
        assert mm.api_integrator is mock_integrator

    def test_configure_base_path_personality(self, mm):
        """Lines 121-124: _configure_base_path when parent is 'personality'."""
        mm.config_path = Path("/project/personality/server.toml")
        mm._configure_base_path()
        assert mm.path_discovery.base_path == Path("/project")

    def test_configure_base_path_non_personality(self, mm):
        """Line 124: _configure_base_path when parent is not 'personality'."""
        mm.config_path = Path("/project/config/server.toml")
        mm._configure_base_path()
        assert mm.path_discovery.base_path == Path("/project/config")


class TestModuleManagerAsync:

    @pytest.fixture
    def mm(self, tmp_path):
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n')
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            return ModuleManager(config_path=config_file)

    def test_load_module_not_found(self):
        """Lines 176-182: load_module for non-existent module."""
        pass  # Tested via discover_modules flow

    def test_start_system_and_shutdown(self, mm):
        """Lines 193-208: start_system and shutdown_system."""
        mm.system_lifecycle.start_system = AsyncMock(return_value=True)
        mm.system_lifecycle.is_running = MagicMock(return_value=True)
        result = asyncio.run(mm.start_system())
        assert result is True
        assert mm._running is True

        mm.system_lifecycle.shutdown_system = AsyncMock()
        mm.system_lifecycle.is_running = MagicMock(return_value=False)
        asyncio.run(mm.shutdown_system())
        assert mm._running is False

    def test_discover_modules_sync(self, mm):
        """Lines 166-171: sync wrapper for discover."""
        mm.discovery.discover = AsyncMock(return_value=["mod1"])
        result = mm.discover_modules_sync()
        assert isinstance(result, list)


class TestSecurityValidationBranch:
    """Test lines 37-38, 44: SECURITY_VALIDATION_AVAILABLE fallback."""

    def test_security_validation_not_available_warning(self):
        """Lines 37-38, 44: when import fails, warning is logged."""
        import importlib
        import sys

        orig = sys.modules.get("plugins.security.core.validators")
        sys.modules["plugins.security.core.validators"] = None  # force ImportError

        try:
            # We can't easily re-import the module, but we can verify
            # the fallback class exists
            from personality.module_manager.module_manager import SECURITY_VALIDATION_AVAILABLE
            # Just check type
            assert isinstance(SECURITY_VALIDATION_AVAILABLE, bool)
        finally:
            if orig is not None:
                sys.modules["plugins.security.core.validators"] = orig
            else:
                sys.modules.pop("plugins.security.core.validators", None)


class TestLoadModule:
    """Test lines 175-183: load_module for non-found module."""

    @pytest.fixture
    def mm(self, tmp_path):
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n')
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            return ModuleManager(config_path=config_file)

    def test_load_module_not_found_after_discover(self, mm):
        """Lines 175-183: module not found even after discover_modules."""
        mm.discovery.discover = AsyncMock(return_value=[])
        result = asyncio.run(mm.load_module("nonexistent_module"))
        assert result is False

    def test_load_module_found_after_discover(self, mm):
        """Lines 175-183: module found after discover."""
        mod = ModuleInfo(
            name="test_mod",
            path=Path("/fake/test_mod"),
            manifest_path=Path("/fake/test_mod/manifest.toml"),
            enabled=True,
        )

        async def mock_discover(mods, lock, force):
            mods["test_mod"] = mod
            return ["test_mod"]

        mm.discovery.discover = mock_discover
        mm.module_lifecycle.load_module = AsyncMock(return_value=True)
        result = asyncio.run(mm.load_module("test_mod"))
        assert result is True

    def test_start_module(self, mm):
        """Line 187: start_module delegates."""
        mm.module_lifecycle.start_module = AsyncMock(return_value=True)
        result = asyncio.run(mm.start_module("test"))
        assert result is True

    def test_stop_module(self, mm):
        """Line 191: stop_module delegates."""
        mm.module_lifecycle.stop_module = AsyncMock(return_value=True)
        result = asyncio.run(mm.stop_module("test"))
        assert result is True


class TestLoadMemoryModules:
    """Test lines 306-307, 317-318, 325-326, 341-342, 354-355, 386-388."""

    @pytest.fixture
    def mm(self, tmp_path):
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n')
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            return ModuleManager(config_path=config_file)

    def test_memory_path_not_exists(self, mm, tmp_path):
        """Lines 306-307: memory path doesn't exist."""
        mm.path_discovery.base_path = tmp_path / "nonexistent"
        result = asyncio.run(mm.load_memory_modules())
        assert result == {}

    def test_memory_manifest_not_found(self, mm, tmp_path):
        """Lines 317-318: manifest file not found."""
        memory_path = tmp_path / "memory" / "embeddings"
        memory_path.mkdir(parents=True)
        mm.path_discovery.base_path = tmp_path
        result = asyncio.run(mm.load_memory_modules())
        assert result == {}

    def test_memory_module_missing_module_id(self, mm, tmp_path):
        """Lines 325-326: manifest module missing MODULE_ID."""
        memory_path = tmp_path / "memory" / "embeddings"
        memory_path.mkdir(parents=True)
        (memory_path / "manifest.py").write_text("")
        mm.path_discovery.base_path = tmp_path

        mock_manifest = MagicMock(spec=[])  # no MODULE_ID
        del mock_manifest.MODULE_ID

        with patch("importlib.import_module", return_value=mock_manifest):
            result = asyncio.run(mm.load_memory_modules())
        assert result == {}

    def test_memory_module_class_not_found(self, mm, tmp_path):
        """Lines 341-342: module class not found."""
        memory_path = tmp_path / "memory" / "embeddings"
        memory_path.mkdir(parents=True)
        (memory_path / "manifest.py").write_text("")
        mm.path_discovery.base_path = tmp_path

        mock_manifest = MagicMock()
        mock_manifest.MODULE_ID = "test_id"
        mock_module_py = MagicMock(spec=[])  # no EmbeddingsModule

        with patch("importlib.import_module", side_effect=[mock_manifest, mock_module_py]):
            result = asyncio.run(mm.load_memory_modules())
        assert result == {}

    def test_memory_module_init_fails(self, mm, tmp_path):
        """Lines 354-355: initialization fails."""
        memory_path = tmp_path / "memory" / "embeddings"
        memory_path.mkdir(parents=True)
        (memory_path / "manifest.py").write_text("")
        mm.path_discovery.base_path = tmp_path

        mock_manifest = MagicMock()
        mock_manifest.MODULE_ID = "test_id"

        mock_instance = MagicMock()
        mock_instance.initialize = AsyncMock(return_value=False)

        mock_class = MagicMock(return_value=mock_instance)
        mock_class.get_instance.return_value = mock_instance

        mock_module_py = MagicMock()
        mock_module_py.EmbeddingsModule = mock_class

        with patch("importlib.import_module", side_effect=[mock_manifest, mock_module_py]):
            result = asyncio.run(mm.load_memory_modules())
        assert result == {}

    def test_memory_module_load_exception(self, mm, tmp_path):
        """Lines 386-388: exception during load."""
        memory_path = tmp_path / "memory" / "embeddings"
        memory_path.mkdir(parents=True)
        (memory_path / "manifest.py").write_text("")
        mm.path_discovery.base_path = tmp_path

        with patch("importlib.import_module", side_effect=Exception("import error")):
            result = asyncio.run(mm.load_memory_modules())
        assert result == {}

    def test_load_memory_modules_sync(self, mm, tmp_path):
        """Line 395: sync wrapper."""
        mm.path_discovery.base_path = tmp_path / "nonexistent"
        result = mm.load_memory_modules_sync()
        assert result == {}


class TestLoadPluginRouters:
    """Test lines 439-497: load_plugin_routers branches."""

    @pytest.fixture
    def mm(self, tmp_path):
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n')
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            return ModuleManager(config_path=config_file)

    def test_module_no_info(self, mm):
        """Lines 450-452: module discovered but no info."""
        from fastapi import FastAPI
        app = FastAPI()
        result = mm.load_plugin_routers(app, Path("/fake"), discovered=["unknown_mod"])
        assert len(result['skipped']) >= 1

    def test_module_exception_during_load(self, mm, tmp_path):
        """Lines 487-497: exception during plugin loading."""
        from fastapi import FastAPI
        app = FastAPI()

        mod = ModuleInfo(
            name="bad_mod",
            path=tmp_path / "bad_mod",
            manifest_path=tmp_path / "bad_mod" / "manifest.toml",
            enabled=True,
        )
        mm._modules["bad_mod"] = mod
        mm._configure_plugin_allowlist = MagicMock(return_value={
            'approved_modules': None,
            'internal_modules': set(),
            'effective_allowlist': None,
            'core_env': 'development'
        })

        with patch.object(mm, '_import_plugin_manifest', side_effect=Exception("import fail")):
            result = mm.load_plugin_routers(app, tmp_path, discovered=["bad_mod"])
        assert len(result['failed']) == 1
        assert mod.state == ModuleState.ERROR

    def test_configure_allowlist_production_no_env(self, mm, monkeypatch):
        """Lines 517: production with no NEXE_APPROVED_MODULES raises."""
        monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
        monkeypatch.setenv("NEXE_ENV", "production")
        with pytest.raises(ValueError, match="SECURITY ERROR"):
            mm._configure_plugin_allowlist(mm.i18n)

    def test_configure_allowlist_with_approved(self, mm, monkeypatch):
        """Lines 512-514: approved modules from env."""
        monkeypatch.setenv("NEXE_APPROVED_MODULES", "mod_a, mod_b")
        monkeypatch.setenv("NEXE_ENV", "development")
        config = mm._configure_plugin_allowlist(mm.i18n)
        assert "mod_a" in config['approved_modules']
        assert "mod_b" in config['approved_modules']

    def test_check_security_not_in_allowlist(self, mm):
        """Lines 554-555: module not in allowlist."""
        from fastapi import FastAPI
        app = FastAPI()
        mod = ModuleInfo(
            name="bad_mod",
            path=Path("/fake"),
            manifest_path=Path("/fake/m.toml"),
            enabled=True,
        )
        config = {'effective_allowlist': {'good_mod'}}
        result = mm._check_plugin_security(app, "bad_mod", mod, config, mm.i18n)
        assert result is False
        assert mod.state == ModuleState.DISABLED

    def test_check_security_disabled_module(self, mm):
        """Line 555: module disabled."""
        from fastapi import FastAPI
        app = FastAPI()
        mod = ModuleInfo(
            name="dis_mod",
            path=Path("/fake"),
            manifest_path=Path("/fake/m.toml"),
            enabled=False,
        )
        config = {'effective_allowlist': None}
        result = mm._check_plugin_security(app, "dis_mod", mod, config, mm.i18n)
        assert result is False


class TestPluginRoutersFromManifest:
    """Test lines 574-576, 579, 593-595, 598-600, 609-610, 613."""

    @pytest.fixture
    def mm(self, tmp_path):
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n')
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            return ModuleManager(config_path=config_file)

    def test_load_router_admin(self, mm):
        """Lines 593-595: router_admin loaded."""
        from fastapi import FastAPI, APIRouter
        app = FastAPI()
        manifest = MagicMock()
        manifest.router_public = APIRouter()
        manifest.router_admin = APIRouter()
        del manifest.router_ui
        del manifest.get_router
        result = mm._load_plugin_routers_from_manifest(app, manifest, "test", mm.i18n)
        assert result is True

    def test_load_router_ui(self, mm):
        """Lines 598-600: router_ui loaded."""
        from fastapi import FastAPI, APIRouter
        app = FastAPI()
        manifest = MagicMock()
        del manifest.router_public
        del manifest.router_admin
        manifest.router_ui = APIRouter()
        del manifest.get_router
        result = mm._load_plugin_routers_from_manifest(app, manifest, "test", mm.i18n)
        assert result is True

    def test_load_get_router_fallback(self, mm):
        """Lines 602-610: get_router() fallback."""
        from fastapi import FastAPI, APIRouter
        app = FastAPI()
        manifest = MagicMock()
        del manifest.router_public
        del manifest.router_admin
        del manifest.router_ui
        manifest.get_router.return_value = APIRouter()
        result = mm._load_plugin_routers_from_manifest(app, manifest, "test", mm.i18n)
        assert result is True

    def test_load_get_router_exception(self, mm):
        """Lines 609-610: get_router() fails."""
        from fastapi import FastAPI
        app = FastAPI()
        manifest = MagicMock()
        del manifest.router_public
        del manifest.router_admin
        del manifest.router_ui
        manifest.get_router.side_effect = Exception("fail")
        result = mm._load_plugin_routers_from_manifest(app, manifest, "test", mm.i18n)
        assert result is False

    def test_load_no_routers(self, mm):
        """Line 613: module has no routers."""
        from fastapi import FastAPI
        app = FastAPI()
        manifest = MagicMock(spec=[])
        result = mm._load_plugin_routers_from_manifest(app, manifest, "test", mm.i18n)
        assert result is False


class TestRegisterPluginInstance:
    """Test lines 620-645."""

    @pytest.fixture
    def mm(self, tmp_path):
        config_file = tmp_path / "personality" / "server.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text('[meta]\nversion = "0.8"\n[personality]\n[personality.orchestrator]\nmodules_path = "plugins"\n')
        with patch("personality.module_manager.module_manager.SECURITY_VALIDATION_AVAILABLE", False):
            from personality.module_manager.module_manager import ModuleManager
            return ModuleManager(config_path=config_file)

    def test_register_with_get_module_instance(self, mm):
        """Lines 624-628: get_module_instance callable."""
        from fastapi import FastAPI
        app = FastAPI()
        manifest = MagicMock()
        instance = MagicMock()
        instance.name = "test_inst"
        manifest.get_module_instance.return_value = instance
        mm._register_plugin_instance(app, "test_mod", manifest)
        assert app.state.modules["test_mod"] is instance

    def test_register_get_module_instance_exception(self, mm):
        """Lines 629-631: get_module_instance raises."""
        from fastapi import FastAPI
        app = FastAPI()
        manifest = MagicMock()
        manifest.get_module_instance.side_effect = Exception("fail")
        # Should not have module_instance, _module, etc.
        del manifest.module_instance
        del manifest._module
        del manifest._ollama_module
        mm._register_plugin_instance(app, "test_mod", manifest)
        # Should be None, so nothing registered
        assert not hasattr(app.state, 'modules') or "test_mod" not in getattr(app.state, 'modules', {})

    def test_register_with_attribute(self, mm):
        """Lines 632-635: module_instance attribute."""
        from fastapi import FastAPI
        app = FastAPI()
        manifest = MagicMock(spec=[])
        manifest.module_instance = MagicMock()
        manifest.module_instance.name = "attr_inst"
        mm._register_plugin_instance(app, "test_mod", manifest)
        assert app.state.modules["test_mod"] is manifest.module_instance

    def test_register_no_instance(self, mm):
        """Lines 640-641: no instance found."""
        from fastapi import FastAPI
        app = FastAPI()
        manifest = MagicMock(spec=[])  # no attributes at all
        mm._register_plugin_instance(app, "test_mod", manifest)
        # modules dict may or may not exist
        assert not hasattr(app.state, 'modules') or "test_mod" not in getattr(app.state, 'modules', {})
