"""
Tests for personality/loading/module_validator.py

Covers: __init__, validate_module, _validate_api, _validate_ui,
_validate_dependencies. Manifest integrity validation is not implemented
(removed dead no-op), so it is not tested here.
"""
import warnings
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from personality.loading.module_validator import ModuleValidator, ModuleValidationError


def _make_module_info(name="test_module", manifest=None, path=None):
    from personality.data.models import ModuleInfo
    return ModuleInfo(
        name=name,
        path=path or Path("/tmp/test_module"),  # nosemgrep: hardcode.absolute_path
        manifest_path=Path("/tmp/test_module/manifest.toml"),  # nosemgrep: hardcode.absolute_path
        manifest=manifest or {},
    )


class TestModuleValidatorInit:
    """Tests for __init__"""

    def test_init_default(self):
        v = ModuleValidator()
        assert v.i18n is None

    def test_init_with_core_root(self):
        # core_root is accepted for signature compatibility; manifest integrity
        # validation is not implemented (see TODO in module_validator).
        v = ModuleValidator(core_root=Path("/explicit/root"))
        assert v.i18n is None


class TestValidateModule:
    """Tests for validate_module (lines 69-88)"""

    def test_valid_module(self):
        """No validations fail"""
        v = ModuleValidator()
        info = _make_module_info()
        instance = MagicMock()
        v.validate_module(instance, info)  # Should not raise

    def test_none_instance_raises(self):
        """Lines 73-74: instance is None"""
        v = ModuleValidator()
        info = _make_module_info()
        with pytest.raises(ModuleValidationError):
            v.validate_module(None, info)

    def test_api_validation_failure(self):
        """Lines 76, 82-88: API validation fails"""
        v = ModuleValidator()
        manifest = {"api": {"endpoints_auto_discovery": True}}
        info = _make_module_info(manifest=manifest)
        instance = MagicMock(spec=[])  # No router/app/etc
        with pytest.raises(ModuleValidationError):
            v.validate_module(instance, info)

    def test_multiple_validations_combined(self):
        """Lines 82-88: multiple errors combined"""
        v = ModuleValidator()
        manifest = {"api": {"endpoints_auto_discovery": True}}
        info = _make_module_info(manifest=manifest)
        with pytest.raises(ModuleValidationError):
            v.validate_module(None, info)


class TestValidateApi:
    """Tests for _validate_api (lines 93-102 / 104)"""

    def test_no_api_section(self):
        """Line 93: no api section in manifest"""
        v = ModuleValidator()
        validations = []
        v._validate_api(MagicMock(), {}, validations)
        assert len(validations) == 0

    def test_api_auto_discovery_with_router(self):
        """Lines 95-99: has router"""
        v = ModuleValidator()
        validations = []
        instance = MagicMock()
        instance.router = MagicMock()
        v._validate_api(instance, {"api": {"endpoints_auto_discovery": True}}, validations)
        assert len(validations) == 0

    def test_api_auto_discovery_missing_router(self):
        """Lines 101-104: no router/app found"""
        v = ModuleValidator()
        validations = []
        instance = MagicMock(spec=[])  # no router, app, etc.
        v._validate_api(instance, {"api": {"endpoints_auto_discovery": True}}, validations)
        assert len(validations) == 1

    def test_api_auto_discovery_false(self):
        """Line 95: endpoints_auto_discovery is False"""
        v = ModuleValidator()
        validations = []
        v._validate_api(MagicMock(spec=[]), {"api": {"endpoints_auto_discovery": False}}, validations)
        assert len(validations) == 0


class TestValidateUi:
    """Tests for _validate_ui (lines 109-116 / 119)"""

    def test_ui_not_enabled(self):
        """Line 111: ui not enabled"""
        v = ModuleValidator()
        info = _make_module_info(manifest={"ui": {"enabled": False}})
        validations = []
        v._validate_ui(MagicMock(), info, validations)
        assert len(validations) == 0

    def test_ui_enabled_file_exists(self):
        """Lines 111-115: UI enabled and file exists"""
        v = ModuleValidator()
        with patch.object(Path, 'exists', return_value=True):
            info = _make_module_info(
                manifest={"ui": {"enabled": True, "path": "ui", "main_file": "index.html"}}
            )
            validations = []
            v._validate_ui(MagicMock(), info, validations)
        assert len(validations) == 0

    def test_ui_enabled_file_missing(self):
        """Lines 115-119: UI file doesn't exist"""
        v = ModuleValidator()
        with patch.object(Path, 'exists', return_value=False):
            info = _make_module_info(
                manifest={"ui": {"enabled": True, "path": "ui", "main_file": "index.html"}}
            )
            validations = []
            v._validate_ui(MagicMock(), info, validations)
        assert len(validations) == 1
        # The message uses the fallback key with {file} placeholder
        assert len(validations[0]) > 0


class TestValidateDependencies:
    """Tests for _validate_dependencies (lines 166-185)"""

    def test_no_dependencies(self):
        """Lines 166-167: no dependencies section"""
        v = ModuleValidator()
        info = _make_module_info(manifest={})
        v._validate_dependencies(info)  # Should not raise

    def test_all_dependencies_available(self):
        """Lines 170-173: all deps importable"""
        v = ModuleValidator()
        info = _make_module_info(manifest={
            "dependencies": {"external": ["os", "sys"]}
        })
        v._validate_dependencies(info)  # Should not warn

    def test_missing_dependencies_warns(self):
        """Lines 177-183: missing deps trigger warning"""
        v = ModuleValidator()
        info = _make_module_info(manifest={
            "dependencies": {"external": ["nonexistent_pkg_xyz_123"]}
        })
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            v._validate_dependencies(info)
        assert len(w) == 1

    def test_dependency_version_stripped(self):
        """Line 171: version specifiers stripped"""
        v = ModuleValidator()
        info = _make_module_info(manifest={
            "dependencies": {"external": ["os>=1.0", "sys==2.0"]}
        })
        v._validate_dependencies(info)  # Should not warn (os and sys exist)
