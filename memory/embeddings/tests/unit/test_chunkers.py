"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/tests/unit/test_chunkers.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from memory.embeddings.chunkers import (
  BaseChunker,
  Chunk,
  ChunkingResult,
  ChunkerNotFoundError,
  ChunkerRegistry,
  CodeChunker,
  DuplicateChunkerError,
  TextChunker,
  get_chunker_registry,
  reset_registry,
)

class TestChunkDataclass:
  """Tests per la dataclass Chunk."""

  def test_chunk_create_factory(self):
    """Factory method crea chunk amb UUID."""
    chunk = Chunk.create(
      text="Test content",
      start=0,
      end=12,
      index=0,
      document_id="doc1",
    )

    assert chunk.text == "Test content"
    assert chunk.start_char == 0
    assert chunk.end_char == 12
    assert chunk.chunk_index == 0
    assert chunk.document_id == "doc1"
    assert chunk.chunk_id
    assert len(chunk.chunk_id) == 36

  def test_chunk_to_dict(self):
    """to_dict() serialitza correctament."""
    chunk = Chunk.create(
      text="Test",
      start=0,
      end=4,
      index=0,
      section_title="Section",
      chunk_type="paragraph",
    )

    d = chunk.to_dict()

    assert d["text"] == "Test"
    assert d["chunk_id"] == chunk.chunk_id
    assert d["section_title"] == "Section"
    assert d["chunk_type"] == "paragraph"

  def test_chunk_len(self):
    """len(chunk) retorna longitud del text."""
    chunk = Chunk.create(text="Hello", start=0, end=5, index=0)
    assert len(chunk) == 5

  def test_chunk_with_metadata(self):
    """Chunk pot tenir metadata personalitzada."""
    chunk = Chunk.create(
      text="Code",
      start=0,
      end=4,
      index=0,
      metadata={"file_path": "test.py", "language": "python"},
    )

    assert chunk.metadata["file_path"] == "test.py"
    assert chunk.metadata["language"] == "python"

class TestChunkingResultDataclass:
  """Tests per la dataclass ChunkingResult."""

  def test_chunking_result_basic(self):
    """ChunkingResult conté informació correcta."""
    chunks = [
      Chunk.create(text="A", start=0, end=1, index=0),
      Chunk.create(text="B", start=2, end=3, index=1),
    ]

    result = ChunkingResult(
      document_id="doc1",
      chunks=chunks,
      total_chunks=2,
      original_length=100,
      chunker_id="chunker.test",
    )

    assert result.document_id == "doc1"
    assert result.total_chunks == 2
    assert result.original_length == 100
    assert result.chunker_id == "chunker.test"
    assert len(result.chunks) == 2

  def test_chunking_result_get_texts(self):
    """get_texts() retorna només els textos."""
    chunks = [
      Chunk.create(text="First", start=0, end=5, index=0),
      Chunk.create(text="Second", start=6, end=12, index=1),
    ]

    result = ChunkingResult(
      document_id="doc1",
      chunks=chunks,
      total_chunks=2,
      original_length=12,
      chunker_id="test",
    )

    texts = result.get_texts()
    assert texts == ["First", "Second"]

  def test_chunking_result_to_dict(self):
    """to_dict() serialitza tot el resultat."""
    chunks = [Chunk.create(text="Test", start=0, end=4, index=0)]

    result = ChunkingResult(
      document_id="doc1",
      chunks=chunks,
      total_chunks=1,
      original_length=4,
      chunker_id="test",
    )

    d = result.to_dict()

    assert d["document_id"] == "doc1"
    assert d["total_chunks"] == 1
    assert len(d["chunks"]) == 1
    assert d["chunks"][0]["text"] == "Test"

