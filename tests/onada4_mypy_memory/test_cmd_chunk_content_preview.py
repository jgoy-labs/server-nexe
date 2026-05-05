"""TDD tests Cluster B — `memory/embeddings/__main__.py:95`.

Cluster B: REAL — AttributeError garantit a cmd_chunk CLI.
Arrel: `chunk.content[:100] + "..."` on ChunkMetadata no té atribut 'content'.
Decisió Director (Onada 4.5-residual): B-LOCAL — rellegir text via
char_start/char_end al __main__.py, fallback a f"chars {char_start}-{char_end}".

Test 1 (xfail strict): demostra el bug — AttributeError pre-fix.
Test 2 (anti-regressió): pina char_start/char_end com a premissa del fix B-LOCAL
                          i verifica que 'content' NO és al model (B-LOCAL local).
"""

from __future__ import annotations

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_cmd_chunk_raises_attribute_error_content_missing(tmp_path) -> None:
    """Post-fix B-LOCAL: cmd_chunk no llança AttributeError.

    Fix B-LOCAL: __main__.py:95 usa content[char_start:char_end] en lloc de
    chunk.content. El text original ja llegit a la mateixa funció s'usa per
    generar el preview — sense accés a cap atribut inexistent.
    """
    from memory.embeddings.core.interfaces import ChunkMetadata, ChunkedDocument

    doc_file = tmp_path / "test.md"
    doc_file.write_text("Hello world test document for TDD cluster B.")

    chunk = ChunkMetadata(
        chunk_id="c1-tdd-b",
        document_id="test",
        chunk_index=0,
        char_start=0,
        char_end=44,
    )
    chunked_doc = ChunkedDocument(
        document_id="test",
        original_length=44,
        chunks=[chunk],
        chunk_count=1,
    )

    mock_module = MagicMock()
    mock_module._initialized = True
    mock_module.chunk_document = AsyncMock(return_value=chunked_doc)

    with patch("memory.embeddings.module.EmbeddingsModule") as MockEM:
        MockEM.get_instance.return_value = mock_module
        import memory.embeddings.__main__ as m
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            asyncio.run(m.cmd_chunk(str(doc_file)))
        # Si arriba aquí sense excepció → bug arreglat → XPASS (strict: error)


def test_chunk_metadata_char_range_contract_for_b_local() -> None:
    """Anti-regressió: ChunkMetadata té char_start/char_end (premissa del fix B-LOCAL).

    El fix B-LOCAL accedeix text[chunk.char_start:chunk.char_end] i el fallback usa
    f"chars {chunk.char_start}-{chunk.char_end}". Si algú elimina o renombra aquests
    camps, el fix fallaria en runtime.

    A més: 'content' NO ha d'existir al model. B-LOCAL és un fix LOCAL a __main__.py
    — no afegeix camps a ChunkMetadata. Si algú introdueix 'content' al model
    (opció B1 descartada pel Director), aquest test ho detecta.
    """
    from memory.embeddings.core.interfaces import ChunkMetadata

    chunk = ChunkMetadata(
        chunk_id="c-anti-reg",
        document_id="doc",
        chunk_index=0,
        char_start=10,
        char_end=50,
    )

    assert hasattr(chunk, "char_start"), (
        "ChunkMetadata ha perdut char_start — premissa B-LOCAL trencada"
    )
    assert hasattr(chunk, "char_end"), (
        "ChunkMetadata ha perdut char_end — premissa B-LOCAL trencada"
    )
    assert isinstance(chunk.char_start, int), (
        "char_start no és int — fix B-LOCAL produiria slice invàlid"
    )
    assert isinstance(chunk.char_end, int), (
        "char_end no és int — fix B-LOCAL produiria slice invàlid"
    )
    assert chunk.char_start >= 0, (
        "char_start negatiu — B-LOCAL produiria slice inesperat"
    )
    assert chunk.char_end > chunk.char_start, (
        "char_end ≤ char_start — B-LOCAL produiria slice buit"
    )
    assert not hasattr(chunk, "content"), (
        "'content' ha aparegut a ChunkMetadata — opció B1 aplicada sense decisió Director. "
        "B-LOCAL exigeix fix LOCAL a __main__.py, NO al model."
    )
