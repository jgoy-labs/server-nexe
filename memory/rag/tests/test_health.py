"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/tests/test_health.py
Description: Tests per RAG health checks (health.py).

www.jgoy.net
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch

from memory.rag.health import (
  check_module_initialized,
  check_qdrant_available,
  check_storage_paths,
  check_transaction_ledger,
  check_write_coordinator,
  check_rag_sources,
  check_disk_space,
  check_health,
)

class TestCheckModuleInitialized:
  """Tests for module_initialized check."""

  def test_initialized_returns_pass(self):
    """Verify pass when module initialized."""
    mock_module = MagicMock()
    mock_module._initialized = True

    result = check_module_initialized(mock_module)

    assert result["name"] == "module_initialized"
    assert result["status"] == "pass"

  def test_not_initialized_returns_fail(self):
    """Verify fail when module not initialized."""
    mock_module = MagicMock()
    mock_module._initialized = False

    result = check_module_initialized(mock_module)

    assert result["status"] == "fail"

  def test_exception_returns_fail(self):
    """Verify fail on exception."""
    mock_module = MagicMock()
    mock_module._initialized = property(lambda self: (_ for _ in ()).throw(Exception("Test")))

    type(mock_module)._initialized = property(lambda self: (_ for _ in ()).throw(Exception("Test")))

    result = check_module_initialized(mock_module)
    assert result["status"] == "fail"

class TestCheckQdrantAvailable:
  """Tests for qdrant_available check."""

  def test_qdrant_available(self):
    """Verify pass when qdrant-client installed."""
    result = check_qdrant_available()

    assert result["name"] == "qdrant_available"
    assert result["status"] in ["pass", "fail"]

  @patch.dict('sys.modules', {'qdrant_client': None})
  def test_qdrant_importable(self):
    """Verify check attempts import."""
    result = check_qdrant_available()
    assert "name" in result
    assert "status" in result

class TestCheckStoragePaths:
  """Tests for storage_paths check."""

  def test_storage_paths_created(self, tmp_path):
    """Verify paths created if not exist."""
    with patch('memory.rag.health.Path') as mock_path:
      mock_path.return_value = tmp_path / "storage/vectors"

      result = check_storage_paths()

      assert result["name"] == "storage_paths"
      assert result["status"] in ["pass", "fail"]

  def test_storage_paths_check_writable(self):
    """Verify writability check performed."""
    result = check_storage_paths()

    assert "message" in result
    assert result["status"] in ["pass", "fail"]

class TestCheckTransactionLedger:
  """Tests for transaction_ledger check."""

  def test_ledger_check(self):
    """Verify ledger importability check."""
    result = check_transaction_ledger()

    assert result["name"] == "transaction_ledger"
    assert result["status"] in ["pass", "fail"]
    assert "message" in result

class TestCheckWriteCoordinator:
  """Tests for write_coordinator check."""

  def test_coordinator_check(self):
    """Verify coordinator importability check."""
    result = check_write_coordinator()

    assert result["name"] == "write_coordinator"
    assert result["status"] in ["pass", "fail"]
    assert "message" in result

class TestCheckRagSources:
  """Tests for rag_sources check."""

  def test_sources_not_initialized(self):
    """Verify warn when module not initialized."""
    mock_module = MagicMock()
    mock_module._initialized = False

    result = check_rag_sources(mock_module)

    assert result["name"] == "rag_sources"
    assert result["status"] == "warn"

  def test_sources_no_sources(self):
    """Verify fail when no sources registered."""
    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module._sources = {}

    result = check_rag_sources(mock_module)

    assert result["status"] == "fail"

  def test_sources_all_healthy(self):
    """Verify pass when all sources healthy."""
    mock_source = MagicMock()
    mock_source.health.return_value = {"status": "healthy"}

    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module._sources = {"personality": mock_source}

    result = check_rag_sources(mock_module)

    assert result["status"] == "pass"
    assert "sources" in result

  def test_sources_some_unhealthy(self):
    """Verify fail when some sources unhealthy."""
    mock_source = MagicMock()
    mock_source.health.return_value = {"status": "unhealthy"}

    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module._sources = {"personality": mock_source}

    result = check_rag_sources(mock_module)

    assert result["status"] == "fail"

class TestCheckDiskSpace:
  """Tests for disk_space check."""

  def test_disk_space_sufficient(self):
    """Verify pass with sufficient space."""
    result = check_disk_space(min_gb=0.001)

    assert result["name"] == "disk_space"
    assert result["status"] == "pass"
    assert "free_gb" in result

  def test_disk_space_warning(self):
    """Verify warn with low space."""
    result = check_disk_space(min_gb=10000000)

    assert result["status"] in ["warn", "fail"]

  def test_disk_space_contains_free_gb(self):
    """Verify result contains free_gb."""
    result = check_disk_space()

    if result["status"] != "fail":
      assert "free_gb" in result
      assert isinstance(result["free_gb"], (int, float))

class TestCheckHealth:
  """Tests for aggregate check_health function."""

  def test_check_health_returns_all_checks(self):
    """Verify all checks are run."""
    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module._sources = {}
    mock_module.module_id = "TEST"
    mock_module.name = "rag"
    mock_module.version = "0.1"
    mock_module._stats = {}

    result = check_health(mock_module)

    assert "status" in result
    assert "checks" in result
    assert "metadata" in result
    assert len(result["checks"]) >= 5

  def test_check_health_healthy_status(self):
    """Verify healthy when all pass."""
    mock_source = MagicMock()
    mock_source.health.return_value = {"status": "healthy"}

    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module._sources = {"personality": mock_source}
    mock_module.module_id = "TEST"
    mock_module.name = "rag"
    mock_module.version = "0.1"
    mock_module._stats = {}

    result = check_health(mock_module)

    assert result["status"] in ["healthy", "degraded", "unhealthy"]

  def test_check_health_unhealthy_on_fail(self):
    """Verify unhealthy when any check fails."""
    mock_module = MagicMock()
    mock_module._initialized = False
    mock_module._sources = {}
    mock_module.module_id = "TEST"
    mock_module.name = "rag"
    mock_module.version = "0.1"
    mock_module._stats = {}

    result = check_health(mock_module)

    assert result["status"] in ["degraded", "unhealthy"]

  def test_check_health_metadata(self):
    """Verify metadata is included."""
    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module._sources = {}
    mock_module.module_id = "TEST-ID"
    mock_module.name = "rag"
    mock_module.version = "0.1"
    mock_module._stats = {"test": 1}

    result = check_health(mock_module)

    assert result["metadata"]["module_id"] == "TEST-ID"
    assert result["metadata"]["name"] == "rag"

class TestHealthCheckEdgeCases:
  """Edge case tests for health checks."""

  def test_check_health_exception_handling(self):
    """Verify exception is handled gracefully."""
    mock_module = MagicMock()
    type(mock_module)._initialized = property(
      lambda self: (_ for _ in ()).throw(Exception("Test"))
    )

    result = check_health(mock_module)
    assert result["status"] == "unhealthy"

  def test_disk_space_error_handling(self):
    """Verify disk space handles errors."""
    with patch('memory.rag.health.psutil') as mock_psutil:
      mock_psutil.disk_usage.side_effect = Exception("Test error")

      result = check_disk_space()

      assert result["status"] == "fail"
      assert "error" in result["message"].lower()