"""
Tests for core/paths.py facade module.
Verifies that the facade re-exports all expected symbols from core.paths.
"""

import pytest


class TestPathsFacade:
    """Test the core.paths facade module."""

    def test_import_facade(self):
        """Test that core.paths can be imported."""
        import core.paths as paths_mod
        assert paths_mod is not None

    def test_all_exports(self):
        """Test __all__ contains all expected symbols."""
        from core.paths import __all__
        expected = [
            "get_repo_root",
            "reset_repo_root_cache",
            "DetectionMethod",
            "REQUIRED_MARKERS",
            "OPTIONAL_MARKERS",
            "NEXE_CORE_DIRS",
            "get_project_path",
            "get_core_path",
            "get_memory_path",
            "get_personality_path",
            "get_storage_path",
            "get_logs_dir",
            "get_config_dir",
            "get_data_dir",
            "get_cache_dir",
            "get_system_logs_dir",
            "get_core_root",
        ]
        for name in expected:
            assert name in __all__, f"{name} missing from __all__"

    def test_get_repo_root_exported(self):
        """Test get_repo_root is accessible from facade."""
        from core.paths import get_repo_root
        assert callable(get_repo_root)

    def test_reset_repo_root_cache_exported(self):
        """Test reset_repo_root_cache is accessible from facade."""
        from core.paths import reset_repo_root_cache
        assert callable(reset_repo_root_cache)

    def test_detection_method_exported(self):
        """Test DetectionMethod is accessible from facade."""
        from core.paths import DetectionMethod
        assert DetectionMethod is not None

    def test_required_markers_exported(self):
        """Test REQUIRED_MARKERS is accessible from facade."""
        from core.paths import REQUIRED_MARKERS
        assert isinstance(REQUIRED_MARKERS, (list, tuple, set, frozenset))

    def test_helper_functions_exported(self):
        """Test all helper path functions are exported."""
        from core.paths import (
            get_project_path,
            get_core_path,
            get_memory_path,
            get_personality_path,
            get_storage_path,
            get_logs_dir,
            get_config_dir,
            get_data_dir,
            get_cache_dir,
            get_system_logs_dir,
            get_core_root,
        )
        for fn in [
            get_project_path, get_core_path, get_memory_path,
            get_personality_path, get_storage_path, get_logs_dir,
            get_config_dir, get_data_dir, get_cache_dir,
            get_system_logs_dir, get_core_root,
        ]:
            assert callable(fn)
