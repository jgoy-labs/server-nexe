"""Tests for core/ingest/ingest_docs.py — coverage gaps."""


class TestIngestDocsModule:
    def test_module_constants(self):
        from core.ingest.ingest_docs import DOCS_COLLECTION, CHUNK_SIZE, CHUNK_OVERLAP
        assert DOCS_COLLECTION == "nexe_documentation"
        assert CHUNK_SIZE == 500
        assert CHUNK_OVERLAP == 50

    def test_ingest_function_exists(self):
        from core.ingest.ingest_docs import ingest_documentation
        assert callable(ingest_documentation)
