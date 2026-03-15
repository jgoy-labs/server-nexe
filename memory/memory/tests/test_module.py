"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/tests/test_module.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

import pytest

from memory.memory.module import MemoryModule
from memory.memory.models.memory_entry import MemoryEntry
from memory.memory.models.memory_types import MemoryType

@pytest.mark.asyncio
class TestMemoryModule:
  """Tests per MemoryModule singleton"""

  async def test_singleton_pattern(self):
    """MemoryModule és Singleton"""
    module1 = MemoryModule.get_instance()

    module2 = MemoryModule.get_instance()

    assert module1 is module2

  async def test_direct_instantiation_fails(self):
    """No es pot instanciar directament"""
    MemoryModule.get_instance()

    with pytest.raises(RuntimeError):
      MemoryModule()

  async def test_get_instance_before_init(self):
    """get_instance() funciona sense init previ"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()

    assert module is not None
    assert isinstance(module, MemoryModule)
    assert module._initialized is False

    MemoryModule._instance = None

  async def test_initialization(self):
    """Inicialitzar MemoryModule"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()
    result = await module.initialize()

    assert result is True
    assert module._initialized is True
    assert module._flash_memory is not None
    assert module._ram_context is not None
    assert module._persistence is not None
    assert module._pipeline is not None

    await module.shutdown()
    MemoryModule._instance = None

  async def test_double_initialization(self):
    """Segona inicialització no falla (idempotent)"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()

    result1 = await module.initialize()
    assert result1 is True

    result2 = await module.initialize()
    assert result2 is True

    await module.shutdown()
    MemoryModule._instance = None

  async def test_get_info(self):
    """Obtenir informació del mòdul"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()

    info = module.get_info()

    assert "module_id" in info
    assert "name" in info
    assert "version" in info
    assert "initialized" in info
    assert info["name"] == "memory"

    MemoryModule._instance = None

  async def test_get_health_before_init(self):
    """get_health() funciona abans d'inicialitzar"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()

    health = module.get_health()

    assert "status" in health
    assert health["status"] in ["healthy", "degraded", "unhealthy"]

    MemoryModule._instance = None

  async def test_shutdown_before_init(self):
    """Shutdown sense init no falla"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()

    result = await module.shutdown()

    assert result is True

    MemoryModule._instance = None

  @pytest.mark.integration
  async def test_full_lifecycle(self):
    """Test cicle complet: init -> store -> recall -> shutdown"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()

    await module.initialize()

    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test integration",
      source="test_module"
    )
    success = await module._pipeline.ingest(entry)
    assert success is True

    flash_entry = await module._flash_memory.get(entry.id)
    assert flash_entry is not None
    assert flash_entry.content == "Test integration"

    context = await module._ram_context.to_context_string(limit=10)
    assert "Test integration" in context

    result = await module.shutdown()
    assert result is True

    assert module._initialized is False
    assert module._flash_memory is None

    MemoryModule._instance = None

  @pytest.mark.xfail(
    reason="MemoryModule utilitza rutes relatives a l'usuari i pot ignorar l'arrel real del repo en certs entorns",
    strict=False,
  )
  async def test_storage_paths_follow_repo_root(self, monkeypatch, tmp_path):
    """La persistència hauria de viure a storage/memory però s'escriu a Path.home"""
    MemoryModule._instance = None
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
      "memory.memory.module.Path.home",
      lambda: fake_home,
    )

    module = MemoryModule.get_instance()
    try:
      await module.initialize()

      project_root = Path(__file__).resolve().parents[4]
      expected_storage = project_root / "storage" / "memory"

      assert module._persistence.db_path.is_relative_to(
        expected_storage
      ), "La base de dades hauria d'estar dins storage/memory"
    finally:
      await module.shutdown()
      MemoryModule._instance = None

  @pytest.mark.integration
  async def test_integration_smoke(self):
    """Smoke test complert"""
    MemoryModule._instance = None

    module = MemoryModule.get_instance()

    await module.initialize()

    for i in range(3):
      entry = MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Smoke test entry {i}",
        source="smoke"
      )
      await module._pipeline.ingest(entry)

    pipeline_stats = module._pipeline.get_stats()
    assert pipeline_stats["total_ingested"] == 3

    ram_stats = await module._ram_context.get_stats()
    # RAM context may have extra entries from initialization or previous tests
    assert ram_stats["total_available"] >= 3

    await module.shutdown()

    MemoryModule._instance = None


