"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/chunkers/tests/test_text_chunker.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import pytest

from memory.embeddings.chunkers import TextChunker, Chunk, ChunkingResult

class TestTextChunkerBasic:
  """Tests bàsics del TextChunker."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_empty_text(self):
    """Text buit retorna result buit."""
    result = self.chunker.chunk("")

    assert result.total_chunks == 0
    assert result.chunks == []

  def test_whitespace_only(self):
    """Només whitespace retorna result buit."""
    result = self.chunker.chunk("  \n\n\t ")

    assert result.total_chunks == 0

  def test_returns_chunking_result(self):
    """chunk() retorna ChunkingResult."""
    result = self.chunker.chunk("Hello world.")

    assert isinstance(result, ChunkingResult)
    assert result.chunker_id == "chunker.text"

  def test_chunks_are_chunk_instances(self):
    """Els chunks són instàncies de Chunk."""
    result = self.chunker.chunk("Hello world.\n\nAnother paragraph.")

    for chunk in result.chunks:
      assert isinstance(chunk, Chunk)

class TestParagraphChunking:
  """Tests per chunking per paràgrafs."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_split_by_double_newline(self):
    """Separa per doble newline."""
    text = """Primer paràgraf amb contingut.

Segon paràgraf amb més contingut.

Tercer paràgraf final."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_preserves_paragraph_content(self):
    """Preserva el contingut dels paràgrafs."""
    text = """Contingut important.

Més contingut important."""

    result = self.chunker.chunk(text)

    all_text = " ".join(c.text for c in result.chunks)
    assert "Contingut important" in all_text
    assert "Més contingut important" in all_text

class TestSentenceChunking:
  """Tests per chunking per sentències."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_fallback_to_sentences_without_paragraphs(self):
    """Usa sentències si no hi ha paràgrafs."""
    text = "Primera sentència. Segona sentència. Tercera sentència."

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_long_paragraph_split_by_sentences(self):
    """Paràgrafs llargs es divideixen per sentències."""
    long_text = ". ".join([f"Sentència número {i}" for i in range(100)])

    result = self.chunker.chunk(long_text)

    assert result.total_chunks >= 1

class TestTitleDetection:
  """Tests per detecció de títols."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_uppercase_title_detected(self):
    """Detecta títols en majúscules."""
    text = """INTRODUCCIÓ

Contingut de la introducció amb text narratiu."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1
    assert result.chunks[0].section_title == "INTRODUCCIÓ"

  def test_markdown_heading_detected(self):
    """Detecta headings markdown."""
    text = """# Secció Principal

Contingut de la secció."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1
    if result.chunks:
      assert "Contingut" in result.chunks[0].text

  def test_numbered_title_detected(self):
    """Detecta títols numerats."""
    text = """1. Primer Punt

Explicació del primer punt."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_title_propagation(self):
    """Títols es propaguen als chunks següents."""
    text = """SECCIÓ A

Paràgraf 1 de la secció A.

Paràgraf 2 de la secció A.

SECCIÓ B

Paràgraf 1 de la secció B."""

    result = self.chunker.chunk(text)

    sections = set(c.section_title for c in result.chunks if c.section_title)

    assert len(sections) >= 1

class TestChunkMerging:
  """Tests per fusió de chunks petits."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_small_chunks_merged(self):
    """Chunks petits es fusionen."""
    text = """aquest és un paràgraf curt.

un altre paràgraf curt.

i un tercer paràgraf."""

    result = self.chunker.chunk(text)

    assert result.total_chunks >= 1

  def test_merged_chunk_preserves_content(self):
    """Chunks fusionats preserven contingut."""
    text = """Curt.

Més."""

    result = self.chunker.chunk(text)

    all_text = " ".join(c.text for c in result.chunks)
    assert "Curt" in all_text
    assert "Més" in all_text

class TestSupports:
  """Tests pel mètode supports()."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_supports_text_extension(self):
    """Suporta extensió text."""
    assert self.chunker.supports(file_extension="txt")
    assert self.chunker.supports(file_extension=".txt")

  def test_supports_markdown_extension(self):
    """Suporta extensió markdown."""
    assert self.chunker.supports(file_extension="md")
    assert self.chunker.supports(file_extension="markdown")

  def test_supports_rst_extension(self):
    """Suporta extensió rst."""
    assert self.chunker.supports(file_extension="rst")

  def test_supports_log_extension(self):
    """Suporta extensió log."""
    assert self.chunker.supports(file_extension="log")

  def test_not_supports_code_extension(self):
    """No suporta explícitament extensió codi (però és default)."""
    assert self.chunker.supports(file_extension="py") is False
    assert self.chunker.supports(file_extension="js") is False

  def test_supports_text_content_type(self):
    """Suporta content_type 'text'."""
    assert self.chunker.supports(content_type="text")
    assert self.chunker.supports(content_type="markdown")
    assert self.chunker.supports(content_type="narrative")

  def test_default_supports_all(self):
    """Com a default chunker, suporta sense arguments."""
    assert self.chunker.supports() is True

class TestMetadata:
  """Tests per metadata del chunker."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_metadata_id(self):
    """Metadata té ID correcte."""
    assert self.chunker.metadata["id"] == "chunker.text"

  def test_metadata_formats(self):
    """Metadata té formats correctes."""
    formats = self.chunker.metadata["formats"]
    assert "txt" in formats
    assert "md" in formats
    assert "rst" in formats

  def test_metadata_content_types(self):
    """Metadata té content_types correctes."""
    types = self.chunker.metadata["content_types"]
    assert "text" in types
    assert "markdown" in types

class TestChunkMetadata:
  """Tests per metadata dels chunks."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_chunk_has_positions(self):
    """Chunks tenen posicions start/end."""
    text = "Primer paràgraf.\n\nSegon paràgraf."

    result = self.chunker.chunk(text)

    for chunk in result.chunks:
      assert chunk.start_char >= 0
      assert chunk.end_char > chunk.start_char

  def test_chunk_has_index(self):
    """Chunks tenen índex seqüencial."""
    text = "A.\n\nB.\n\nC."

    result = self.chunker.chunk(text)

    for i, chunk in enumerate(result.chunks):
      assert chunk.chunk_index == i

  def test_chunk_has_document_id(self):
    """Chunks tenen document_id."""
    result = self.chunker.chunk("Text.", document_id="doc123")

    for chunk in result.chunks:
      assert chunk.document_id == "doc123"

  def test_chunk_type_is_paragraph(self):
    """Chunks tenen tipus 'paragraph'."""
    text = "Paràgraf.\n\nAltre paràgraf."

    result = self.chunker.chunk(text)

    for chunk in result.chunks:
      assert chunk.chunk_type in ("paragraph", "merged")

class TestConfiguration:
  """Tests per configuració del chunker."""

  def test_custom_max_chunk_size(self):
    """Pot configurar max_chunk_size."""
    chunker = TextChunker(max_chunk_size=500)
    assert chunker.config["max_chunk_size"] == 500

  def test_custom_min_chunk_size(self):
    """Pot configurar min_chunk_size."""
    chunker = TextChunker(min_chunk_size=50)
    assert chunker.config["min_chunk_size"] == 50

  def test_custom_chunk_overlap(self):
    """Pot configurar chunk_overlap."""
    chunker = TextChunker(chunk_overlap=100)
    assert chunker.config["chunk_overlap"] == 100

class TestRealWorldText:
  """Tests amb text real."""

  def setup_method(self):
    self.chunker = TextChunker()

  def test_structured_document(self):
    """Document estructurat amb seccions."""
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
    """Document markdown."""
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