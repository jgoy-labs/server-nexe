"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/chunkers/tests/test_registry.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from memory.embeddings.chunkers import (
  BaseChunker,
  ChunkerNotFoundError,
  ChunkerRegistry,
  CodeChunker,
  DuplicateChunkerError,
  TextChunker,
  get_chunker_registry,
  reset_registry,
)

class TestChunkerRegistrySingleton:
  """Tests per comportament singleton."""

  def setup_method(self):
    """Reset registry abans de cada test."""
    reset_registry()

  def test_get_registry_returns_same_instance(self):
    """get_chunker_registry retorna el mateix singleton."""
    registry1 = get_chunker_registry()
    registry2 = get_chunker_registry()
    assert registry1 is registry2

  def test_reset_registry_creates_new_instance(self):
    """reset_registry permet crear nou singleton."""
    registry1 = get_chunker_registry()
    reset_registry()
    registry2 = get_chunker_registry()
    assert registry1 is not registry2

class TestAutoDiscovery:
  """Tests per auto-discovery de chunkers."""

  def setup_method(self):
    reset_registry()

  def test_auto_discovery_finds_builtin_chunkers(self):
    """Auto-discovery troba TextChunker i CodeChunker."""
    registry = get_chunker_registry()

    assert len(registry) >= 2

    assert registry.has_chunker("chunker.text")
    assert registry.has_chunker("chunker.code")

  def test_auto_discovery_registers_correct_types(self):
    """Auto-discovery registra els tipus correctes."""
    registry = get_chunker_registry()

    text_chunker = registry.get_chunker("chunker.text")
    code_chunker = registry.get_chunker("chunker.code")

    assert isinstance(text_chunker, TextChunker)
    assert isinstance(code_chunker, CodeChunker)

