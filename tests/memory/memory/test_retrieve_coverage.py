"""Tests for memory/memory/retrieve/ — __init__, formatter, retriever coverage."""
from unittest.mock import MagicMock


class TestRetrieveInit:
    def test_exports(self):
        from memory.memory.retrieve import Retriever, Formatter, __all__
        assert "Retriever" in __all__
        assert "Formatter" in __all__
        assert Retriever is not None
        assert Formatter is not None


class TestFormatter:
    def test_empty_cards_returns_empty(self):
        from memory.memory.retrieve.formatter import Formatter
        assert Formatter.format_cards([]) == ""

    def test_high_confidence_cards(self):
        from memory.memory.retrieve.formatter import Formatter
        card = MagicMock()
        card.confidence = "high"
        card.content = "User likes cats"
        result = Formatter.format_cards([card])
        assert "HIGH CONFIDENCE" in result
        assert "User likes cats" in result
        assert "MEMORY CONTEXT" in result

    def test_moderate_confidence_cards(self):
        from memory.memory.retrieve.formatter import Formatter
        card = MagicMock()
        card.confidence = "moderate"
        card.content = "Recent topic"
        result = Formatter.format_cards([card])
        assert "MODERATE CONFIDENCE" in result

    def test_low_confidence_cards(self):
        from memory.memory.retrieve.formatter import Formatter
        card = MagicMock()
        card.confidence = "low"
        card.content = "Vague memory"
        result = Formatter.format_cards([card])
        assert "LOW CONFIDENCE" in result

    def test_mixed_confidence(self):
        from memory.memory.retrieve.formatter import Formatter
        cards = []
        for conf in ("high", "moderate", "low"):
            c = MagicMock()
            c.confidence = conf
            c.content = f"{conf} fact"
            cards.append(c)
        result = Formatter.format_cards(cards)
        assert "HIGH CONFIDENCE" in result
        assert "MODERATE CONFIDENCE" in result
        assert "LOW CONFIDENCE" in result
        assert "END MEMORY CONTEXT" in result
