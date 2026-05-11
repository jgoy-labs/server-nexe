"""
Tests for uncovered lines in core/resources.py.
Targets: lines 20-23, 113, 135
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestResourcesImportFallback:
    """Lines 20-23: importlib_resources fallback for Python < 3.9."""

    def test_files_available_on_current_python(self):
        """Verify files is available on current Python."""
        from core.resources import files
        if sys.version_info >= (3, 9):
            assert files is not None

    def test_importlib_resources_files_none_raises(self):
        """Line 100-103: _get_resource_via_importlib when files is None."""
        from core.resources import _get_resource_via_importlib

        with patch("core.resources.files", None):
            with pytest.raises(ImportError):
                _get_resource_via_importlib("core", "nonexistent.txt")


class TestGetResourceViaImportlib:
    """Line 113: resource_path without __fspath__."""

    def test_resource_path_without_fspath(self):
        """Line 113: falls back to str() when no __fspath__."""
        from core.resources import _get_resource_via_importlib

        # Create a mock resource without __fspath__ attribute
        class FakeResource:
            def __str__(self):
                return "/fake/path/resource.txt"

        mock_files = MagicMock()
        mock_files.return_value = MagicMock()
        mock_files.return_value.__truediv__ = MagicMock(return_value=FakeResource())

        with patch("core.resources.files", mock_files):
            with pytest.raises(FileNotFoundError):
                _get_resource_via_importlib("core", "nonexistent.txt")


class TestGetResourceViaFile:
    """Line 135: package without __file__."""

    def test_package_without_file_attribute(self):
        """Line 134-138: package has no __file__ (namespace package)."""
        from core.resources import _get_resource_via_file

        mock_module = MagicMock(spec=[])  # No __file__ attribute
        with patch("importlib.import_module", return_value=mock_module):
            with pytest.raises(RuntimeError, match="no __file__"):
                _get_resource_via_file("fake_package", "resource.txt")

    def test_package_with_none_file(self):
        """Line 134: __file__ is None."""
        from core.resources import _get_resource_via_file

        mock_module = MagicMock()
        mock_module.__file__ = None
        with patch("importlib.import_module", return_value=mock_module):
            with pytest.raises(RuntimeError, match="no __file__"):
                _get_resource_via_file("fake_package", "resource.txt")