@pytest.mark.asyncio
class TestMemoryModuleAdditional:
  """Additional tests for uncovered lines."""

  async def test_initialize_project_root_none_fallback(self):
    """Lines 117-119: project_root is None, falls back to cwd."""
    from unittest.mock import patch, MagicMock

    MemoryModule._instance = None
    module = MemoryModule.get_instance()

    mock_state = MagicMock()
    mock_state.project_root = None
    mock_state.config = {}

    with patch("memory.memory.module.get_server_state", return_value=mock_state):
      result = await module.initialize(config={"flash_ttl_seconds": 3600})
      assert result is True

    await module.shutdown()
    MemoryModule._instance = None

  async def test_initialize_custom_config_merge(self):
    """Line 111: custom config merged."""
    from unittest.mock import patch, MagicMock

    MemoryModule._instance = None
    module = MemoryModule.get_instance()

    with patch("memory.memory.module.get_server_state") as mock_gs:
      mock_gs.return_value.project_root = Path.cwd()
      mock_gs.return_value.config = {}
      result = await module.initialize(config={"ram_max_entries": 50})
      assert result is True

    await module.shutdown()
    MemoryModule._instance = None

  async def test_initialize_exception_raises(self):
    """Lines 172-174: exception raised during init."""
    from unittest.mock import patch, MagicMock

    MemoryModule._instance = None
    module = MemoryModule.get_instance()

    with patch("memory.memory.module.get_server_state") as mock_gs:
      mock_gs.return_value.project_root = Path.cwd()
      mock_gs.return_value.config = {}
      with patch("memory.memory.module.FlashMemory", side_effect=Exception("flash error")):
        with pytest.raises(Exception, match="flash error"):
          await module.initialize()

    module._initialized = False
    MemoryModule._instance = None

  async def test_shutdown_failure_returns_false(self):
    """Lines 208-210: shutdown exception returns False."""
    from unittest.mock import patch, MagicMock, AsyncMock

    MemoryModule._instance = None
    module = MemoryModule.get_instance()

    with patch("memory.memory.module.get_server_state") as mock_gs:
      mock_gs.return_value.project_root = Path.cwd()
      mock_gs.return_value.config = {}
      await module.initialize()

    module._flash_memory.cleanup_expired = AsyncMock(side_effect=Exception("cleanup err"))
    result = await module.shutdown()
    assert result is False

    module._initialized = False
    module._flash_memory = None
    module._ram_context = None
    module._persistence = None
    module._pipeline = None
    MemoryModule._instance = None

  async def test_ingest_not_initialized_raises(self):
    """Lines 250-253: ingest before init."""
    MemoryModule._instance = None
    module = MemoryModule.get_instance()

    entry = MemoryEntry(entry_type=MemoryType.EPISODIC, content="test", source="t")
    with pytest.raises(RuntimeError, match="not initialized"):
      await module.ingest(entry)

    MemoryModule._instance = None

  async def test_ingest_batch_not_initialized_raises(self):
    """Lines 265-268: ingest_batch before init."""
    MemoryModule._instance = None
    module = MemoryModule.get_instance()

    with pytest.raises(RuntimeError, match="not initialized"):
      await module.ingest_batch([])

    MemoryModule._instance = None

  async def test_get_metrics_coverage(self):
    """Lines 277-283: get_metrics."""
    from unittest.mock import patch, MagicMock

    MemoryModule._instance = None
    module = MemoryModule.get_instance()

    mock_metrics_obj = MagicMock()
    mock_metrics_obj.get_metrics.return_value = {"counter": 1}
    mock_metrics_obj.update_from_module = MagicMock()

    with patch("memory.memory.health.check_health", return_value={"status": "healthy"}):
      with patch("memory.memory.metrics.get_metrics", return_value=mock_metrics_obj):
        result = module.get_metrics()
        assert isinstance(result, dict)

    MemoryModule._instance = None
