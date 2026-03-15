"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/tests/test_dependencies_registry.py
Description: Tests per core/dependencies.py i core/module_registry.py.

www.jgoy.net
────────────────────────────────────
"""

import pytest


# ─── Tests dependencies.py ────────────────────────────────────────────────────

class TestDependencies:

    def test_limiter_is_importable(self):
        from core.dependencies import limiter
        assert limiter is not None

    def test_limiter_global_available(self):
        from core.dependencies import limiter_global
        assert limiter_global is not None

    def test_advanced_rate_limiting_flag(self):
        from core.dependencies import ADVANCED_RATE_LIMITING
        assert isinstance(ADVANCED_RATE_LIMITING, bool)

    def test_all_exports_present(self):
        import core.dependencies as dep
        for name in dep.__all__:
            assert hasattr(dep, name), f"Missing export: {name}"

    def test_limiter_same_as_limiter_global(self):
        from core.dependencies import limiter, limiter_global
        assert limiter is limiter_global


# ─── Tests module_registry.py ─────────────────────────────────────────────────

class TestModuleRecord:

    def test_creation(self):
        from core.module_registry import ModuleRecord
        rec = ModuleRecord(name="test", instance=object())
        assert rec.name == "test"
        assert rec.module_id is None
        assert rec.capabilities == []
        assert rec.priority == 0

    def test_creation_with_all_fields(self):
        from core.module_registry import ModuleRecord
        instance = object()
        rec = ModuleRecord(
            name="svc",
            instance=instance,
            module_id="svc-001",
            capabilities=["chat", "stream"],
            priority=10
        )
        assert rec.name == "svc"
        assert rec.module_id == "svc-001"
        assert rec.capabilities == ["chat", "stream"]
        assert rec.priority == 10


class TestModuleRegistry:

    def setup_method(self):
        from core.module_registry import ModuleRegistry
        self.registry = ModuleRegistry()

    def test_empty_list(self):
        assert self.registry.list() == []

    def test_register_and_get(self):
        instance = object()
        self.registry.register("my_module", instance)
        record = self.registry.get("my_module")
        assert record is not None
        assert record.instance is instance
        assert record.name == "my_module"

    def test_get_nonexistent_returns_none(self):
        assert self.registry.get("nonexistent") is None

    def test_register_with_capabilities(self):
        self.registry.register("engine", object(), capabilities=["chat", "stream"])
        record = self.registry.get("engine")
        assert "chat" in record.capabilities
        assert "stream" in record.capabilities

    def test_register_with_module_id(self):
        self.registry.register("svc", object(), module_id="svc-001")
        assert self.registry.get("svc").module_id == "svc-001"

    def test_register_with_priority(self):
        self.registry.register("svc", object(), priority=5)
        assert self.registry.get("svc").priority == 5

    def test_list_returns_all_modules(self):
        self.registry.register("a", object())
        self.registry.register("b", object())
        assert len(self.registry.list()) == 2

    def test_find_by_capability_empty(self):
        self.registry.register("svc", object(), capabilities=["other"])
        result = self.registry.find_by_capability("missing")
        assert result == []

    def test_find_by_capability_returns_matches(self):
        self.registry.register("svc1", object(), capabilities=["chat"])
        self.registry.register("svc2", object(), capabilities=["stream"])
        self.registry.register("svc3", object(), capabilities=["chat", "stream"])
        result = self.registry.find_by_capability("chat")
        names = [r.name for r in result]
        assert "svc1" in names
        assert "svc3" in names
        assert "svc2" not in names

    def test_find_by_capability_sorted_by_priority(self):
        self.registry.register("low", object(), capabilities=["chat"], priority=1)
        self.registry.register("high", object(), capabilities=["chat"], priority=10)
        self.registry.register("mid", object(), capabilities=["chat"], priority=5)
        result = self.registry.find_by_capability("chat")
        priorities = [r.priority for r in result]
        assert priorities == sorted(priorities, reverse=True)

    def test_overwrite_registration(self):
        obj1 = object()
        obj2 = object()
        self.registry.register("svc", obj1)
        self.registry.register("svc", obj2)
        assert self.registry.get("svc").instance is obj2

    def test_register_without_capabilities_defaults_empty(self):
        self.registry.register("svc", object(), capabilities=None)
        assert self.registry.get("svc").capabilities == []