class TestChunkerSelection:
  """Tests per selecció de chunkers."""

  def setup_method(self):
    reset_registry()

  def test_get_chunker_for_python_format(self):
    """get_chunker_for_format('py') retorna CodeChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("py")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

  def test_get_chunker_for_javascript_format(self):
    """get_chunker_for_format('js') retorna CodeChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("js")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

  def test_get_chunker_for_text_format(self):
    """get_chunker_for_format('txt') retorna TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("txt")

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_get_chunker_for_markdown_format(self):
    """get_chunker_for_format('md') retorna TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("md")

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_get_chunker_for_unknown_format_returns_none(self):
    """get_chunker_for_format amb format desconegut retorna None."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("xyz123")

    assert chunker is None

  def test_get_chunker_for_type_code(self):
    """get_chunker_for_type('code') retorna CodeChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_type("code")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

  def test_get_chunker_for_type_text(self):
    """get_chunker_for_type('text') retorna TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_type("text")

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_get_default_chunker_returns_text(self):
    """get_default_chunker retorna TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_default_chunker()

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_format_with_leading_dot(self):
    """Accepta formats amb punt inicial (.py)."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format(".py")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

class TestManualRegistration:
  """Tests per registre manual de chunkers."""

  def setup_method(self):
    reset_registry()

  def test_register_custom_chunker(self):
    """Pot registrar un chunker personalitzat."""
    registry = ChunkerRegistry()

    class CustomChunker(BaseChunker):
      metadata = {
        "id": "chunker.custom",
        "name": "Custom Chunker",
        "formats": ["custom"],
        "content_types": ["custom"],
      }

      def chunk(self, text, document_id=None, metadata=None):
        pass

      def supports(self, file_extension=None, content_type=None):
        return file_extension == "custom"

    registry.register(CustomChunker)

    assert registry.has_chunker("chunker.custom")
    assert registry.get_chunker_for_format("custom") is not None

  def test_register_duplicate_raises_error(self):
    """Registrar duplicat llança DuplicateChunkerError."""
    registry = ChunkerRegistry()
    registry.register(TextChunker)

    with pytest.raises(DuplicateChunkerError):
      registry.register(TextChunker)

  def test_register_non_chunker_raises_error(self):
    """Registrar no-BaseChunker llança ValueError."""
    registry = ChunkerRegistry()

    class NotAChunker:
      pass

    with pytest.raises(ValueError):
      registry.register(NotAChunker)

  def test_get_nonexistent_chunker_raises_error(self):
    """get_chunker amb ID inexistent llança ChunkerNotFoundError."""
    registry = ChunkerRegistry()

    with pytest.raises(ChunkerNotFoundError):
      registry.get_chunker("chunker.nonexistent")

class TestRegistryStats:
  """Tests per estadístiques del registry."""

  def setup_method(self):
    reset_registry()

  def test_list_chunkers(self):
    """list_chunkers retorna llista amb info."""
    registry = get_chunker_registry()
    chunkers = registry.list_chunkers()

    assert isinstance(chunkers, list)
    assert len(chunkers) >= 2

    for chunker_info in chunkers:
      assert "id" in chunker_info
      assert "name" in chunker_info
      assert "formats" in chunker_info

  def test_get_stats(self):
    """get_stats retorna estadístiques."""
    registry = get_chunker_registry()
    stats = registry.get_stats()

    assert "total_chunkers" in stats
    assert stats["total_chunkers"] >= 2
    assert "chunker_ids" in stats
    assert "chunker.text" in stats["chunker_ids"]
    assert "chunker.code" in stats["chunker_ids"]
    assert "supported_formats" in stats
    assert "py" in stats["supported_formats"]
    assert "txt" in stats["supported_formats"]

  def test_has_format_support(self):
    """has_format_support funciona correctament."""
    registry = get_chunker_registry()

    assert registry.has_format_support("py")
    assert registry.has_format_support("txt")
    assert registry.has_format_support(".md")
    assert not registry.has_format_support("xyz123")

  def test_len_registry(self):
    """len(registry) retorna nombre de chunkers."""
    registry = get_chunker_registry()
    assert len(registry) >= 2

  def test_repr_registry(self):
    """repr mostra info útil."""
    registry = get_chunker_registry()
    repr_str = repr(registry)

    assert "ChunkerRegistry" in repr_str
    assert "chunkers=" in repr_str

class TestMemoryIntegration:
  """Tests que simulen com Memory usarà el registry."""

  def setup_method(self):
    reset_registry()

  def test_memory_workflow_python_file(self):
    """Simula processament de fitxer Python per Memory."""
    registry = get_chunker_registry()

    file_path = "module.py"
    extension = file_path.split(".")[-1]
    chunker = registry.get_chunker_for_format(extension)

    if chunker is None:
      chunker = registry.get_default_chunker()

    code = '''
def hello():
  """Saluda."""
  print("Hello")

def world():
  return "World"
'''
    result = chunker.chunk(code, document_id=file_path)

    assert result.total_chunks >= 1
    assert result.chunker_id == "chunker.code"

  def test_memory_workflow_text_file(self):
    """Simula processament de fitxer text per Memory."""
    registry = get_chunker_registry()

    file_path = "document.txt"
    extension = file_path.split(".")[-1]
    chunker = registry.get_chunker_for_format(extension)

    if chunker is None:
      chunker = registry.get_default_chunker()

    text = """
Introducció

Aquest és un document de prova amb múltiples paràgrafs.

Secció 1

Contingut de la primera secció amb text narratiu.

Secció 2

Contingut de la segona secció.
"""
    result = chunker.chunk(text, document_id=file_path)

    assert result.total_chunks >= 1
    assert result.chunker_id == "chunker.text"

  def test_memory_workflow_unknown_format(self):
    """Memory amb format desconegut usa default chunker."""
    registry = get_chunker_registry()

    file_path = "data.xyz"
    extension = file_path.split(".")[-1]
    chunker = registry.get_chunker_for_format(extension)

    if chunker is None:
      chunker = registry.get_default_chunker()

    assert chunker is not None
    assert isinstance(chunker, TextChunker)