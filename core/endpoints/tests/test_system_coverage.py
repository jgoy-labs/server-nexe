"""Tests for core/endpoints/system.py — coverage gaps."""


class TestSystemModule:
    def test_get_router(self):
        from core.endpoints.system import get_router
        router = get_router()
        assert router is not None

    def test_module_imports(self):
        from core.endpoints import system
        assert hasattr(system, 'get_router')
        assert hasattr(system, 'get_supervisor_pid')
