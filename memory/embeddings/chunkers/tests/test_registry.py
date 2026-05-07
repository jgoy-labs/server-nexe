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
  """Tests for singleton behavior."""

  def setup_method(self):
    """Reset registry before each test."""
    reset_registry()

  def test_get_registry_returns_same_instance(self):
    """get_chunker_registry returns the same singleton."""
    registry1 = get_chunker_registry()
    registry2 = get_chunker_registry()
    assert registry1 is registry2

  def test_reset_registry_creates_new_instance(self):
    """reset_registry allows creating a new singleton."""
    registry1 = get_chunker_registry()
    reset_registry()
    registry2 = get_chunker_registry()
    assert registry1 is not registry2

class TestAutoDiscovery:
  """Tests for chunker auto-discovery."""

  def setup_method(self):
    reset_registry()

  def test_auto_discovery_finds_builtin_chunkers(self):
    """Auto-discovery finds TextChunker and CodeChunker."""
    registry = get_chunker_registry()

    assert len(registry) >= 2

    assert registry.has_chunker("chunker.text")
    assert registry.has_chunker("chunker.code")

  def test_auto_discovery_registers_correct_types(self):
    """Auto-discovery registers the correct types."""
    registry = get_chunker_registry()

    text_chunker = registry.get_chunker("chunker.text")
    code_chunker = registry.get_chunker("chunker.code")

    assert isinstance(text_chunker, TextChunker)
    assert isinstance(code_chunker, CodeChunker)

class TestChunkerSelection:
  """Tests for chunker selection."""

  def setup_method(self):
    reset_registry()

  def test_get_chunker_for_python_format(self):
    """get_chunker_for_format('py') returns CodeChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("py")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

  def test_get_chunker_for_javascript_format(self):
    """get_chunker_for_format('js') returns CodeChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("js")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

  def test_get_chunker_for_text_format(self):
    """get_chunker_for_format('txt') returns TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("txt")

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_get_chunker_for_markdown_format(self):
    """get_chunker_for_format('md') returns TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("md")

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_get_chunker_for_unknown_format_returns_none(self):
    """get_chunker_for_format with unknown format returns None."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format("xyz123")

    assert chunker is None

  def test_get_chunker_for_type_code(self):
    """get_chunker_for_type('code') returns CodeChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_type("code")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

  def test_get_chunker_for_type_text(self):
    """get_chunker_for_type('text') returns TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_type("text")

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_get_default_chunker_returns_text(self):
    """get_default_chunker returns TextChunker."""
    registry = get_chunker_registry()
    chunker = registry.get_default_chunker()

    assert chunker is not None
    assert isinstance(chunker, TextChunker)

  def test_format_with_leading_dot(self):
    """Accepts formats with leading dot (.py)."""
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format(".py")

    assert chunker is not None
    assert isinstance(chunker, CodeChunker)

class TestManualRegistration:
  """Tests for manual chunker registration."""

  def setup_method(self):
    reset_registry()

  def test_register_custom_chunker(self):
    """Can register a custom chunker."""
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
    """Registering a duplicate raises DuplicateChunkerError."""
    registry = ChunkerRegistry()
    registry.register(TextChunker)

    with pytest.raises(DuplicateChunkerError):
      registry.register(TextChunker)

  def test_register_non_chunker_raises_error(self):
    """Registering a non-BaseChunker raises ValueError."""
    registry = ChunkerRegistry()

    class NotAChunker:
      pass

    with pytest.raises(ValueError):
      registry.register(NotAChunker)

  def test_get_nonexistent_chunker_raises_error(self):
    """get_chunker with non-existent ID raises ChunkerNotFoundError."""
    registry = ChunkerRegistry()

    with pytest.raises(ChunkerNotFoundError):
      registry.get_chunker("chunker.nonexistent")

class TestRegistryStats:
  """Tests for registry statistics."""

  def setup_method(self):
    reset_registry()

  def test_list_chunkers(self):
    """list_chunkers returns list with info."""
    registry = get_chunker_registry()
    chunkers = registry.list_chunkers()

    assert isinstance(chunkers, list)
    assert len(chunkers) >= 2

    for chunker_info in chunkers:
      assert "id" in chunker_info
      assert "name" in chunker_info
      assert "formats" in chunker_info

  def test_get_stats(self):
    """get_stats returns statistics."""
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
    """has_format_support works correctly."""
    registry = get_chunker_registry()

    assert registry.has_format_support("py")
    assert registry.has_format_support("txt")
    assert registry.has_format_support(".md")
    assert not registry.has_format_support("xyz123")

  def test_len_registry(self):
    """len(registry) returns number of chunkers."""
    registry = get_chunker_registry()
    assert len(registry) >= 2

  def test_repr_registry(self):
    """repr shows useful info."""
    registry = get_chunker_registry()
    repr_str = repr(registry)

    assert "ChunkerRegistry" in repr_str
    assert "chunkers=" in repr_str

class TestMemoryIntegration:
  """Tests simulating how Memory will use the registry."""

  def setup_method(self):
    reset_registry()

  def test_memory_workflow_python_file(self):
    """Simulates Python file processing by Memory."""
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
    """Simulates text file processing by Memory."""
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
    """Memory with unknown format uses default chunker."""
    registry = get_chunker_registry()

    file_path = "data.xyz"
    extension = file_path.split(".")[-1]
    chunker = registry.get_chunker_for_format(extension)

    if chunker is None:
      chunker = registry.get_default_chunker()

    assert chunker is not None
    assert isinstance(chunker, TextChunker)