class TestChunkerRegistryCore:
  """Tests pel core del ChunkerRegistry."""

  def setup_method(self):
    reset_registry()

  def test_singleton_pattern(self):
    """get_chunker_registry() retorna singleton."""
    r1 = get_chunker_registry()
    r2 = get_chunker_registry()
    assert r1 is r2

  def test_reset_creates_new_instance(self):
    """reset_registry() elimina el singleton."""
    r1 = get_chunker_registry()
    reset_registry()
    r2 = get_chunker_registry()
    assert r1 is not r2

  def test_auto_discovery_on_init(self):
    """Auto-discovery es fa al crear el registry."""
    registry = get_chunker_registry()

    assert registry.has_chunker("chunker.code")
    assert registry.has_chunker("chunker.text")
    assert len(registry) >= 2

  def test_get_chunker_by_id(self):
    """get_chunker() retorna chunker per ID."""
    registry = get_chunker_registry()

    code = registry.get_chunker("chunker.code")
    text = registry.get_chunker("chunker.text")

    assert isinstance(code, CodeChunker)
    assert isinstance(text, TextChunker)

  def test_get_nonexistent_raises_error(self):
    """get_chunker() amb ID inexistent llança error."""
    registry = get_chunker_registry()

    with pytest.raises(ChunkerNotFoundError):
      registry.get_chunker("chunker.nonexistent")

  def test_format_selection_python(self):
    """Selecció per format Python."""
    registry = get_chunker_registry()

    for ext in ["py", "pyi", "pyx", ".py"]:
      chunker = registry.get_chunker_for_format(ext)
      assert isinstance(chunker, CodeChunker)

  def test_format_selection_javascript(self):
    """Selecció per format JavaScript."""
    registry = get_chunker_registry()

    for ext in ["js", "jsx", "mjs", "ts", "tsx"]:
      chunker = registry.get_chunker_for_format(ext)
      assert isinstance(chunker, CodeChunker)

  def test_format_selection_text(self):
    """Selecció per format text."""
    registry = get_chunker_registry()

    for ext in ["txt", "md", "rst", "log"]:
      chunker = registry.get_chunker_for_format(ext)
      assert isinstance(chunker, TextChunker)

  def test_unknown_format_returns_none(self):
    """Format desconegut retorna None."""
    registry = get_chunker_registry()
    assert registry.get_chunker_for_format("xyz123") is None

  def test_default_chunker_is_text(self):
    """Default chunker és TextChunker."""
    registry = get_chunker_registry()
    default = registry.get_default_chunker()
    assert isinstance(default, TextChunker)

  def test_content_type_selection(self):
    """Selecció per content_type."""
    registry = get_chunker_registry()

    code = registry.get_chunker_for_type("code")
    text = registry.get_chunker_for_type("text")

    assert isinstance(code, CodeChunker)
    assert isinstance(text, TextChunker)

