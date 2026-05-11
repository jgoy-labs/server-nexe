"""
Tests for personality/loading/module_importer.py
Covers uncovered lines: 45-64, 76-89
"""
import sys
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from personality.loading.module_importer import ModuleImporter


class TestImportModule:
    """Tests for import_module (lines 45-64)"""

    def test_import_valid_module(self, tmp_path):
        """Lines 45-64: successfully import a Python file"""
        importer = ModuleImporter()
        py_file = tmp_path / "test_api.py"
        py_file.write_text("VALUE = 42\n")
        module = importer.import_module(py_file, "test_mod")
        assert module.VALUE == 42

    def test_import_adds_to_sys_modules(self, tmp_path):
        """Line 60: module is added to sys.modules"""
        importer = ModuleImporter()
        py_file = tmp_path / "test_api2.py"
        py_file.write_text("X = 1\n")
        # Get the expected module name prefix
        expected_name = importer.patterns.get_module_name_prefix("test_mod2", id(py_file))
        module = importer.import_module(py_file, "test_mod2")
        assert expected_name in sys.modules

    def test_import_spec_none_raises(self):
        """Lines 51-56: spec is None -> raise ImportError"""
        importer = ModuleImporter()
        with patch("personality.loading.module_importer.importlib.util.spec_from_file_location", return_value=None):
            with pytest.raises(ImportError):
                importer.import_module(Path("/fake/nonexistent.py"), "bad_mod")

    def test_import_spec_loader_none_raises(self):
        """Lines 51-56: spec.loader is None -> raise ImportError"""
        importer = ModuleImporter()
        mock_spec = MagicMock()
        mock_spec.loader = None
        with patch("personality.loading.module_importer.importlib.util.spec_from_file_location", return_value=mock_spec):
            with pytest.raises(ImportError):
                importer.import_module(Path("/fake/bad.py"), "bad_mod")


class TestCleanupModule:
    """Tests for cleanup_module (lines 76-89)"""

    def test_cleanup_removes_matching_modules(self):
        """Lines 76-89: removes modules from sys.modules"""
        importer = ModuleImporter()
        # Inject fake modules
        sys.modules["module_test_cleanup_12345"] = MagicMock()
        sys.modules["some_test_cleanup_extra"] = MagicMock()
        removed = importer.cleanup_module("test_cleanup")
        assert removed >= 2
        assert "module_test_cleanup_12345" not in sys.modules
        assert "some_test_cleanup_extra" not in sys.modules

    def test_cleanup_returns_zero_when_none_found(self):
        """Lines 76-89: no matching modules"""
        importer = ModuleImporter()
        removed = importer.cleanup_module("totally_unique_no_match_xyz")
        assert removed == 0
