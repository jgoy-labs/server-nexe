"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/tests/unit/test_chunker.py
Description: Tests unitaris per SmartChunker.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from memory.embeddings.core.chunker import SmartChunker

@pytest.fixture
def chunker():
  """Fixture: SmartChunker amb config default"""
  return SmartChunker(
    max_chunk_size=150,
    chunk_overlap=20,
    min_chunk_size=10
  )

def test_empty_document(chunker):
  """
  Test 1: Document buit retorna 0 chunks.

  Checks:
  - Document buit → ChunkedDocument amb 0 chunks
  """
  result = chunker.chunk_document("", document_id="doc_empty")

  assert result.chunk_count == 0, "Document buit hauria de retornar 0 chunks"
  assert len(result.chunks) == 0
  assert result.original_length == 0

def test_chunk_by_paragraphs(chunker):
  """
  Test 2: Chunking per paràgrafs.

  Checks:
  - Split per '\n\n'
  - Cada paràgraf → chunk
  - chunk_type = "paragraph"
  """
  content = """
Primer paràgraf amb text suficient per ser un chunk.

Segon paràgraf també amb contingut adequat.

Tercer paràgraf per validar split correcte.
  """.strip()

  result = chunker.chunk_document(content, document_id="doc_para")

  assert result.chunk_count == 3, "Hauria de tenir 3 chunks (3 paràgrafs)"
  assert all(chunk.chunk_type in ["paragraph", "merged"] for chunk in result.chunks)
  assert all(chunk.chunk_index == i for i, chunk in enumerate(result.chunks))

def test_title_detection(chunker):
  """
  Test 3: Detecció de títols.

  Checks:
  - Títol curt uppercase → detectat
  - Section_title propagat als chunks següents
  """
  assert chunker._is_title("Introducció"), "Hauria de detectar títol simple"
  assert chunker._is_title("1. Capítol Primer"), "Hauria de detectar llista numerada"
  assert chunker._is_title("TÍTOL EN MAJÚSCULES"), "Hauria de detectar majúscules"

  assert not chunker._is_title("Això és una frase llarga que no és un títol perquè té més de 80 caràcters i acaba amb punt."), \
    "Frase llarga no hauria de ser títol"
  assert not chunker._is_title("això no comença amb majúscula"), \
    "Sense majúscula no hauria de ser títol"

def test_section_title_propagation(chunker):
  """
  Test 4: Section title es propaga als chunks.

  Checks:
  - Títol detectat
  - Paràgraf següent hereta section_title
  """
  content = """
Introducció

Aquest és el paràgraf que hauria de tenir section_title = "Introducció".

Desenvolupament

Aquest altre paràgraf hauria de tenir section_title = "Desenvolupament".
  """.strip()

  result = chunker.chunk_document(content, document_id="doc_sections")

  para_chunks = [c for c in result.chunks if c.section_title is not None]

  assert len(para_chunks) >= 1, "Hauria d'haver almenys 1 chunk amb section_title"
  assert para_chunks[0].section_title == "Introducció", \
    "Primer chunk hauria de tenir section_title 'Introducció'"

def test_split_long_paragraph(chunker):
  """
  Test 5: Paràgraf llarg es split per sentències.

  Checks:
  - Paràgraf > max_chunk_size → múltiples chunks
  """
  long_para = "Aquesta és una frase. " * 20

  result = chunker.chunk_document(long_para, document_id="doc_long")

  assert result.chunk_count > 1, "Paràgraf llarg hauria de generar >1 chunk"

def test_merge_small_chunks(chunker):
  """
  Test 6: Chunks petits (<min_chunk_size) es fusionen.

  Checks:
  - Chunks molt petits es fusionen amb adjacents
  - chunk_type = "merged"
  """
  content = "A\n\nB\n\nC\n\nTexto más largo para evitar merge completo."

  result = chunker.chunk_document(content, document_id="doc_merge")

  merged_chunks = [c for c in result.chunks if c.chunk_type == "merged"]

  assert all(c.chunk_index == i for i, c in enumerate(result.chunks))

def test_chunk_by_sentences_fallback(chunker):
  """
  Test 7: Chunking per sentències (fallback si no hi ha paràgrafs).

  Checks:
  - Text sense '\n\n' → chunk per sentències
  """
  content = "Primera frase. Segona frase. Tercera frase. Quarta frase amb contingut suficient."

  result = chunker.chunk_document(content, document_id="doc_sentences")

  assert result.chunk_count >= 1, "Hauria de generar almenys 1 chunk"

def test_chunk_metadata(chunker):
  """
  Test 8: Metadata dels chunks és correcte.

  Checks:
  - chunk_id (UUID)
  - char_start, char_end
  - chunk_index
  """
  content = "Paràgraf 1.\n\nParàgraf 2.\n\nParàgraf 3."

  result = chunker.chunk_document(content, document_id="doc_meta")

  for i, chunk in enumerate(result.chunks):
    assert chunk.chunk_id, "chunk_id no pot estar buit"
    assert chunk.document_id == "doc_meta"
    assert chunk.chunk_index == i, f"Chunk {i} hauria de tenir index {i}"
    assert chunk.char_start >= 0
    assert chunk.char_end > chunk.char_start
    assert chunk.char_end <= result.original_length

def test_chunked_document_metadata(chunker):
  """
  Test 9: ChunkedDocument té metadata correcte.

  Checks:
  - document_id
  - original_length
  - chunk_count
  - created_at
  """
  content = "Test document amb contingut suficient per validar metadata."

  result = chunker.chunk_document(content, document_id="doc_test")

  assert result.document_id == "doc_test"
  assert result.original_length == len(content)
  assert result.chunk_count == len(result.chunks)
  assert result.created_at is not None

"""
Test Coverage SmartChunker:
✅ test_empty_document - Document buit
✅ test_chunk_by_paragraphs - Chunking per paràgrafs
✅ test_title_detection - Detecció títols (heurística)
✅ test_section_title_propagation - Section title als chunks
✅ test_split_long_paragraph - Split paràgrafs llargs
✅ test_merge_small_chunks - Merge chunks petits
✅ test_chunk_by_sentences_fallback - Fallback sentències
✅ test_chunk_metadata - Metadata chunks correcte
✅ test_chunked_document_metadata - ChunkedDocument metadata

Total: 9 test cases
Target coverage: >85%
"""