class TestCodeChunkerCore:
  """Tests pel core del CodeChunker."""

  def setup_method(self):
    self.chunker = CodeChunker()

  def test_metadata_correct(self):
    """Metadata del chunker és correcta."""
    assert self.chunker.metadata["id"] == "chunker.code"
    assert "py" in self.chunker.metadata["formats"]
    assert "js" in self.chunker.metadata["formats"]
    assert "code" in self.chunker.metadata["content_types"]

  def test_no_overlap_config(self):
    """Config té chunk_overlap = 0 (Architectural decision)."""
    assert self.chunker.config["chunk_overlap"] == 0

  def test_empty_input(self):
    """Input buit retorna resultat buit."""
    result = self.chunker.chunk("")
    assert result.total_chunks == 0
    assert result.chunks == []

  def test_python_function_detection(self):
    """Detecta funcions Python."""
    code = """def hello():
  print("Hello")

def world():
  return "World"
"""
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks == 2
    assert result.chunks[0].metadata["name"] == "hello"
    assert result.chunks[1].metadata["name"] == "world"

  def test_python_class_detection(self):
    """Detecta classes Python."""
    code = """class MyClass:
  def __init__(self):
    pass

  def method(self):
    return 42
"""
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert result.total_chunks >= 1
    assert "class MyClass" in result.chunks[0].text
    assert result.chunks[0].metadata["code_type"] == "class"

  def test_python_decorator_included(self):
    """Decoradors s'inclouen amb la funció."""
    code = """@decorator
@another
def decorated():
  pass
"""
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    assert "@decorator" in result.chunks[0].text
    assert "@another" in result.chunks[0].text

  def test_javascript_function_detection(self):
    """Detecta funcions JavaScript."""
    code = """function hello() {
  console.log("Hello");
}

async function fetchData() {
  return await fetch(url);
}
"""
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 2
    names = [c.metadata["name"] for c in result.chunks]
    assert "hello" in names
    assert "fetchData" in names

  def test_javascript_arrow_function(self):
    """Detecta arrow functions."""
    code = """const add = (a, b) => {
  return a + b;
};
"""
    result = self.chunker.chunk(code, metadata={"file_path": "test.js"})

    assert result.total_chunks >= 1
    assert result.chunks[0].metadata["code_type"] == "arrow_function"

  def test_no_overlap_between_chunks(self):
    """NO hi ha overlap entre chunks (Architectural decision)."""
    code = """def func1():
  x = 1
  y = 2
  return x + y

def func2():
  a = 10
  b = 20
  return a * b
"""
    result = self.chunker.chunk(code, metadata={"file_path": "test.py"})

    func1_text = result.chunks[0].text
    func2_text = result.chunks[1].text

    assert "x = 1" in func1_text
    assert "x = 1" not in func2_text
    assert "a = 10" in func2_text
    assert "a = 10" not in func1_text

  def test_language_detection(self):
    """Detecta llenguatge per extensió."""
    py_result = self.chunker.chunk("def f(): pass", metadata={"file_path": "a.py"})
    js_result = self.chunker.chunk("function f() {}", metadata={"file_path": "a.js"})
    ts_result = self.chunker.chunk("function f() {}", metadata={"file_path": "a.ts"})

    assert py_result.metadata["language"] == "python"
    assert js_result.metadata["language"] == "javascript"
    assert ts_result.metadata["language"] == "typescript"

class TestTextChunkerCore:
  """Tests pel core del TextChunker."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_metadata_correct(self):
    """Metadata del chunker és correcta."""
    assert self.chunker.metadata["id"] == "chunker.text"
    assert "txt" in self.chunker.metadata["formats"]
    assert "md" in self.chunker.metadata["formats"]
    assert "text" in self.chunker.metadata["content_types"]

  def test_empty_input(self):
    """Input buit retorna resultat buit."""
    result = self.chunker.chunk("")
    assert result.total_chunks == 0

  def test_paragraph_chunking(self):
    """Chunk per paràgrafs (doble newline)."""
    text = """Primer paràgraf amb contingut.

Segon paràgraf amb més contingut.

Tercer paràgraf final."""

    result = self.chunker.chunk(text)

    all_text = " ".join(c.text for c in result.chunks)
    assert "Primer paràgraf" in all_text
    assert "Segon paràgraf" in all_text

  def test_title_detection_uppercase(self):
    """Detecta títols en majúscules."""
    text = """INTRODUCCIÓ

Aquest és el contingut de la introducció."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1
    assert result.chunks[0].section_title == "INTRODUCCIÓ"

  def test_title_detection_markdown(self):
    """Detecta títols markdown (#)."""
    text = """# Secció Principal

Contingut de la secció."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_section_title_propagation(self):
    """Títols es propaguen als chunks següents."""
    text = """SECCIÓ A

Contingut A paràgraf 1.

Contingut A paràgraf 2.

SECCIÓ B

