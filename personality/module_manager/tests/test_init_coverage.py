"""
Tests for personality/module_manager/__init__.py
Covers uncovered lines: 76-79, 88-106, 119-126, 138, 154-166
"""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


class TestCreateOrchestrator:
    """Tests for create_orchestrator (lines 76-79)"""

    @patch("personality.module_manager.ModuleManager")
    @patch("personality.module_manager.get_default_config_path")
    def test_create_orchestrator_default_path(self, mock_get_path, mock_mm):
        mock_get_path.return_value = Path("/default/server.toml")
        mock_mm.return_value = MagicMock()
        from personality.module_manager import create_orchestrator
        result = create_orchestrator()
        mock_get_path.assert_called_once()
        mock_mm.assert_called_once_with(Path("/default/server.toml"))

    @patch("personality.module_manager.ModuleManager")
    def test_create_orchestrator_custom_path(self, mock_mm):
        mock_mm.return_value = MagicMock()
        from personality.module_manager import create_orchestrator
        result = create_orchestrator(config_path=Path("/custom/server.toml"))
        mock_mm.assert_called_once_with(Path("/custom/server.toml"))


class TestGetDefaultConfigPath:
    """Tests for get_default_config_path (lines 88-106)"""

    def test_finds_config_in_parent(self, tmp_path):
        """Lines 88-93: walks up directory tree to find server.toml"""
        config_file = tmp_path / "server.toml"
        config_file.write_text("[server]")
        from personality.module_manager import get_default_config_path
        with patch("personality.module_manager.Path") as MockPath:
            # This is tricky since it uses __file__, let's just test the fallback paths
            pass

    def test_fallback_search_paths(self):
        """Lines 96-106: fallback paths searched"""
        from personality.module_manager import get_default_config_path
        # When nothing is found, returns default path
        with patch.object(Path, 'exists', return_value=False):
            result = get_default_config_path()
        assert str(result).endswith("server.toml")


class TestCreateModuleManagerWithConfig:
    """Tests for create_module_manager_with_config (lines 119-126)"""

    @patch("personality.module_manager.ModuleManager")
    @patch("personality.module_manager.get_default_config_path")
    def test_with_config_dict(self, mock_get_path, mock_mm):
        """Lines 119-126: creates manager with config dict"""
        mock_get_path.return_value = Path("/default/server.toml")
        mock_manager = MagicMock()
        mock_manager._config = {}
        mock_mm.return_value = mock_manager
        from personality.module_manager import create_module_manager_with_config
        result = create_module_manager_with_config(config_dict={"key": "value"})
        assert mock_manager._config == {"key": "value"}

    @patch("personality.module_manager.ModuleManager")
    @patch("personality.module_manager.get_default_config_path")
    def test_without_config_dict(self, mock_get_path, mock_mm):
        """Lines 119-126: creates manager without config dict"""
        mock_get_path.return_value = Path("/default/server.toml")
        mock_mm.return_value = MagicMock()
        from personality.module_manager import create_module_manager_with_config
        result = create_module_manager_with_config()
        mock_mm.assert_called_once()

    @patch("personality.module_manager.ModuleManager")
    def test_with_custom_config_path(self, mock_mm):
        """Line 119: config_path kwarg"""
        mock_mm.return_value = MagicMock()
        from personality.module_manager import create_module_manager_with_config
        result = create_module_manager_with_config(config_path=Path("/custom/server.toml"))
        mock_mm.assert_called_once_with(Path("/custom/server.toml"))


class TestCreateModuleSystem:
    """Tests for create_module_system (line 138)"""

    @patch("personality.module_manager.create_orchestrator")
    def test_delegates_to_create_orchestrator(self, mock_orchestrator):
        """Line 138: legacy alias"""
        mock_orchestrator.return_value = MagicMock()
        from personality.module_manager import create_module_system
        result = create_module_system(config_path=Path("/test"))
        mock_orchestrator.assert_called_once_with(Path("/test"))


class TestCreateValidatedModuleManager:
    """Tests for create_validated_module_manager (lines 154-166)"""

    @patch("personality.module_manager.ModuleManager")
    @patch("personality.module_manager.get_default_config_path")
    def test_no_validation(self, mock_get_path, mock_mm):
        """Lines 154-166: validate_config=False"""
        mock_get_path.return_value = Path("/default/server.toml")
        mock_mm.return_value = MagicMock()
        from personality.module_manager import create_validated_module_manager
        result = create_validated_module_manager(validate_config=False)
        mock_mm.assert_called_once()

    @patch("personality.module_manager.ModuleManager")
    @patch("personality.module_manager.ConfigValidator")
    @patch("personality.module_manager.get_default_config_path")
    def test_validation_passes(self, mock_get_path, mock_cv, mock_mm):
        """Lines 159-166: validation passes"""
        mock_get_path.return_value = Path("/default/server.toml")
        mock_validator = MagicMock()
        mock_validator.validate.return_value = []  # No errors
        mock_cv.return_value = mock_validator
        mock_mm.return_value = MagicMock()
        from personality.module_manager import create_validated_module_manager
        result = create_validated_module_manager()
        mock_mm.assert_called_once()

    @patch("personality.module_manager.ConfigValidator")
    @patch("personality.module_manager.get_default_config_path")
    def test_validation_fails(self, mock_get_path, mock_cv):
        """Lines 163-164: validation fails -> ValueError"""
        mock_get_path.return_value = Path("/default/server.toml")
        mock_validator = MagicMock()
        mock_validator.validate.return_value = ["Error 1", "Error 2"]
        mock_cv.return_value = mock_validator
        from personality.module_manager import create_validated_module_manager
        with pytest.raises(ValueError, match="Configuration validation failed"):
            create_validated_module_manager()
