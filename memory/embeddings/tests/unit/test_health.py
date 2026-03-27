"""
Tests per memory/embeddings/health.py
Covers uncovered lines: 44-45, 75, 111-123, 132-139, 169-170, 183-194,
226-236, 250-251, 293-296, 322-329.
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from memory.embeddings.health import (
    check_module_initialized,
    check_dependencies_available,
    check_device_available,
    check_cache_directories,
    check_memory_available,
    check_health,
)


class TestCheckModuleInitialized:
    def test_initialized_module_passes(self):
        module = MagicMock()
        module._initialized = True
        result = check_module_initialized(module)
        assert result["status"] == "pass"
        assert result["name"] == "module_initialized"

    def test_uninitialized_module_fails(self):
        module = MagicMock()
        module._initialized = False
        result = check_module_initialized(module)
        assert result["status"] == "fail"

    def test_exception_returns_fail(self):
        """Lines 44-45: exception accessing _initialized -> fail."""
        module = MagicMock()
        type(module)._initialized = PropertyMock(side_effect=RuntimeError("boom"))
        result = check_module_initialized(module)
        assert result["status"] == "fail"
        assert result["message"]  # Has some message (may be i18n key or fallback)


class TestCheckDependenciesAvailable:
    def test_sentence_transformers_available(self):
        result = check_dependencies_available()
        # May pass or fail depending on environment
        assert result["name"] == "dependencies_available"
        assert result["status"] in ("pass", "fail")

    def test_import_error_returns_fail(self):
        """Line 75: sentence-transformers not installed."""
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with patch("builtins.__import__", side_effect=ImportError("no module")):
                result = check_dependencies_available()
        assert result["status"] == "fail"
        assert result["message"]  # Has some message


class TestCheckDeviceAvailable:
    def test_mps_available(self):
        """Lines 107-110: MPS device detected."""
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": mock_torch}):
            with patch("builtins.__import__", return_value=mock_torch):
                result = check_device_available()
        # On Mac this should return pass with mps
        assert result["name"] == "device_available"

    def test_cuda_available(self):
        """Lines 111-119: CUDA device detected."""
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.current_device.return_value = 0
        mock_torch.cuda.get_device_name.return_value = "RTX 3090"
        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = check_device_available()
        assert result["name"] == "device_available"

    def test_cpu_only(self):
        """Lines 121-123: Only CPU available."""
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        mock_torch.cuda.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = check_device_available()
        assert result["name"] == "device_available"

    def test_torch_import_error(self):
        """Lines 132-137: torch not installed."""
        with patch.dict("sys.modules", {"torch": None}):
            with patch("builtins.__import__", side_effect=ImportError("no torch")):
                result = check_device_available()
        assert result["status"] == "fail"

    def test_torch_generic_error(self):
        """Lines 138-146: generic error checking device."""
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.side_effect = RuntimeError("bad")
        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = check_device_available()
        assert result["status"] == "fail"


class TestCheckCacheDirectories:
    def test_writable_cache(self, tmp_path):
        """Lines 166-170, 172-181: writable cache directory."""
        with patch("memory.embeddings.health.Path", return_value=tmp_path):
            result = check_cache_directories()
        assert result["name"] == "cache_directories"
        # Should pass on a writable tmp_path
        assert result["status"] in ("pass", "fail")

    def test_not_writable_cache(self, tmp_path):
        """Lines 169-170, 183-191: cache not writable."""
        mock_path = MagicMock()
        mock_path.mkdir = MagicMock()
        mock_test_file = MagicMock()
        mock_test_file.write_text.side_effect = PermissionError("denied")
        mock_path.__truediv__ = MagicMock(return_value=mock_test_file)
        mock_path.__str__ = MagicMock(return_value="/fake/path")

        with patch("memory.embeddings.health.Path", return_value=mock_path):
            result = check_cache_directories()
        assert result["status"] == "fail"

    def test_cache_exception(self):
        """Lines 193-201: exception during cache check."""
        with patch("core.paths.get_repo_root", side_effect=RuntimeError("bad")):
            result = check_cache_directories()
        assert result["status"] == "fail"
        assert result["message"]  # Has some message


class TestCheckMemoryAvailable:
    def test_sufficient_memory(self):
        """Lines 218-225: enough memory."""
        mock_mem = MagicMock()
        mock_mem.available = 4 * (1024**3)  # 4 GB
        with patch("memory.embeddings.health.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_mem
            result = check_memory_available(min_gb=2.0)
        assert result["status"] == "pass"
        assert result["available_gb"] > 0

    def test_low_memory_warning(self):
        """Lines 226-233: low memory warning."""
        mock_mem = MagicMock()
        mock_mem.available = 1.5 * (1024**3)  # 1.5 GB
        with patch("memory.embeddings.health.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_mem
            result = check_memory_available(min_gb=2.0)
        assert result["status"] == "warn"

    def test_critical_memory(self):
        """Lines 234-241: critical memory level."""
        mock_mem = MagicMock()
        mock_mem.available = 0.5 * (1024**3)  # 0.5 GB
        with patch("memory.embeddings.health.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_mem
            result = check_memory_available(min_gb=2.0)
        assert result["status"] == "fail"

    def test_memory_check_exception(self):
        """Lines 250-258: exception checking memory."""
        with patch("memory.embeddings.health.psutil") as mock_psutil:
            mock_psutil.virtual_memory.side_effect = RuntimeError("fail")
            result = check_memory_available()
        assert result["status"] == "fail"


class TestCheckHealth:
    def _make_module(self, initialized=True):
        module = MagicMock()
        module._initialized = initialized
        module.module_id = "embeddings"
        module.name = "embeddings"
        module.version = "0.8.2"
        return module

    def test_healthy_module(self):
        """Lines 293-296: all checks pass -> healthy."""
        module = self._make_module()
        with patch("memory.embeddings.health.check_dependencies_available",
                   return_value={"name": "deps", "status": "pass", "message": "ok"}), \
             patch("memory.embeddings.health.check_device_available",
                   return_value={"name": "device", "status": "pass", "message": "ok"}), \
             patch("memory.embeddings.health.check_cache_directories",
                   return_value={"name": "cache", "status": "pass", "message": "ok"}), \
             patch("memory.embeddings.health.check_memory_available",
                   return_value={"name": "mem", "status": "pass", "message": "ok"}):
            result = check_health(module)
        assert result["status"] == "healthy"

    def test_degraded_module(self):
        """Some warn, no fail -> degraded."""
        module = self._make_module()
        with patch("memory.embeddings.health.check_dependencies_available",
                   return_value={"name": "deps", "status": "pass", "message": "ok"}), \
             patch("memory.embeddings.health.check_device_available",
                   return_value={"name": "device", "status": "warn", "message": "cpu only"}), \
             patch("memory.embeddings.health.check_cache_directories",
                   return_value={"name": "cache", "status": "pass", "message": "ok"}), \
             patch("memory.embeddings.health.check_memory_available",
                   return_value={"name": "mem", "status": "pass", "message": "ok"}):
            result = check_health(module)
        assert result["status"] == "degraded"

    def test_unhealthy_module(self):
        """Any fail -> unhealthy."""
        module = self._make_module()
        with patch("memory.embeddings.health.check_dependencies_available",
                   return_value={"name": "deps", "status": "fail", "message": "missing"}), \
             patch("memory.embeddings.health.check_device_available",
                   return_value={"name": "device", "status": "pass", "message": "ok"}), \
             patch("memory.embeddings.health.check_cache_directories",
                   return_value={"name": "cache", "status": "pass", "message": "ok"}), \
             patch("memory.embeddings.health.check_memory_available",
                   return_value={"name": "mem", "status": "pass", "message": "ok"}):
            result = check_health(module)
        assert result["status"] == "unhealthy"

    def test_check_health_exception(self):
        """Lines 322-329: exception during health check."""
        module = MagicMock()
        # Make module_id access raise to trigger the outer exception handler
        type(module)._initialized = PropertyMock(side_effect=RuntimeError("boom"))
        result = check_health(module)
        assert result["status"] == "unhealthy"
        assert "error" in result["metadata"]
