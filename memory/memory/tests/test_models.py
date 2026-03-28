"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/tests/test_models.py
Description: Tests per als models de dades de Memory (MemoryEntry, MemoryType).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from memory.memory.models.memory_entry import MemoryEntry
from memory.memory.models.memory_types import MemoryType

class TestMemoryType:
  """Tests per MemoryType enum"""

  def test_memory_type_values(self):
    """Verificar que els valors de l'enum són correctes"""
    assert MemoryType.EPISODIC.value == "episodic"
    assert MemoryType.SEMANTIC.value == "semantic"

  def test_memory_type_from_string(self):
    """Crear MemoryType des de string"""
    assert MemoryType("episodic") == MemoryType.EPISODIC
    assert MemoryType("semantic") == MemoryType.SEMANTIC

  def test_memory_type_invalid(self):
    """Rebutjar valors invàlids"""
    with pytest.raises(ValueError):
      MemoryType("invalid_type")


class TestMemoryEntry:
  """Tests per MemoryEntry"""

  def test_memory_entry_basic(self):
    """Crear MemoryEntry bàsica"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test content",
      source="test"
    )
    assert entry.entry_type == MemoryType.EPISODIC
    assert entry.content == "Test content"
    assert entry.source == "test"
    assert entry.id is not None
    assert isinstance(entry.timestamp, datetime)

  def test_memory_entry_deterministic_id(self):
    """ID determinístic: SHA256(content)[:16]"""
    entry1 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Same content",
      source="test"
    )
    entry2 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Same content",
      source="test"
    )
    assert entry1.id == entry2.id

    entry3 = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Different content",
      source="test"
    )
    assert entry1.id != entry3.id

  def test_memory_entry_id_format(self):
    """ID ha de ser hex de 16 chars"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test"
    )
    assert len(entry.id) == 16
    assert all(c in "0123456789abcdef" for c in entry.id)

  def test_memory_entry_content_validation(self):
    """Validar content: min_length=1, max_length=100_000"""
    MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="A",
      source="test"
    )

    with pytest.raises(ValidationError):
      MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content="",
        source="test"
      )

    with pytest.raises(ValidationError):
      MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content="x" * 100_001,
        source="test"
      )

  def test_memory_entry_ttl_default(self):
    """TTL per defecte: 1800s"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test"
    )
    assert entry.ttl_seconds == 1800

  def test_memory_entry_ttl_custom(self):
    """TTL customitzat"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test",
      ttl_seconds=3600
    )
    assert entry.ttl_seconds == 3600

  def test_memory_entry_ttl_validation(self):
    """TTL >= 60 (mínim 1 minut)"""
    MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test",
      ttl_seconds=60
    )

    MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test",
      ttl_seconds=86400
    )

    with pytest.raises(ValidationError):
      MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content="Test",
        source="test",
        ttl_seconds=59
      )

    with pytest.raises(ValidationError):
      MemoryEntry(
        entry_type=MemoryType.EPISODIC,
        content="Test",
        source="test",
        ttl_seconds=-1
      )

  def test_memory_entry_should_encrypt_fase13(self):
    """should_encrypt retorna sempre False (Anàlisi Contextual no implementada)"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test"
    )
    assert entry.should_encrypt is False


  def test_memory_entry_metadata_dict(self):
    """Metadata com a dict lliure"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test",
      metadata={"custom_key": "custom_value", "count": 42}
    )
    assert entry.metadata["custom_key"] == "custom_value"
    assert entry.metadata["count"] == 42

  def test_memory_entry_serialization(self):
    """Serialització Pydantic (model_dump)"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test content",
      source="test",
      ttl_seconds=3600
    )
    data = entry.model_dump()

    assert data["entry_type"] == "episodic"
    assert data["content"] == "Test content"
    assert data["source"] == "test"
    assert data["ttl_seconds"] == 3600
    assert "id" in data
    assert "timestamp" in data

  def test_memory_entry_json_serialization(self):
    """Serialització JSON"""
    entry = MemoryEntry(
      entry_type=MemoryType.EPISODIC,
      content="Test",
      source="test"
    )
    json_str = entry.model_dump_json()
    assert isinstance(json_str, str)
    assert "episodic" in json_str
    assert "Test" in json_str

  def test_memory_entry_from_dict(self):
    """Crear MemoryEntry des de dict"""
    data = {
      "entry_type": "semantic",
      "content": "Knowledge base entry",
      "source": "wikipedia",
      "ttl_seconds": 7200
    }
    entry = MemoryEntry(**data)
    assert entry.entry_type == MemoryType.SEMANTIC
    assert entry.content == "Knowledge base entry"
    assert entry.source == "wikipedia"
    assert entry.ttl_seconds == 7200