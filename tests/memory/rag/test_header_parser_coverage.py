"""
Additional coverage tests for memory/rag/header_parser.py
Covers: create_header, parse_rag_header, create_rag_header, get_parser,
        _parse_list edge cases, _validate edge cases, invalid date formats
"""

import pytest
from unittest.mock import patch

from memory.rag.header_parser import (
    RAGHeaderParser,
    RAGHeader,
    parse_rag_header,
    create_rag_header,
    get_parser,
    VALID_PRIORITIES,
    VALID_TYPES,
    VALID_LANGS,
)


class TestCreateHeader:
    """Tests for RAGHeaderParser.create_header()."""

    def setup_method(self):
        self.parser = RAGHeaderParser()

    def test_create_basic_header(self):
        result = self.parser.create_header(
            id="test-doc",
            abstract="Test document description",
            tags=["test", "unit"],
            priority="P1",
            chunk_size=800,
        )
        assert "test-doc" in result
        assert "Test document description" in result
        assert "test, unit" in result
        assert "P1" in result
        assert "---" in result

    def test_create_header_with_all_optional_fields(self):
        result = self.parser.create_header(
            id="full-doc",
            abstract="Full test",
            tags=["tag1"],
            priority="P0",
            lang="es",
            type="tutorial",
            collection="personal_memory",
            author="Test Author",
            expires="2027-01-01",
            related=["doc-a", "doc-b"],
        )
        assert "full-doc" in result
        assert "lang: es" in result
        assert "type: tutorial" in result
        assert "collection: personal_memory" in result
        assert 'author: "Test Author"' in result
        assert "expires: 2027-01-01" in result
        assert "related:" in result
        assert "doc-a" in result

    def test_create_header_null_expires(self):
        result = self.parser.create_header(
            id="no-expire",
            abstract="No expiry",
            tags=["test"],
        )
        assert "expires: null" in result

    def test_create_header_no_related(self):
        result = self.parser.create_header(
            id="no-rel",
            abstract="No related",
            tags=["test"],
        )
        assert "related:" not in result

    def test_create_header_truncates_abstract(self):
        """create_header must truncate abstract to 500 chars (header_parser.py:355).

        The ORIGINAL test (T78) only asserted `len(long_abstract[:500]) == 500`
        — a slice of the test's OWN local variable, never touching `result`.
        This version asserts on the actual return value of create_header().

        Mutation target: header_parser.py:355
          abstract: "{abstract[:500]}"
        If the [:500] slice is removed, `result` contains the full 600-char
        abstract and this test must go RED.
        """
        long_abstract = "a" * 600
        result = self.parser.create_header(
            id="long-abs",
            abstract=long_abstract,
            tags=["test"],
        )
        # Extract what's between the quotes of the abstract line in the result
        import re
        match = re.search(r'^abstract: "(.+)"$', result, re.MULTILINE)
        assert match is not None, "abstract field not found in result"
        abstract_in_result = match.group(1)
        assert len(abstract_in_result) <= 500, (
            f"abstract must be truncated to 500 chars, got {len(abstract_in_result)}"
        )
        assert len(abstract_in_result) == 500, (
            "abstract of 600 chars should yield exactly 500 chars in result"
        )
        assert abstract_in_result == "a" * 500, (
            "truncated abstract must be the first 500 chars of the input"
        )


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_parse_rag_header(self):
        content = """# === METADATA RAG ===
versio: "1.0"
data: 2025-01-01
id: helper-test
abstract: "Helper test"
tags: [test]
chunk_size: 800
priority: P1
---

Body content here.
"""
        header, body = parse_rag_header(content)
        assert header.id == "helper-test"
        assert "Body content" in body

    def test_create_rag_header(self):
        result = create_rag_header(
            id="create-test",
            abstract="Created header",
            tags=["test"],
        )
        assert "create-test" in result
        assert "---" in result

    def test_get_parser(self):
        parser = get_parser()
        assert isinstance(parser, RAGHeaderParser)


class TestValidateEdgeCases:
    """Edge case tests for validation."""

    def setup_method(self):
        self.parser = RAGHeaderParser()

    def test_invalid_lang(self):
        header = RAGHeader(
            id="test", abstract="Test", tags=["t"],
            chunk_size=800, priority="P1", lang="fr"
        )
        errors = self.parser._validate(header)
        assert any("lang" in e for e in errors)

    def test_invalid_type(self):
        header = RAGHeader(
            id="test", abstract="Test", tags=["t"],
            chunk_size=800, priority="P1", type="invalid_type"
        )
        errors = self.parser._validate(header)
        assert any("type" in e for e in errors)

    def test_invalid_date_format(self):
        header = RAGHeader(
            id="test", abstract="Test", tags=["t"],
            chunk_size=800, priority="P1", data="01-01-2025"
        )
        errors = self.parser._validate(header)
        assert any("data" in e for e in errors)

    def test_invalid_expires_format(self):
        header = RAGHeader(
            id="test", abstract="Test", tags=["t"],
            chunk_size=800, priority="P1", expires="not-a-date"
        )
        errors = self.parser._validate(header)
        assert any("expires" in e for e in errors)

    def test_parse_list_non_list_non_string(self):
        result = self.parser._parse_list(123)
        assert result == []
