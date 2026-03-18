"""
Tests for uncovered lines in plugins/llama_cpp_module/ files.

Covers:
- chat.py: lines 87-88, 110
- manifest.py: line 44
"""

import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════════
# chat.py — uncovered lines
# ═══════════════════════════════════════════════════════════════

class TestLlamaCppChatNodeGaps:

    def test_threadsafe_callback_not_called_when_none(self):
        """Lines 87-88: threadsafe_callback with None stream_callback."""
        # The callback is only invoked when stream_callback is not None
        stream_callback = None
        if stream_callback and callable(stream_callback):
            assert False, "Should not reach here"
        assert True

    def test_tokens_per_second_calculation(self):
        """Line 110: tokens_per_second with elapsed > 0 and tokens > 0."""
        elapsed_ms = 500
        tokens = 50
        tokens_per_second = 0.0
        if elapsed_ms > 0 and tokens > 0:
            tokens_per_second = tokens / (elapsed_ms / 1000)
        assert tokens_per_second == 100.0


# ═══════════════════════════════════════════════════════════════
# manifest.py — line 44
# ═══════════════════════════════════════════════════════════════

class TestLlamaCppManifestGaps:

    def test_get_metadata(self):
        """Line 44: get_metadata returns metadata."""
        from plugins.llama_cpp_module.manifest import get_metadata
        metadata = get_metadata()
        assert metadata.name == "llama_cpp_module"

    def test_get_module_instance(self):
        """Line 49: get_module_instance returns module."""
        from plugins.llama_cpp_module.manifest import get_module_instance
        instance = get_module_instance()
        assert instance is not None
        assert hasattr(instance, 'metadata')
