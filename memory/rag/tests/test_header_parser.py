"""
Tests per memory/rag/header_parser.py
"""
import os
import pytest
from unittest.mock import patch

from memory.rag.header_parser import (
    RAGHeader,
    RAGHeaderParser,
    HEADER_VERSION,
    HEADER_START,
    VALID_PRIORITIES,
    VALID_TYPES,
    VALID_LANGS,
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    DEFAULT_CHUNK_SIZE,
    MIN_TAGS,
    MAX_TAGS,
)


class TestRAGHeader:
    def test_default_creation(self):
        header = RAGHeader()
        assert header.versio == HEADER_VERSION
        assert header.is_valid is False
        assert header.chunk_size == DEFAULT_CHUNK_SIZE
        assert header.priority == "P2"
        assert header.type == "docs"
        assert header.collection == "user_knowledge"

    def test_to_dict(self):
        header = RAGHeader(
            id="test-id",
            abstract="Prova",
            tags=["tag1", "tag2"],
            priority="P1"
        )
        d = header.to_dict()
        assert d["id"] == "test-id"
        assert d["abstract"] == "Prova"
        assert d["tags"] == ["tag1", "tag2"]
        assert d["priority"] == "P1"
        assert "versio" in d
        assert "collection" in d

    def test_to_dict_all_fields(self):
        header = RAGHeader()
        d = header.to_dict()
        expected_keys = ["versio", "data", "id", "abstract", "tags",
                         "chunk_size", "priority", "lang", "type",
                         "collection", "author", "expires", "related"]
        for key in expected_keys:
            assert key in d


class TestRAGHeaderParserConstants:
    def test_valid_priorities(self):
        assert "P0" in VALID_PRIORITIES
        assert "P1" in VALID_PRIORITIES
        assert "P2" in VALID_PRIORITIES
        assert "P3" in VALID_PRIORITIES

    def test_valid_types(self):
        assert "docs" in VALID_TYPES
        assert "tutorial" in VALID_TYPES
        assert "api" in VALID_TYPES

    def test_chunk_size_limits(self):
        assert MIN_CHUNK_SIZE == 400
        assert MAX_CHUNK_SIZE == 2000
        assert DEFAULT_CHUNK_SIZE == 800


class TestRAGHeaderParser:
    def setup_method(self):
        self.parser = RAGHeaderParser()

    VALID_DOC = """# === METADATA RAG ===
versio: "1.0"
data: 2025-01-01
id: test-document-id
abstract: "Descripció del document de prova"
tags: [nexe, test, documentació]
chunk_size: 800
priority: P1
lang: ca
type: docs
---

Contingut del document aquí.
"""

    def test_parse_valid_header(self):
        header, body = self.parser.parse(self.VALID_DOC)
        assert header.is_valid is True
        assert header.id == "test-document-id"
        assert header.abstract == "Descripció del document de prova"
        assert len(header.tags) == 3
        assert header.priority == "P1"
        assert header.lang == "ca"
        assert header.type == "docs"
        assert "Contingut" in body

    def test_parse_no_header(self):
        content = "Document sense capçalera RAG."
        header, body = self.parser.parse(content)
        assert header.is_valid is False
        assert "No RAG header found" in header.validation_errors
        assert body == content

    def test_parse_empty_string(self):
        header, body = self.parser.parse("")
        assert header.is_valid is False

    def test_parse_header_missing_id(self):
        doc = """# === METADATA RAG ===
abstract: "Prova sense id"
tags: [test]
chunk_size: 800
priority: P1
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.is_valid is False
        assert any("id" in e.lower() for e in header.validation_errors)

    def test_parse_header_missing_abstract(self):
        doc = """# === METADATA RAG ===
id: test-id
tags: [test]
chunk_size: 800
priority: P1
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.is_valid is False
        assert any("abstract" in e.lower() for e in header.validation_errors)

    def test_parse_header_no_tags(self):
        doc = """# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: []
chunk_size: 800
priority: P1
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.is_valid is False
        assert any("tag" in e.lower() for e in header.validation_errors)

    def test_parse_invalid_priority(self):
        doc = """# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [test]
