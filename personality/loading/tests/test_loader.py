"""
Tests for personality/loading/loader.py
Covers uncovered lines: 64, 94-154, 163-170, 182-203, 207, 211, 215, 227-237, 241-243
"""
import warnings
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from personality.loading.module_validator import ModuleValidationError


def _make_module_info(name="test_module"):
    from personality.data.models import ModuleInfo
    return ModuleInfo(
        name=name,
        path=Path("/tmp/test_module"),
        manifest_path=Path("/tmp/test_module/manifest.toml"),
        manifest={},
    )


def _create_loader():
    """Create ModuleLoader suppressing deprecation warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from personality.loading.loader import ModuleLoader
        return ModuleLoader(suppress_deprecation=True)


class TestModuleLoaderInit:
    """Tests for __init__ (line 64)"""

    def test_deprecation_warning(self):
        """Line 64: emits DeprecationWarning"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from personality.loading.loader import ModuleLoader
            ModuleLoader()
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1

    def test_suppress_deprecation(self):
        """Line 63: suppress_deprecation=True"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from personality.loading.loader import ModuleLoader
            ModuleLoader(suppress_deprecation=True)
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0


class TestLoadModule:
    """Tests for load_module (lines 94-154)"""

    @pytest.mark.asyncio
    async def test_load_module_success(self):
        """Lines 94-141: successful load"""
        loader = _create_loader()
        info = _make_module_info()
        mock_instance = MagicMock()

        loader.finder.find_api_file = MagicMock(return_value=Path("/fake/api.py"))
        loader.importer.import_module = MagicMock(return_value=MagicMock())
        loader.extractor.extract_module_instance = MagicMock(return_value=mock_instance)
        loader.validator.validate_module = MagicMock()
        loader.lifecycle.initialize_module = AsyncMock()

        result = await loader.load_module(info)
        assert result is mock_instance
        assert loader.is_module_loaded("test_module")

    @pytest.mark.asyncio
    async def test_load_module_no_api_file(self):
        """Lines 103-122: no API file found -> ImportError"""
        loader = _create_loader()
        info = _make_module_info()
        loader.finder.find_api_file = MagicMock(return_value=None)

        with pytest.raises(ImportError):
            await loader.load_module(info)

    @pytest.mark.asyncio
    async def test_load_module_import_error(self):
        """Lines 143-154: import error handled"""
        loader = _create_loader()
        info = _make_module_info()
        loader.finder.find_api_file = MagicMock(return_value=Path("/fake/api.py"))
        loader.importer.import_module = MagicMock(side_effect=ImportError("bad import"))

        with pytest.raises(ImportError):
            await loader.load_module(info)

    @pytest.mark.asyncio
    async def test_load_module_validation_error(self):
        """Lines 143-154: validation error"""
        loader = _create_loader()
        info = _make_module_info()
        loader.finder.find_api_file = MagicMock(return_value=Path("/fake/api.py"))
        loader.importer.import_module = MagicMock(return_value=MagicMock())
        loader.extractor.extract_module_instance = MagicMock(return_value=MagicMock())
        loader.validator.validate_module = MagicMock(side_effect=ModuleValidationError("invalid"))

        with pytest.raises(ImportError):
            await loader.load_module(info)


class TestCleanupFailedLoad:
    """Tests for _cleanup_failed_load (lines 163-170)"""

    def test_cleanup_removes_from_loaded(self):
        """Lines 163-170: cleanup removes module"""
        loader = _create_loader()
        loader._loaded_modules["test_mod"] = MagicMock()
        loader.importer.cleanup_module = MagicMock(return_value=1)
        loader._cleanup_failed_load("test_mod")
        assert "test_mod" not in loader._loaded_modules

    def test_cleanup_nonexistent_module(self):
        """Line 163: cleanup module not in dict"""
        loader = _create_loader()
        loader.importer.cleanup_module = MagicMock(return_value=0)
        loader._cleanup_failed_load("nonexistent")


class TestUnloadModule:
    """Tests for unload_module (lines 182-203)"""

    @pytest.mark.asyncio
    async def test_unload_loaded_module(self):
        """Lines 182-196: unload existing module"""
        loader = _create_loader()
        mock_instance = MagicMock()
        loader._loaded_modules["test_mod"] = mock_instance
        loader.lifecycle.cleanup_module = AsyncMock()
        loader.importer.cleanup_module = MagicMock(return_value=1)

        result = await loader.unload_module("test_mod")
        assert result is True
        assert "test_mod" not in loader._loaded_modules

    @pytest.mark.asyncio
    async def test_unload_not_loaded(self):
        """Lines 182-196: unload module not in loaded dict"""
        loader = _create_loader()
        loader.importer.cleanup_module = MagicMock(return_value=0)
        result = await loader.unload_module("nonexistent")
        assert result is True

    @pytest.mark.asyncio
    async def test_unload_error_returns_false(self):
        """Lines 198-203: error during unload"""
        loader = _create_loader()
        loader._loaded_modules["bad_mod"] = MagicMock()
        loader.lifecycle.cleanup_module = AsyncMock(side_effect=ValueError("cleanup error"))

        result = await loader.unload_module("bad_mod")
        assert result is False


class TestGettersAndStats:
    """Tests for get_loaded_modules, is_module_loaded, get_module_instance, get_loader_stats (lines 207, 211, 215, 241-243)"""

    def test_get_loaded_modules(self):
        """Line 207"""
        loader = _create_loader()
        loader._loaded_modules = {"a": 1, "b": 2}
        assert loader.get_loaded_modules() == ["a", "b"]

    def test_is_module_loaded(self):
        """Line 211"""
        loader = _create_loader()
        loader._loaded_modules["test"] = MagicMock()
        assert loader.is_module_loaded("test") is True
        assert loader.is_module_loaded("other") is False

    def test_get_module_instance(self):
        """Line 215"""
        loader = _create_loader()
        mock = MagicMock()
        loader._loaded_modules["test"] = mock
        assert loader.get_module_instance("test") is mock
        assert loader.get_module_instance("other") is None

    def test_get_loader_stats(self):
        """Lines 241-243"""
        loader = _create_loader()
        loader._loaded_modules = {"mod_a": MagicMock()}
        stats = loader.get_loader_stats()
        assert stats['modules_loaded'] == 1
        assert 'mod_a' in stats['loaded_modules']
        assert 'memory_modules' in stats


class TestReloadModule:
    """Tests for reload_module (lines 227-237)"""

    @pytest.mark.asyncio
    async def test_reload_loaded_module(self):
        """Lines 227-237: reload existing module"""
        loader = _create_loader()
        info = _make_module_info()
        loader._loaded_modules["test_module"] = MagicMock()

        loader.lifecycle.cleanup_module = AsyncMock()
        loader.importer.cleanup_module = MagicMock(return_value=0)
        loader.finder.find_api_file = MagicMock(return_value=Path("/fake/api.py"))
        loader.importer.import_module = MagicMock(return_value=MagicMock())
        mock_instance = MagicMock()
        loader.extractor.extract_module_instance = MagicMock(return_value=mock_instance)
        loader.validator.validate_module = MagicMock()
        loader.lifecycle.initialize_module = AsyncMock()

        result = await loader.reload_module(info)
        assert result is mock_instance

    @pytest.mark.asyncio
    async def test_reload_not_loaded_module(self):
        """Lines 234-237: reload module not yet loaded (just load)"""
        loader = _create_loader()
        info = _make_module_info()

        loader.finder.find_api_file = MagicMock(return_value=Path("/fake/api.py"))
        loader.importer.import_module = MagicMock(return_value=MagicMock())
        mock_instance = MagicMock()
        loader.extractor.extract_module_instance = MagicMock(return_value=mock_instance)
        loader.validator.validate_module = MagicMock()
        loader.lifecycle.initialize_module = AsyncMock()

        result = await loader.reload_module(info)
        assert result is mock_instance
