"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/tests/test_health.py
Description: Tests for RAG health checks (health.py).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch

from memory.rag.health import (
  check_module_initialized,
  check_qdrant_available,
  check_storage_paths,
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

class TestCheckRagSources:
  """Tests for rag_sources check.

  ADR-008 E2: the check lists the chat's sources (system + registered)
  through `module.list_sources()`; it no longer walks `module._sources` nor
  calls a per-source `health()` the real sources do not have.
  """

  def test_sources_not_initialized(self):
    """Verify warn when module not initialized."""
    mock_module = MagicMock()
    mock_module._initialized = False

    result = check_rag_sources(mock_module)

    assert result["name"] == "rag_sources"
    assert result["status"] == "warn"

  def test_sources_no_sources(self):
    """Verify fail when the module lists no source at all (defensive: the
    three system collections make this unreachable on the real module)."""
    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module.list_sources.return_value = []

    result = check_rag_sources(mock_module)

    assert result["status"] == "fail"

  def test_sources_listed_pass(self):
    """Verify pass, with the names, when the module lists sources."""
    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module.list_sources.return_value = ["nexe_documentation", "plugin_notes"]

    result = check_rag_sources(mock_module)

    assert result["status"] == "pass"
    assert result["sources"] == ["nexe_documentation", "plugin_notes"]
    assert "2" in result["message"]

  def test_real_module_with_an_empty_registry_is_not_fail(self):
    """The readiness hazard of E2, pinned on the REAL module.

    A default install registers no source. If the check were fed only
    `registered_names()` it would report `fail`, the aggregate would turn
    `unhealthy` and readiness would hold the server down while the chat
    retrieves fine. The three system collections are always counted."""
    from core.memory_access import SYSTEM_COLLECTIONS
    from core.rag.registry import clear_registered_sources, registered_names
    from memory.rag.module import RAGModule

    clear_registered_sources()
    assert registered_names() == []  # precondition: nothing registered
    module = RAGModule.__new__(RAGModule)
    module._initialized = True

    result = check_rag_sources(module)

    assert result["status"] == "pass", result
    assert sorted(result["sources"]) == sorted(SYSTEM_COLLECTIONS)
    assert len(result["sources"]) == 3

  def test_real_module_counts_a_registered_source_too(self):
    from core.rag.registry import clear_registered_sources, register_source
    from memory.rag.module import RAGModule

    class _Src:
      def name(self):
        return "plugin_notes"

      async def search(self, memory, query):
        return []

    clear_registered_sources()
    register_source(_Src())
    try:
      module = RAGModule.__new__(RAGModule)
      module._initialized = True
      result = check_rag_sources(module)
    finally:
      clear_registered_sources()

    assert result["status"] == "pass"
    assert "plugin_notes" in result["sources"]
    assert len(result["sources"]) == 4

class TestCheckDiskSpace:
  """Tests for disk_space check."""

  def test_disk_space_sufficient(self):
    """Verify pass with sufficient space."""
    result = check_disk_space(min_gb=0.001)

    assert result["name"] == "disk_space"
    assert result["status"] == "pass"
    assert "free_gb" in result

  def test_disk_space_warning(self):
    """Verify warn with low space (never fail-by-value)."""
    result = check_disk_space(min_gb=10000000)

    assert result["status"] == "warn"

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
    mock_module.list_sources.return_value = []
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
    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module.list_sources.return_value = ["nexe_documentation"]
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
    mock_module.list_sources.return_value = []
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
    mock_module.list_sources.return_value = []
    mock_module.module_id = "TEST-ID"
    mock_module.name = "rag"
    mock_module.version = "0.1"
    mock_module._stats = {"test": 1}

    result = check_health(mock_module)

    assert result["metadata"]["module_id"] == "TEST-ID"
    assert result["metadata"]["name"] == "rag"

  def test_check_health_has_no_phantom_subchecks(self):
    """B064 anti-regression: check_health must NOT emit the lobotomised
    transaction_ledger / write_coordinator sub-checks.

    Those checks reported 'pass' unconditionally for components that do not
    exist in this codebase (TransactionLedger / WriteCoordinator), so the
    health report lied. The real contract is exactly 5 sub-checks, none of
    which is a phantom component.
    """
    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module.list_sources.return_value = ["nexe_documentation"]
    mock_module.module_id = "TEST"
    mock_module.name = "rag"
    mock_module.version = "0.1"
    mock_module._stats = {}

    result = check_health(mock_module)

    names = {c["name"] for c in result["checks"]}
    assert "transaction_ledger" not in names, (
      "phantom transaction_ledger sub-check still emitted"
    )
    assert "write_coordinator" not in names, (
      "phantom write_coordinator sub-check still emitted"
    )
    assert names == {
      "module_initialized",
      "rag_sources",
      "qdrant_available",
      "storage_paths",
      "disk_space",
    }
    assert len(result["checks"]) == 5

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

  def test_real_module_empty_registry_is_not_unhealthy_by_its_sources(self):
    """End to end through check_health on the real module, with the store
    answering and the disk fine: an empty registry must not make the
    aggregate unhealthy (readiness, core/endpoints/root.py)."""
    from core.rag.registry import clear_registered_sources
    from memory.rag.module import RAGModule

    clear_registered_sources()
    module = RAGModule.__new__(RAGModule)
    module.module_id = "rag"
    module.name = "rag"
    module.version = "0"
    module._initialized = True
    module._stats = {"searches_performed": 0}

    with patch("core.qdrant_pool.qdrant_status", return_value=(True, "ok")), \
         patch("memory.rag.health.check_disk_space",
               return_value={"name": "disk_space", "status": "pass", "message": "ok"}), \
         patch("memory.rag.health.check_storage_paths",
               return_value={"name": "storage_paths", "status": "pass", "message": "ok"}):
      result = check_health(module)

    by_name = {c["name"]: c["status"] for c in result["checks"]}
    assert by_name["rag_sources"] == "pass"
    assert result["status"] == "healthy", result
    assert len(result["metadata"]["sources"]) == 3
