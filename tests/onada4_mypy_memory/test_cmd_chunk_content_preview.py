"""TDD tests Cluster B — `memory/embeddings/__main__.py:95`.

Cluster B: REAL — AttributeError guaranteed in the cmd_chunk CLI.
Root cause: `chunk.content[:100] + "..."` where ChunkMetadata has no 'content' attribute.
Director decision (Onada 4.5-residual): B-LOCAL — re-read text via
char_start/char_end in __main__.py, fallback to f"chars {char_start}-{char_end}".

Test 1 (xfail strict): demonstrates the bug — AttributeError pre-fix.
Test 2 (anti-regression): pins char_start/char_end as the premise of the B-LOCAL fix
                           and verifies that 'content' is NOT in the model (B-LOCAL local).
"""

from __future__ import annotations

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_cmd_chunk_raises_attribute_error_content_missing(tmp_path) -> None:
    """Post-fix B-LOCAL: cmd_chunk does not raise AttributeError.

    Fix B-LOCAL: __main__.py:95 uses content[char_start:char_end] instead of
    chunk.content. The original text already read in the same function is used to
    generate the preview — without accessing any non-existent attribute.
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
        # If we get here without exception → bug fixed → XPASS (strict: error)


def test_chunk_metadata_char_range_contract_for_b_local() -> None:
    """Anti-regression: ChunkMetadata has char_start/char_end (premise of the B-LOCAL fix).

    The B-LOCAL fix accesses text[chunk.char_start:chunk.char_end] and the fallback uses
    f"chars {chunk.char_start}-{chunk.char_end}". If anyone removes or renames these
    fields, the fix would fail at runtime.

    Also: 'content' must NOT exist in the model. B-LOCAL is a LOCAL fix to __main__.py
    — it does not add fields to ChunkMetadata. If anyone introduces 'content' to the model
    (option B1 discarded by the Director), this test detects it.
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
        "ChunkMetadata has lost char_start — B-LOCAL premise broken"
    )
    assert hasattr(chunk, "char_end"), (
        "ChunkMetadata has lost char_end — B-LOCAL premise broken"
    )
    assert isinstance(chunk.char_start, int), (
        "char_start is not int — B-LOCAL fix would produce an invalid slice"
    )
    assert isinstance(chunk.char_end, int), (
        "char_end is not int — B-LOCAL fix would produce an invalid slice"
    )
    assert chunk.char_start >= 0, (
        "char_start is negative — B-LOCAL would produce an unexpected slice"
    )
    assert chunk.char_end > chunk.char_start, (
        "char_end ≤ char_start — B-LOCAL would produce an empty slice"
    )
    assert not hasattr(chunk, "content"), (
        "'content' has appeared in ChunkMetadata — option B1 applied without Director decision. "
        "B-LOCAL requires a LOCAL fix to __main__.py, NOT to the model."
    )