chunk_size: 800
priority: P9
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.is_valid is False
        assert any("priority" in e.lower() for e in header.validation_errors)

    def test_parse_chunk_size_too_small(self):
        doc = f"""# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [test]
chunk_size: {MIN_CHUNK_SIZE - 1}
priority: P1
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.is_valid is False

    def test_parse_chunk_size_too_large(self):
        doc = f"""# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [test]
chunk_size: {MAX_CHUNK_SIZE + 1}
priority: P1
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.is_valid is False

    def test_parse_too_many_tags(self):
        tags = ", ".join([f"tag{i}" for i in range(MAX_TAGS + 1)])
        doc = f"""# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [{tags}]
chunk_size: 800
priority: P1
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.is_valid is False

    def test_parse_list_from_string(self):
        header, body = self.parser.parse(self.VALID_DOC)
        assert isinstance(header.tags, list)
        assert len(header.tags) > 0

    def test_parse_int_valid(self):
        result = self.parser._parse_int("800", 500)
        assert result == 800

    def test_parse_int_invalid(self):
        result = self.parser._parse_int("not_a_number", 500)
        assert result == 500

    def test_parse_int_none(self):
        result = self.parser._parse_int(None, 500)
        assert result == 500

    def test_parse_list_from_list(self):
        result = self.parser._parse_list(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_parse_list_from_empty_list(self):
        result = self.parser._parse_list([])
        assert result == []

    def test_parse_list_from_string_bracket(self):
        result = self.parser._parse_list("[tag1, tag2]")
        assert "tag1" in result
        assert "tag2" in result

    def test_parse_list_from_empty_string(self):
        result = self.parser._parse_list("")
        assert result == []

    def test_parse_list_from_simple_string(self):
        result = self.parser._parse_list("singlevalue")
        assert result == ["singlevalue"]

    def test_parse_yaml_like_comments(self):
        text = "# Comentari\nid: test-id\n"
        result = self.parser._parse_yaml_like(text)
        assert "id" in result
        assert result["id"] == "test-id"

    def test_parse_yaml_like_list_value(self):
        text = "tags: [tag1, tag2, tag3]\n"
        result = self.parser._parse_yaml_like(text)
        assert "tags" in result
        assert isinstance(result["tags"], list)
        assert len(result["tags"]) == 3

    def test_extract_header_with_versio_marker(self):
        """Capçalera que comença directament amb 'versio:'"""
        content = """versio: "1.0"
id: test-id
abstract: "Test"
tags: [test]
priority: P1

Contingut
"""
        header_text, body = self.parser._extract_header(content)
        assert "id" in header_text

    def test_parse_with_expires(self):
        doc = """# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [test]
chunk_size: 800
priority: P1
expires: 2026-12-31
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.expires == "2026-12-31"

    def test_parse_with_null_expires(self):
        doc = """# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [test]
chunk_size: 800
priority: P1
expires: null
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.expires is None

    def test_parse_with_author(self):
        doc = """# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [test]
chunk_size: 800
priority: P1
author: Jordi Goy
---

Contingut
"""
        header, body = self.parser.parse(doc)
        assert header.author == "Jordi Goy"

    def test_parse_body_returned_correctly(self):
        header, body = self.parser.parse(self.VALID_DOC)
        assert "Contingut del document" in body
        assert "METADATA RAG" not in body

    def test_lang_from_env(self):
        with patch.dict(os.environ, {"NEXE_LANG": "es-ES"}):
            doc = """# === METADATA RAG ===
id: test-id
abstract: "Prova"
tags: [test]
chunk_size: 800
priority: P1
---

Contingut
"""
            header, body = self.parser.parse(doc)
            # Lang per defecte ve de NEXE_LANG → "es"
            assert header.lang == "es"

    def test_abstract_too_long_validation(self):
        long_abstract = "a" * 601
        header = RAGHeader(
            id="test-id",
            abstract=long_abstract,
            tags=["test"],
            chunk_size=800,
            priority="P1"
        )
        errors = self.parser._validate(header)
        assert any("abstract" in e.lower() for e in errors)
