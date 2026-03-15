"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: tests/test_container.py
Description: Tests per core/container.py.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def clear_container():
    """Clear container state between tests."""
    from core.container import Container
    Container.clear()
    yield
    Container.clear()


class TestContainerSingleton:

    def test_is_singleton(self):
        from core.container import Container
        c1 = Container()
        c2 = Container()
        assert c1 is c2


class TestContainerRegister:

    def test_register_and_get(self):
        from core.container import Container
        service = MagicMock()
        Container.register("my_service", service)
        assert Container.get("my_service") is service

    def test_get_default_when_not_found(self):
        from core.container import Container
        result = Container.get("nonexistent", default="fallback")
        assert result == "fallback"

    def test_get_none_when_not_found_no_default(self):
        from core.container import Container
        result = Container.get("nonexistent")
        assert result is None

    def test_register_factory(self):
        from core.container import Container
        service = MagicMock()
        Container.register_factory("lazy_service", lambda: service)
        result = Container.get("lazy_service")
        assert result is service

    def test_factory_result_cached(self):
        from core.container import Container
        call_count = [0]

        def factory():
            call_count[0] += 1
            return MagicMock()

        Container.register_factory("cached_svc", factory)
        r1 = Container.get("cached_svc")
        r2 = Container.get("cached_svc")
        assert r1 is r2
        assert call_count[0] == 1

    def test_clear_removes_all(self):
        from core.container import Container
        Container.register("svc1", MagicMock())
        Container.register_factory("svc2", MagicMock())
        Container.clear()
        assert Container.get("svc1") is None
        assert Container.get("svc2") is None


class TestShortcutFunctions:

    def test_get_service(self):
        from core.container import Container, get_service
        service = MagicMock()
        Container.register("test_svc", service)
        assert get_service("test_svc") is service

    def test_register_service(self):
        from core.container import Container, register_service
        service = MagicMock()
        register_service("test_svc2", service)
        assert Container.get("test_svc2") is service

    def test_get_service_default(self):
        from core.container import get_service
        result = get_service("nope", default=42)
        assert result == 42
