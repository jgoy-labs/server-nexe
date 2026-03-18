"""
Tests for personality/loading/module_finder.py
Covers uncovered lines: 40-44, 48-63, 67-82
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from personality.loading.module_finder import ModuleFinder


class TestFindApiFile:
    """Tests for find_api_file (lines 40-44)"""

    def test_returns_pattern_match(self):
        """Lines 40-42: pattern match found"""
        finder = ModuleFinder()
        with patch.object(finder, '_find_by_patterns', return_value=Path("/fake/api.py")):
            result = finder.find_api_file(Path("/fake"), "test")
        assert result == Path("/fake/api.py")

    def test_falls_back_to_py_file(self):
        """Lines 43-44: no pattern match, try fallback"""
        finder = ModuleFinder()
        with patch.object(finder, '_find_by_patterns', return_value=None), \
             patch.object(finder, '_find_fallback_py_file', return_value=Path("/fake/module.py")):
            result = finder.find_api_file(Path("/fake"), "test")
        assert result == Path("/fake/module.py")

    def test_returns_none_when_nothing_found(self):
        """Lines 43-44: no pattern match and no fallback"""
        finder = ModuleFinder()
        with patch.object(finder, '_find_by_patterns', return_value=None), \
             patch.object(finder, '_find_fallback_py_file', return_value=None):
            result = finder.find_api_file(Path("/fake"), "test")
        assert result is None


class TestFindByPatterns:
    """Tests for _find_by_patterns (lines 48-63)"""

    def test_finds_matching_py_file(self, tmp_path):
        """Lines 51-61: finds existing .py file matching pattern"""
        finder = ModuleFinder()
        api_file = tmp_path / "api_test.py"
        api_file.write_text("# api")
        result = finder._find_by_patterns(tmp_path, "test")
        assert result == api_file

    def test_returns_none_no_match(self, tmp_path):
        """Line 63: no matching file"""
        finder = ModuleFinder()
        result = finder._find_by_patterns(tmp_path, "nonexistent")
        assert result is None

    def test_skips_non_py_extension(self, tmp_path):
        """Line 56: file exists but is not .py"""
        finder = ModuleFinder()
        # Create a file with a matching pattern name but wrong extension
        txt_file = tmp_path / "api_test.txt"
        txt_file.write_text("not python")
        result = finder._find_by_patterns(tmp_path, "test")
        assert result is None

    def test_skips_directory_with_matching_name(self, tmp_path):
        """Line 55: path exists but is not a file"""
        finder = ModuleFinder()
        dir_path = tmp_path / "api_test.py"
        dir_path.mkdir()
        result = finder._find_by_patterns(tmp_path, "test")
        assert result is None


class TestFindFallbackPyFile:
    """Tests for _find_fallback_py_file (lines 67-82)"""

    def test_finds_fallback_py_file(self, tmp_path):
        """Lines 73-80: finds a valid .py file"""
        finder = ModuleFinder()
        py_file = tmp_path / "some_module.py"
        py_file.write_text("# module")
        result = finder._find_fallback_py_file(tmp_path, "test")
        assert result == py_file

    def test_ignores_test_files(self, tmp_path):
        """Line 75: ignores files starting with test_"""
        finder = ModuleFinder()
        test_file = tmp_path / "test_something.py"
        test_file.write_text("# test")
        result = finder._find_fallback_py_file(tmp_path, "test")
        assert result is None

    def test_ignores_underscore_files(self, tmp_path):
        """Line 75: ignores files starting with _"""
        finder = ModuleFinder()
        private_file = tmp_path / "_internal.py"
        private_file.write_text("# internal")
        result = finder._find_fallback_py_file(tmp_path, "test")
        assert result is None

    def test_ignores_dot_files(self, tmp_path):
        """Line 75: ignores files starting with ."""
        finder = ModuleFinder()
        dot_file = tmp_path / ".hidden.py"
        dot_file.write_text("# hidden")
        result = finder._find_fallback_py_file(tmp_path, "test")
        assert result is None

    def test_ignores_setup_file(self, tmp_path):
        """Line 75: ignores setup.py"""
        finder = ModuleFinder()
        setup_file = tmp_path / "setup.py"
        setup_file.write_text("# setup")
        result = finder._find_fallback_py_file(tmp_path, "test")
        assert result is None

    def test_no_py_files_returns_none(self, tmp_path):
        """Line 82: no py files at all"""
        finder = ModuleFinder()
        result = finder._find_fallback_py_file(tmp_path, "test")
        assert result is None
