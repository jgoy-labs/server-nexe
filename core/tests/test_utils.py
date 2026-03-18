"""
Tests per core/utils.py
"""
import pytest
from core.utils import compute_system_hash


class TestComputeSystemHash:
    def test_empty_string_returns_empty(self):
        result = compute_system_hash("")
        assert result == "empty"

    def test_none_returns_empty(self):
        result = compute_system_hash(None)
        assert result == "empty"

    def test_string_returns_8_char_hex(self):
        result = compute_system_hash("hello world")
        assert len(result) == 8
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_input_deterministic(self):
        input_text = "System prompt for Nexe"
        result1 = compute_system_hash(input_text)
        result2 = compute_system_hash(input_text)
        assert result1 == result2

    def test_different_inputs_different_hashes(self):
        result1 = compute_system_hash("prompt A")
        result2 = compute_system_hash("prompt B")
        assert result1 != result2

    def test_whitespace_normalization(self):
        """Strips leading/trailing whitespace → mateix hash"""
        result1 = compute_system_hash("hello")
        result2 = compute_system_hash("  hello  ")
        assert result1 == result2

    def test_long_string(self):
        long_text = "x" * 10000
        result = compute_system_hash(long_text)
        assert len(result) == 8
