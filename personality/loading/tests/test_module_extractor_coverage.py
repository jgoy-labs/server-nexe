"""Tests for personality/loading/module_extractor.py — coverage gaps."""


class TestModuleExtractor:
    def test_init(self):
        from personality.loading.module_extractor import ModuleExtractor
        ext = ModuleExtractor()
        assert ext is not None

    def test_module_imports(self):
        from personality.loading import module_extractor
        assert hasattr(module_extractor, 'ModuleExtractor')
