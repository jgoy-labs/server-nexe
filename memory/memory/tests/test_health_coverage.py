"""
Additional coverage tests for memory/memory/health.py
Covers: check_module_initialized exception, check_flash_storage_paths fail/exception,
        check_ram_available warn/fail/exception, check_cleanup_policies exception,
        check_flash_memory_size warn/not-init/exception, check_persistence_connectivity branches,
        check_pipeline_stats branches, check_health exception path
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from memory.memory.health import (
    check_module_initialized,
    check_flash_storage_paths,
    check_ram_available,
    check_cleanup_policies,
    check_flash_memory_size,
    check_persistence_connectivity,
    check_pipeline_stats,
    check_health,
)


class TestCheckModuleInitializedCoverage:

    def test_exception_returns_fail(self):
        mock_module = MagicMock()
        type(mock_module)._initialized = PropertyMock(side_effect=Exception("boom"))
        result = check_module_initialized(mock_module)
        assert result["status"] == "fail"


class TestCheckFlashStoragePathsCoverage:

    def test_paths_not_writable(self):
        with patch("memory.memory.health.Path") as MockPath:
            mock_dir = MagicMock()
            mock_dir.mkdir = MagicMock()
            mock_test_file = MagicMock()
            mock_test_file.write_text.side_effect = PermissionError("denied")
            mock_dir.__truediv__ = MagicMock(return_value=mock_test_file)
            MockPath.return_value = mock_dir
            result = check_flash_storage_paths()
            assert result["name"] == "storage_paths"

    def test_paths_exception(self):
        with patch("memory.memory.health.Path", side_effect=Exception("fs error")):
            result = check_flash_storage_paths()
            assert result["status"] == "fail"


class TestCheckRamAvailableCoverage:

    def test_ram_warn(self):
        mock_mem = MagicMock()
        mock_mem.available = int(0.7 * 1024**3)  # 0.7 GB
        mock_mem.total = int(8 * 1024**3)
        mock_mem.used = int(7.3 * 1024**3)
        mock_mem.percent = 91.0
        with patch("memory.memory.health.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_mem
            result = check_ram_available(min_gb=1.0)
            assert result["status"] == "warn"

    def test_ram_fail(self):
        mock_mem = MagicMock()
        mock_mem.available = int(0.2 * 1024**3)  # 0.2 GB
        mock_mem.total = int(8 * 1024**3)
        mock_mem.used = int(7.8 * 1024**3)
        mock_mem.percent = 97.5
        with patch("memory.memory.health.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_mem
            result = check_ram_available(min_gb=1.0)
            assert result["status"] == "fail"

    def test_ram_exception(self):
        with patch("memory.memory.health.psutil") as mock_psutil:
            mock_psutil.virtual_memory.side_effect = Exception("psutil error")
            result = check_ram_available()
            assert result["status"] == "fail"


class TestCheckCleanupPoliciesCoverage:

    def test_cleanup_ok(self):
        result = check_cleanup_policies()
        assert result["status"] == "pass"


class TestCheckFlashMemorySizeCoverage:

    def test_not_initialized(self):
        mock_module = MagicMock()
        mock_module._initialized = False
        result = check_flash_memory_size(mock_module)
        assert result["status"] == "warn"

    def test_flash_memory_none(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory = None
        result = check_flash_memory_size(mock_module)
        assert result["status"] == "warn"

    def test_flash_memory_high_cache(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory._store = {f"k{i}": i for i in range(1001)}
        result = check_flash_memory_size(mock_module)
        assert result["status"] == "warn"

    def test_flash_memory_ok(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory._store = {"k1": 1}
        result = check_flash_memory_size(mock_module)
        assert result["status"] == "pass"

    def test_flash_memory_exception(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        type(mock_module._flash_memory)._store = PropertyMock(side_effect=Exception("error"))
        result = check_flash_memory_size(mock_module)
        assert result["status"] == "fail"


class TestCheckPersistenceConnectivityCoverage:

    def test_not_initialized(self):
        mock_module = MagicMock()
        mock_module._initialized = False
        result = check_persistence_connectivity(mock_module)
        assert result["status"] == "warn"

    def test_persistence_none(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._persistence = None
        result = check_persistence_connectivity(mock_module)
        assert result["status"] == "warn"

    def test_both_exist(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._persistence.db_path.exists.return_value = True
        mock_module._persistence.qdrant_path.exists.return_value = True
        result = check_persistence_connectivity(mock_module)
        assert result["status"] == "pass"

    def test_partial(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._persistence.db_path.exists.return_value = True
        mock_module._persistence.qdrant_path.exists.return_value = False
        result = check_persistence_connectivity(mock_module)
        assert result["status"] == "warn"

    def test_neither_exist(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._persistence.db_path.exists.return_value = False
        mock_module._persistence.qdrant_path.exists.return_value = False
        result = check_persistence_connectivity(mock_module)
        assert result["status"] == "fail"

    def test_exception(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._persistence.db_path.exists.side_effect = Exception("error")
        result = check_persistence_connectivity(mock_module)
        assert result["status"] == "fail"


class TestCheckPipelineStatsCoverage:

    def test_not_initialized(self):
        mock_module = MagicMock()
        mock_module._initialized = False
        result = check_pipeline_stats(mock_module)
        assert result["status"] == "warn"

    def test_pipeline_none(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline = None
        result = check_pipeline_stats(mock_module)
        assert result["status"] == "warn"

    def test_high_failure_rate(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline.get_stats.return_value = {
            "total_ingested": 100, "failures": 20
        }
        result = check_pipeline_stats(mock_module)
        assert result["status"] == "warn"

    def test_low_failure_rate(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline.get_stats.return_value = {
            "total_ingested": 100, "failures": 2
        }
        result = check_pipeline_stats(mock_module)
        assert result["status"] == "pass"

    def test_zero_total(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline.get_stats.return_value = {
            "total_ingested": 0, "failures": 0
        }
        result = check_pipeline_stats(mock_module)
        assert result["status"] == "pass"

    def test_exception(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._pipeline.get_stats.side_effect = Exception("stats error")
        result = check_pipeline_stats(mock_module)
        assert result["status"] == "fail"


class TestCheckHealthCoverage:

    def test_healthy(self):
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._flash_memory._store = {}
        mock_module._persistence.db_path.exists.return_value = True
        mock_module._persistence.qdrant_path.exists.return_value = True
        mock_module._pipeline.get_stats.return_value = {"total_ingested": 0, "failures": 0}
        mock_module.module_id = "TEST"
        mock_module.name = "memory"
        mock_module.version = "0.1"
        result = check_health(mock_module)
        assert result["status"] in ["healthy", "degraded", "unhealthy"]
        assert "checks" in result
        assert "metadata" in result

    def test_exception(self):
        mock_module = MagicMock()
        type(mock_module)._initialized = PropertyMock(side_effect=Exception("boom"))
        result = check_health(mock_module)
        assert result["status"] == "unhealthy"
        assert "error" in result["metadata"]
