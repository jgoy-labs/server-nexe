"""Tests for memory/embeddings/core/chunker.py — coverage gaps."""


class TestSmartChunker:
    def test_init_defaults(self):
        from memory.embeddings.core.chunker import SmartChunker
        c = SmartChunker()
        assert c is not None

    def test_chunk_short_document(self):
        from memory.embeddings.core.chunker import SmartChunker
        c = SmartChunker()
        result = c.chunk_document("Short text here.", "doc1")
        assert result.chunk_count >= 1
        assert result.document_id == "doc1"

    def test_chunk_long_document(self):
        from memory.embeddings.core.chunker import SmartChunker
        c = SmartChunker()
        text = "This is a paragraph with content. " * 100
        result = c.chunk_document(text, "doc2")
        assert result.chunk_count > 1

    def test_chunk_with_sections(self):
        from memory.embeddings.core.chunker import SmartChunker
        c = SmartChunker()
        text = "# Title\n\nFirst section content.\n\n## Subtitle\n\nSecond section content."
        result = c.chunk_document(text, "doc3")
        assert result.chunk_count >= 1

    def test_chunk_empty(self):
        from memory.embeddings.core.chunker import SmartChunker
        c = SmartChunker()
        result = c.chunk_document("", "doc4")
        assert result.chunk_count == 0
        assert result.original_length == 0
