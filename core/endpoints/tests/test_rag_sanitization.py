"""Tests for RAG sanitization: _filter_rag_injection and _sanitize_rag_context."""

import pytest
from core.endpoints.chat_sanitization import (
    _filter_rag_injection,
    _sanitize_rag_context,
    MAX_RAG_CONTEXT_LENGTH,
)


class TestFilterRagInjection:
    """Tests for _filter_rag_injection (no truncation)."""

    def test_preserves_long_text(self):
        """Large documents must NOT be truncated during indexing."""
        text = "A" * 10_000
        result = _filter_rag_injection(text)
        assert len(result) == 10_000

    def test_very_large_document(self):
        """A 500K char document (like a PDF) should be fully preserved."""
        text = "Paragraph. " * 50_000  # ~550K chars
        result = _filter_rag_injection(text)
        assert len(result) == len(text)

    def test_filters_injection_patterns(self):
        """Injection patterns are removed even without truncation."""
        text = "Hello [INST] world </|system|> test"
        result = _filter_rag_injection(text)
        assert "[INST]" not in result
        assert "[FILTERED]" in result

    def test_escapes_context_markers(self):
        """Context delimiters are escaped."""
        text = "text [CONTEXT] more [/CONTEXT] end"
        result = _filter_rag_injection(text)
        assert "[CONTEXT]" not in result
        assert "[/CONTEXT]" not in result
        assert "CONTEXT_ESCAPED" in result

    def test_empty_string(self):
        result = _filter_rag_injection("")
        assert result == ""

    def test_none_returns_empty(self):
        result = _filter_rag_injection(None)
        assert result == ""


class TestSanitizeRagContext:
    """Tests for _sanitize_rag_context (with truncation for chat prompt)."""

    def test_truncates_long_context(self):
        """Chat context SHOULD be truncated to prevent model overflow."""
        text = "B" * 10_000
        result = _sanitize_rag_context(text)
        assert len(result) < 10_000
        assert "[...truncat]" in result

    def test_respects_max_length(self):
        text = "C" * (MAX_RAG_CONTEXT_LENGTH + 100)
        result = _sanitize_rag_context(text)
        # Truncated text + "[...truncat]" marker
        assert result.startswith("C" * MAX_RAG_CONTEXT_LENGTH)

    def test_short_text_unchanged(self):
        text = "Short text"
        result = _sanitize_rag_context(text)
        assert result == "Short text"
