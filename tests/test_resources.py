"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_resources.py
Description: Tests per core/resources.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestGetResourcePath:

    def test_dev_mode_finds_existing_file(self, tmp_path):
        """Via __file__ mode, returns path to existing resource."""
        from core.resources import _get_resource_via_file

        # Use a known package and its __init__.py
        result = _get_resource_via_file("core", "__init__.py")
        assert result.exists()

    def test_dev_mode_raises_for_missing_file(self):
        from core.resources import _get_resource_via_file

        with pytest.raises(FileNotFoundError):
            _get_resource_via_file("core", "nonexistent_file_xyz.txt")

    def test_dev_mode_raises_for_invalid_package(self):
        from core.resources import _get_resource_via_file

        with pytest.raises(ImportError):
            _get_resource_via_file("nonexistent_package_xyz", "file.txt")

    def test_importlib_mode_finds_file(self):
        """Via importlib.resources, returns correct path."""
        from core.resources import _get_resource_via_importlib

        # Find __init__.py of core package
        result = _get_resource_via_importlib("core", "__init__.py")
        assert result.exists()

    def test_importlib_raises_for_missing_file(self):
        from core.resources import _get_resource_via_importlib

        with pytest.raises(FileNotFoundError):
            _get_resource_via_importlib("core", "this_does_not_exist.html")

    def test_get_resource_path_uses_importlib(self):
        from core.resources import get_resource_path

        result = get_resource_path("core", "__init__.py")
        assert result.exists()

    def test_get_resource_path_no_importlib_falls_back(self):
        """When use_importlib=False, uses __file__ mode."""
        from core.resources import get_resource_path

        result = get_resource_path("core", "__init__.py", use_importlib=False)
        assert result.exists()

    def test_get_resource_path_importlib_failure_falls_back(self):
        """When importlib fails, falls back to __file__ mode."""
        from core.resources import get_resource_path

        with patch("core.resources._get_resource_via_importlib", side_effect=Exception("importlib fail")):
            result = get_resource_path("core", "__init__.py")

        assert result.exists()

    def test_get_resource_path_raises_when_all_fail(self):
        from core.resources import get_resource_path

        with patch("core.resources._get_resource_via_importlib", side_effect=Exception("fail1")), \
             patch("core.resources._get_resource_via_file", side_effect=Exception("fail2")), \
             patch("core.resources._get_resource_via_repo_root", side_effect=Exception("fail3")):
            with pytest.raises(RuntimeError):
                get_resource_path("core", "nonexistent.html")

    def test_repo_root_fallback(self):
        from core.resources import _get_resource_via_repo_root

        # core/__init__.py should be findable via repo root
        result = _get_resource_via_repo_root("core", "__init__.py")
        assert result.exists()

    def test_repo_root_raises_for_missing(self):
        from core.resources import _get_resource_via_repo_root

        with pytest.raises(FileNotFoundError):
            _get_resource_via_repo_root("core", "this_file_does_not_exist_xyz.txt")

    def test_importlib_none_raises_import_error(self):
        """When files is None (no importlib.resources), raises ImportError."""
        import core.resources as res_mod

        with patch.object(res_mod, "files", None):
            from core.resources import _get_resource_via_importlib
            with pytest.raises(ImportError):
                _get_resource_via_importlib("core", "__init__.py")
