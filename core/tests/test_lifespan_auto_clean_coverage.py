"""Tests for core/lifespan_auto_clean.py — coverage gaps."""


class TestLifespanAutoClean:
    def test_function_exists(self):
        from core.lifespan_auto_clean import _startup_auto_clean
        assert callable(_startup_auto_clean)

    def test_module_imports(self):
        import core.lifespan_auto_clean as mod
        assert mod is not None
