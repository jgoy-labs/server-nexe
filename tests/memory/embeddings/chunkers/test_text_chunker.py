"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/chunkers/tests/test_text_chunker.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from memory.embeddings.chunkers import TextChunker, Chunk, ChunkingResult

class TestTextChunkerBasic:
  """Basic tests for TextChunker."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_empty_text(self):
    """Empty text returns empty result."""
    result = self.chunker.chunk("")

    assert result.total_chunks == 0
    assert result.chunks == []

  def test_whitespace_only(self):
    """Whitespace only returns empty result."""
    result = self.chunker.chunk("  \n\n\t ")

    assert result.total_chunks == 0

  def test_returns_chunking_result(self):
    """chunk() returns ChunkingResult."""
    result = self.chunker.chunk("Hello world.")

    assert isinstance(result, ChunkingResult)
    assert result.chunker_id == "chunker.text"

  def test_chunks_are_chunk_instances(self):
    """Chunks are instances of Chunk."""
    result = self.chunker.chunk("Hello world.\n\nAnother paragraph.")

    for chunk in result.chunks:
      assert isinstance(chunk, Chunk)

class TestParagraphChunking:
  """Tests for paragraph-based chunking."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_split_by_double_newline(self):
    """Splits by double newline."""
    text = """Primer paràgraf amb contingut.

Segon paràgraf amb més contingut.

Tercer paràgraf final."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_preserves_paragraph_content(self):
    """Preserves paragraph content."""
    text = """Contingut important.

Més contingut important."""

    result = self.chunker.chunk(text)

    all_text = " ".join(c.text for c in result.chunks)
    assert "Contingut important" in all_text
    assert "Més contingut important" in all_text

class TestSentenceChunking:
  """Tests for sentence-based chunking."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_fallback_to_sentences_without_paragraphs(self):
    """Uses sentences if there are no paragraphs."""
    text = "Primera sentència. Segona sentència. Tercera sentència."

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_long_paragraph_split_by_sentences(self):
    """Long paragraphs are split by sentences."""
    long_text = ". ".join([f"Sentència número {i}" for i in range(100)])

    result = self.chunker.chunk(long_text)

    assert result.total_chunks >= 1

class TestTitleDetection:
  """Tests for title detection."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_uppercase_title_detected(self):
    """Detects uppercase titles."""
    text = """INTRODUCCIÓ

Contingut de la introducció amb text narratiu."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1
    assert result.chunks[0].section_title == "INTRODUCCIÓ"

  def test_markdown_heading_detected(self):
    """Detects markdown headings."""
    text = """# Secció Principal

Contingut de la secció."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1
    if result.chunks:
      assert "Contingut" in result.chunks[0].text

  def test_numbered_title_detected(self):
    """Detects numbered titles."""
    text = """1. Primer Punt

Explicació del primer punt."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_title_propagation(self):
    """Titles propagate to subsequent chunks."""
    text = """SECCIÓ A

Paràgraf 1 de la secció A.

Paràgraf 2 de la secció A.

SECCIÓ B

Paràgraf 1 de la secció B."""

    result = self.chunker.chunk(text)

    sections = set(c.section_title for c in result.chunks if c.section_title)

    assert len(sections) >= 1

class TestChunkMerging:
  """Tests for small chunk merging."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_small_chunks_merged(self):
    """Small chunks are merged."""
    text = """aquest és un paràgraf curt.

un altre paràgraf curt.

i un tercer paràgraf."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_merged_chunk_preserves_content(self):
    """Merged chunks preserve content."""
    text = """Curt.

Més."""

    result = self.chunker.chunk(text)

    all_text = " ".join(c.text for c in result.chunks)
    assert "Curt" in all_text
    assert "Més" in all_text

class TestSupports:
  """Tests for the supports() method."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_supports_text_extension(self):
    """Supports text extension."""
    assert self.chunker.supports(file_extension="txt")
    assert self.chunker.supports(file_extension=".txt")

  def test_supports_markdown_extension(self):
    """Supports markdown extension."""
    assert self.chunker.supports(file_extension="md")
    assert self.chunker.supports(file_extension="markdown")

  def test_supports_rst_extension(self):
    """Supports rst extension."""
    assert self.chunker.supports(file_extension="rst")

  def test_supports_log_extension(self):
    """Supports log extension."""
    assert self.chunker.supports(file_extension="log")

  def test_not_supports_code_extension(self):
    """Does not explicitly support code extension (but is default)."""
    assert self.chunker.supports(file_extension="py") is False
    assert self.chunker.supports(file_extension="js") is False

  def test_supports_text_content_type(self):
    """Supports content_type 'text'."""
    assert self.chunker.supports(content_type="text")
    assert self.chunker.supports(content_type="markdown")
    assert self.chunker.supports(content_type="narrative")

  def test_default_supports_all(self):
    """As default chunker, supports without arguments."""
    assert self.chunker.supports() is True

class TestMetadata:
  """Tests for chunker metadata."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_metadata_id(self):
    """Metadata has correct ID."""
    assert self.chunker.metadata["id"] == "chunker.text"

  def test_metadata_formats(self):
    """Metadata has correct formats."""
    formats = self.chunker.metadata["formats"]
    assert "txt" in formats
    assert "md" in formats
    assert "rst" in formats

  def test_metadata_content_types(self):
    """Metadata has correct content_types."""
    types = self.chunker.metadata["content_types"]
    assert "text" in types
    assert "markdown" in types

