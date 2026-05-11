"""
Tests for memory/memory/tools/__init__.py.
Mocks the qdrant submodule before import since it may not exist.
"""

import sys
import importlib
import pytest
from unittest.mock import MagicMock


# Mock the qdrant submodule before it gets imported
_qdrant_key = "memory.memory.tools.qdrant"
if _qdrant_key not in sys.modules:
    _mock_qdrant = MagicMock()
    _mock_qdrant.QdrantAdapter = type("QdrantAdapter", (), {})
    _mock_qdrant.QdrantConfig = type("QdrantConfig", (), {})
    sys.modules[_qdrant_key] = _mock_qdrant

# Force reimport of tools to pick up our mock
if "memory.memory.tools" in sys.modules:
    importlib.reload(sys.modules["memory.memory.tools"])


class TestToolsInit:
    """Test the tools __init__ module."""

    def test_import_module(self):
        """Test that the tools module can be imported."""
        import memory.memory.tools as tools_mod
        assert tools_mod is not None

    def test_all_exports(self):
        """Test __all__ contains expected symbols."""
        import memory.memory.tools as tools_mod
        assert "QdrantAdapter" in tools_mod.__all__
        assert "QdrantConfig" in tools_mod.__all__

    def test_qdrant_adapter_available(self):
        """Test QdrantAdapter is importable."""
        from memory.memory.tools import QdrantAdapter
        assert QdrantAdapter is not None

    def test_qdrant_config_available(self):
        """Test QdrantConfig is importable."""
        from memory.memory.tools import QdrantConfig
        assert QdrantConfig is not None