Contingut B."""

    result = self.chunker.chunk(text)

    sections = [c.section_title for c in result.chunks if c.section_title]
    assert len(sections) >= 1

  def test_default_supports_all(self):
    """TextChunker és default, suporta tot sense arguments."""
    assert self.chunker.supports() is True

  def test_chunk_positions(self):
    """Chunks tenen posicions start/end correctes."""
    text = "Primer.\n\nSegon."

    result = self.chunker.chunk(text)

    for chunk in result.chunks:
      assert chunk.start_char >= 0
      assert chunk.end_char > chunk.start_char

class TestChunkerIntegration:
  """Tests d'integració del sistema de chunking."""

  def setup_method(self):
    reset_registry()

  def test_memory_workflow_python(self):
    """Simula workflow Memory amb fitxer Python."""
    registry = get_chunker_registry()

    file_path = "module.py"
    ext = file_path.split(".")[-1]

    chunker = registry.get_chunker_for_format(ext)
    if chunker is None:
      chunker = registry.get_default_chunker()

    code = """
import os

def main():
  print("Main")

class App:
  pass
"""
    result = chunker.chunk(code, document_id=file_path, metadata={"file_path": file_path})

    assert result.chunker_id == "chunker.code"
    assert result.total_chunks >= 2

  def test_memory_workflow_markdown(self):
    """Simula workflow Memory amb fitxer Markdown."""
    registry = get_chunker_registry()

    file_path = "README.md"
    ext = file_path.split(".")[-1]

    chunker = registry.get_chunker_for_format(ext)
    if chunker is None:
      chunker = registry.get_default_chunker()

    text = """# Nexe 0.9

Sistema modular.

- Feature 1
- Feature 2
"""
    result = chunker.chunk(text, document_id=file_path)

    assert result.chunker_id == "chunker.text"
    assert result.total_chunks >= 1

  def test_fallback_to_default(self):
    """Format desconegut usa default chunker."""
    registry = get_chunker_registry()

    chunker = registry.get_chunker_for_format("xyz")
    if chunker is None:
      chunker = registry.get_default_chunker()

    assert isinstance(chunker, TextChunker)

  def test_custom_chunker_registration(self):
    """Pot registrar chunker personalitzat."""
    registry = ChunkerRegistry()

    class CustomChunker(BaseChunker):
      metadata = {
        "id": "chunker.custom",
        "name": "Custom",
        "formats": ["custom"],
        "content_types": [],
      }

      def chunk(self, text, document_id=None, metadata=None):
        return ChunkingResult(
          document_id=document_id,
          chunks=[],
          total_chunks=0,
          original_length=len(text),
          chunker_id=self.metadata["id"],
        )

      def supports(self, file_extension=None, content_type=None):
        return file_extension == "custom"

    registry.register(CustomChunker)

    assert registry.has_chunker("chunker.custom")
    chunker = registry.get_chunker_for_format("custom")
    assert chunker is not None

class TestChunkingNodeIntegration:
  """Tests d'integració amb chunking_node."""

  def setup_method(self):
    reset_registry()

  @pytest.mark.asyncio
  async def test_chunking_node_with_python(self):
    """chunking_node usa CodeChunker per .py."""
    from memory.embeddings.workflow.nodes.chunking_node import chunking_node

    code = """def hello():
  print("Hello")
"""
    result = await chunking_node(
      content=code,
      document_id="test.py",
      file_path="test.py",
    )

    assert result["chunker_id"] == "chunker.code"
    assert result["chunk_count"] >= 1

  @pytest.mark.asyncio
  async def test_chunking_node_with_text(self):
    """chunking_node usa TextChunker per .txt."""
    from memory.embeddings.workflow.nodes.chunking_node import chunking_node

    text = """TITOL

Contingut del document."""

    result = await chunking_node(
      content=text,
      document_id="doc.txt",
      file_path="doc.txt",
    )

    assert result["chunker_id"] == "chunker.text"

  @pytest.mark.asyncio
  async def test_chunking_node_legacy_mode(self):
    """chunking_node sense file_path usa SmartChunker legacy."""
    from memory.embeddings.workflow.nodes.chunking_node import chunking_node

    result = await chunking_node(
      content="Test content.",
      document_id="legacy",
    )

    assert result["chunker_id"] == "legacy.smart_chunker"

  @pytest.mark.asyncio
  async def test_chunking_node_with_content_type(self):
    """chunking_node amb content_type selecciona chunker."""
    from memory.embeddings.workflow.nodes.chunking_node import chunking_node

    code = """def test(): pass"""

    result = await chunking_node(
      content=code,
      document_id="test",
      content_type="code",
    )

    assert result["chunker_id"] == "chunker.code"