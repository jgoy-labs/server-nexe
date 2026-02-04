"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/tests/test_ram_context.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import pytest

from memory.memory.engines.flash_memory import FlashMemory
from memory.memory.engines.ram_context import RAMContext
from memory.memory.models.memory_entry import MemoryEntry
from memory.memory.models.memory_types import MemoryType

@pytest.mark.asyncio
class TestRAMContext:
  """Tests per RAMContext"""

  async def test_initialization(self):
    """Inicialització amb FlashMemory"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash, max_entries=100)

    assert ram._flash == flash
    assert ram._max_entries == 100

  async def test_get_context_window(self):
    """Recuperar finestra de context"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash, max_entries=10)

    for i in range(5):
      entry = MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Entry {i}",
        source="test"
      )
      await flash.store(entry)

    context = await ram.get_context_window(limit=10)

    assert len(context) == 5

  async def test_fifo_limit(self):
    """Finestra limitada a max_entries"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash, max_entries=3)

    for i in range(5):
      entry = MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Entry {i}",
        source="test"
      )
      await flash.store(entry)

    context = await ram.get_context_window(limit=10)

    assert len(context) == 3

  async def test_to_context_string(self):
    """Generar context string per LLM"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash)

    entry1 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="User asked about Python",
      source="chat"
    )
    entry2 = MemoryEntry(
      entry_type=MemoryType.SEMANTIC,
      content="Python is a programming language",
      source="wiki"
    )

    await flash.store(entry1)
    await flash.store(entry2)

    context_str = await ram.to_context_string(limit=10)

    assert "User asked about Python" in context_str
    assert "Python is a programming language" in context_str

  async def test_safe_mode_truncation(self):
    """Safe mode trunca content llarg"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash)

    long_content = "x" * 500
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content=long_content,
      source="test"
    )

    await flash.store(entry)

    context_safe = await ram.to_context_string(limit=10, safe_mode=True)
    assert "..." in context_safe

    context_unsafe = await ram.to_context_string(limit=10, safe_mode=False)
    assert long_content in context_unsafe

  async def test_get_recent_by_type(self):
    """Filtrar per entry_type"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash)

    for i in range(3):
      await flash.store(MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content=f"Episodic {i}",
        source="test"
      ))

    for i in range(2):
      await flash.store(MemoryEntry(
        entry_type=MemoryType.SEMANTIC,
        content=f"Semantic {i}",
        source="test"
      ))

    episodic = await ram.get_recent_by_type(MemoryType.EPISODIC, limit=10)
    semantic = await ram.get_recent_by_type(MemoryType.SEMANTIC, limit=10)

    assert len(episodic) == 3
    assert len(semantic) == 2

  async def test_get_stats(self):
    """Obtenir estadístiques"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash, max_entries=100)

    await flash.store(MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="E1",
      source="test"
    ))
    await flash.store(MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="E2",
      source="test"
    ))
    await flash.store(MemoryEntry(
      entry_type=MemoryType.SEMANTIC,
      content="S1",
      source="test"
    ))

    stats = await ram.get_stats()

    assert stats["total_available"] == 3
    assert stats["episodic_count"] == 2
    assert stats["semantic_count"] == 1
    assert stats["max_entries"] == 100

  async def test_empty_context(self):
    """Context buit quan no hi ha entries"""
    flash = FlashMemory()
    ram = RAMContext(flash_memory=flash)

    context = await ram.to_context_string()

    assert "0 entries" in context or context == ""