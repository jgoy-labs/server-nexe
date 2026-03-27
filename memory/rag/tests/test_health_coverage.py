"""
Additional coverage tests for memory/rag/health.py
Covers: check_qdrant_available exception branches, check_storage_paths not writable,
        check_rag_sources source health exception, check_health exception path,
        check_disk_space warn/fail
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from memory.rag.health import (
    check_qdrant_available,
    check_storage_paths,
    check_rag_sources,
    check_health,
    check_disk_space,
)


class TestCheckQdrantAvailableCoverage:

    def test_qdrant_version_unknown(self):
        """When importlib.metadata can't find version."""
        import importlib.metadata
        with patch.object(importlib.metadata, "version", side_effect=Exception("not found")):
            result = check_qdrant_available()
            assert result["status"] == "pass"

    def test_qdrant_check_returns_result(self):
        """General check returns a result."""
        result = check_qdrant_available()
        assert result["status"] in ["pass", "fail"]
        assert "name" in result


class TestCheckStoragePathsCoverage:

    def test_storage_paths_not_writable(self):
        """When paths exist but are not writable."""
        with patch("memory.rag.health.Path") as MockPath:
            mock_dir = MagicMock()
            mock_dir.mkdir = MagicMock()
            mock_test_file = MagicMock()
            mock_test_file.write_text.side_effect = PermissionError("denied")
            mock_dir.__truediv__ = MagicMock(return_value=mock_test_file)
            MockPath.return_value = mock_dir
            result = check_storage_paths()
            assert result["name"] == "storage_paths"

    def test_storage_paths_exception(self):
        """When path creation raises exception."""
        with patch("core.paths.get_repo_root", side_effect=Exception("filesystem error")):
            result = check_storage_paths()
            assert result["status"] == "fail"


class TestCheckRagSourcesCoverage:

    def test_source_health_exception(self):
        """When a source's health() raises exception."""
        mock_source = MagicMock()
        mock_source.health.side_effect = Exception("health error")

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._sources = {"broken": mock_source}

        result = check_rag_sources(mock_module)
        assert result["status"] == "fail"
        assert "broken" in result["sources"]
        assert result["sources"]["broken"]["status"] == "unhealthy"

    def test_source_degraded_status(self):
        """When a source reports degraded status."""
        mock_source = MagicMock()
        mock_source.health.return_value = {"status": "degraded"}

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._sources = {"degraded_src": mock_source}

        result = check_rag_sources(mock_module)
        assert result["status"] == "fail"


class TestCheckDiskSpaceCoverage:

    def test_disk_space_critical(self):
        """Disk space below critical threshold."""
        mock_usage = MagicMock()
        mock_usage.free = 1 * 1024 ** 3  # 1 GB
        with patch("memory.rag.health.psutil") as mock_psutil:
            mock_psutil.disk_usage.return_value = mock_usage
            result = check_disk_space(min_gb=100.0)
            assert result["status"] == "fail"

    def test_disk_space_warn(self):
        """Disk space in warning range."""
        mock_usage = MagicMock()
        mock_usage.free = 7 * 1024 ** 3  # 7 GB
        with patch("memory.rag.health.psutil") as mock_psutil:
            mock_psutil.disk_usage.return_value = mock_usage
            result = check_disk_space(min_gb=10.0)
            assert result["status"] == "warn"


class TestCheckHealthCoverage:

    def test_check_health_degraded(self):
        """Module with warn status."""
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._sources = {}  # Will cause rag_sources fail
        mock_module.module_id = "TEST"
        mock_module.name = "rag"
        mock_module.version = "0.1"
        mock_module._stats = {}
        # Some checks may return warn
        result = check_health(mock_module)
        assert result["status"] in ["unhealthy", "degraded"]

    def test_check_health_exception(self):
        """When check_health itself raises."""
        mock_module = MagicMock()
        type(mock_module)._initialized = PropertyMock(side_effect=Exception("boom"))

        result = check_health(mock_module)
        assert result["status"] == "unhealthy"
        assert "error" in result["metadata"]
