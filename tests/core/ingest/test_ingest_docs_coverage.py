"""Tests for core/ingest/ingest_docs.py — coverage gaps."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestIngestDocsModule:
    def test_module_constants(self):
        from core.ingest.ingest_docs import DOCS_COLLECTION, CHUNK_SIZE, CHUNK_OVERLAP
        assert DOCS_COLLECTION == "nexe_documentation"
        assert CHUNK_SIZE == 500
        assert CHUNK_OVERLAP == 50

    def test_ingest_function_exists(self):
        from core.ingest.ingest_docs import ingest_documentation
        assert callable(ingest_documentation)

    def test_chunk_text_called_with_module_constants(self, tmp_path):
        """AP-04: ingest must pass CHUNK_SIZE/CHUNK_OVERLAP to chunk_text.

        Before the fix the call was ``chunk_text(content)`` (no chunk args),
        so the module constants were dead code and the configured chunking
        only worked by coincidence with chunk_text's own defaults. This test
        fails if the constants are not forwarded.
        """
        from core.ingest import ingest_docs
        from core.ingest.ingest_docs import ingest_documentation, CHUNK_SIZE, CHUNK_OVERLAP

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "test.md").write_text("# Test\n\n" + ("word " * 400))

        mock_memory = MagicMock()
        mock_memory.initialize = AsyncMock()
        mock_memory.collection_exists = AsyncMock(return_value=False)
        mock_memory.create_collection = AsyncMock()
        mock_memory.store = AsyncMock(return_value="doc-id")
        mock_memory.close = AsyncMock()

        spy = MagicMock(side_effect=ingest_docs.chunk_text)

        with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
             patch("core.ingest.ingest_docs.PROJECT_ROOT", tmp_path), \
             patch("core.ingest.ingest_docs.chunk_text", spy):
            result = asyncio.run(ingest_documentation())

        assert result is True
        assert spy.call_count >= 1
        # Every chunk_text call must forward the module constants explicitly.
        for call in spy.call_args_list:
            args = call.args
            assert CHUNK_SIZE in args, f"CHUNK_SIZE not passed to chunk_text: {call}"
            assert CHUNK_OVERLAP in args, f"CHUNK_OVERLAP not passed to chunk_text: {call}"
