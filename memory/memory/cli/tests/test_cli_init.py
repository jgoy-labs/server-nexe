"""
Tests for memory/memory/cli/__init__.py.
"""

import pytest


class TestCLIInit:
    """Test the CLI __init__ module."""

    def test_import_module(self):
        """Test that the cli module can be imported."""
        import memory.memory.cli as cli_mod
        assert cli_mod is not None

    def test_rag_main_exported(self):
        """Test that rag_main is exported."""
        from memory.memory.cli import rag_main
        assert callable(rag_main)

    def test_all_contains_rag_main(self):
        """Test __all__ contains rag_main."""
        from memory.memory.cli import __all__
        assert "rag_main" in __all__