class TestChunkMetadata:
  """Tests for chunk metadata."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_chunk_has_positions(self):
    """Chunks have start/end positions."""
    text = "Primer paràgraf.\n\nSegon paràgraf."

    result = self.chunker.chunk(text)

    for chunk in result.chunks:
      assert chunk.start_char >= 0
      assert chunk.end_char > chunk.start_char

  def test_chunk_has_index(self):
    """Chunks have sequential index."""
    text = "A.\n\nB.\n\nC."

    result = self.chunker.chunk(text)

    for i, chunk in enumerate(result.chunks):
      assert chunk.chunk_index == i

  def test_chunk_has_document_id(self):
    """Chunks have document_id."""
    result = self.chunker.chunk("Text.", document_id="doc123")

    for chunk in result.chunks:
      assert chunk.document_id == "doc123"

  def test_chunk_type_is_paragraph(self):
    """Chunks have type 'paragraph'."""
    text = "Paràgraf.\n\nAltre paràgraf."

    result = self.chunker.chunk(text)

    for chunk in result.chunks:
      assert chunk.chunk_type in ("paragraph", "merged")

class TestConfiguration:
  """Tests for chunker configuration."""

  def test_custom_max_chunk_size(self):
    """Can configure max_chunk_size."""
    chunker = TextChunker(max_chunk_size=500)
    assert chunker.config["max_chunk_size"] == 500

  def test_custom_min_chunk_size(self):
    """Can configure min_chunk_size."""
    chunker = TextChunker(min_chunk_size=50)
    assert chunker.config["min_chunk_size"] == 50

  def test_custom_chunk_overlap(self):
    """Can configure chunk_overlap."""
    chunker = TextChunker(chunk_overlap=100)
    assert chunker.config["chunk_overlap"] == 100

class TestRealWorldText:
  """Tests with real-world text."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_structured_document(self):
    """Structured document with sections."""
    text = """INTRODUCCIÓ

Aquest document presenta una visió general del projecte.
L'objectiu és proporcionar context i informació rellevant.

METODOLOGIA

S'ha utilitzat una aproximació iterativa.
Els resultats s'han validat amb múltiples experiments.

CONCLUSIONS

El projecte ha assolit els seus objectius.
Es recomana continuar amb la següent fase."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

    sections = set(c.section_title for c in result.chunks if c.section_title)
    assert len(sections) >= 1

  def test_markdown_document(self):
    """Markdown document."""
    text = """# Títol Principal

Paràgraf introductori amb **text en negreta** i *cursiva*.

Contingut de la subsecció amb:
- Punt 1
- Punt 2
- Punt 3

Més contingut amb `codi inline` i altres elements."""

    result = self.chunker.chunk(text, metadata={"file_path": "doc.md"})

    assert result.total_chunks >= 1
    assert result.chunker_id == "chunker.text"

class TestMergeSmallChunksFinal:
  """MEM-006: a trailing chunk below min_chunk_size must be merged, not emitted raw."""

  def setup_method(self):
    self.chunker = TextChunker()
    self.min_size = self.chunker.config["min_chunk_size"]

  def test_trailing_small_chunk_is_folded_into_previous(self):
    """A small chunk that follows a large one (and is last) must not survive raw."""
    big_text = "x" * (self.min_size + 50)
    small_text = "tiny"
    chunks = [
      Chunk.create(text=big_text, start=0, end=len(big_text), index=0),
      Chunk.create(
        text=small_text,
        start=len(big_text),
        end=len(big_text) + len(small_text),
        index=1,
      ),
    ]

    merged = self.chunker._merge_small_chunks(chunks)

    # No chunk may remain below min_chunk_size: the small trailing chunk
    # must have been folded into its predecessor.
    assert all(len(c.text) >= self.min_size for c in merged), [
      len(c.text) for c in merged
    ]
    assert len(merged) == 1
    assert small_text in merged[0].text
    assert merged[0].chunk_type == "merged"
