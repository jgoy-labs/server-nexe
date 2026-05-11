"""
Tests for plugins/llama_cpp_module/ — manifest entry points.

Covers:
- manifest.py: get_metadata, get_module_instance
"""

from plugins.llama_cpp_module.manifest import get_metadata, get_module_instance


class TestLlamaCppManifest:

    def test_get_metadata_returns_correct_name(self):
        metadata = get_metadata()
        assert metadata.name == "llama_cpp_module"

    def test_get_module_instance_has_metadata(self):
        instance = get_module_instance()
        assert instance is not None
        assert hasattr(instance, 'metadata')
