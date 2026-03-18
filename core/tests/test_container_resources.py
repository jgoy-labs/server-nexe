"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/tests/test_container_resources.py
Description: Tests per core/container.py i core/resources.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from pathlib import Path
from unittest.mock import patch


# ─── Tests Container ──────────────────────────────────────────────────────────

class TestContainer:

    def setup_method(self):
        from core.container import Container
        Container.clear()

    def test_singleton_pattern(self):
        from core.container import Container
        c1 = Container()
        c2 = Container()
        assert c1 is c2

    def test_register_and_get_service(self):
        from core.container import Container
        service = object()
        Container.register("test_svc", service)
        result = Container.get("test_svc")
        assert result is service

    def test_get_nonexistent_returns_default(self):
        from core.container import Container
        result = Container.get("nonexistent")
        assert result is None

    def test_get_nonexistent_with_default(self):
        from core.container import Container
        sentinel = object()
        result = Container.get("nonexistent", default=sentinel)
        assert result is sentinel

    def test_register_factory(self):
        from core.container import Container
        called = []
        def factory():
            called.append(1)
            return {"created": True}
        Container.register_factory("factory_svc", factory)
        result = Container.get("factory_svc")
        assert result == {"created": True}
        assert len(called) == 1

    def test_factory_cached_after_first_call(self):
        from core.container import Container
        call_count = [0]
        def factory():
            call_count[0] += 1
            return "service_instance"
        Container.register_factory("cached_svc", factory)
        Container.get("cached_svc")
        Container.get("cached_svc")
        assert call_count[0] == 1  # Factory only called once

    def test_clear_removes_services(self):
        from core.container import Container
        Container.register("to_clear", "value")
        Container.clear()
        assert Container.get("to_clear") is None

    def test_clear_removes_factories(self):
        from core.container import Container
        Container.register_factory("factory_to_clear", lambda: "value")
        Container.clear()
        assert Container.get("factory_to_clear") is None


class TestGetServiceRegisterService:

    def setup_method(self):
        from core.container import Container
        Container.clear()

    def test_get_service_shortcut(self):
        from core.container import Container, get_service
        Container.register("svc", "value")
        assert get_service("svc") == "value"

    def test_register_service_shortcut(self):
        from core.container import Container, register_service
        register_service("svc2", "val2")
        assert Container.get("svc2") == "val2"


# ─── Tests resources.py ───────────────────────────────────────────────────────

class TestGetResourcePath:

    def test_get_resource_via_file_success(self, tmp_path):
        """Test directe de _get_resource_via_file amb un paquet existent."""
        from core.resources import _get_resource_via_file
        import os
        # core és un paquet vàlid amb __file__
        # Usem un fitxer que existeix
        import core
        core_dir = Path(core.__file__).parent
        # Buscar un fitxer existent dins core/
        existing = next(core_dir.glob("*.py"), None)
        if existing:
            resource = existing.name
            result = _get_resource_via_file("core", resource)
            assert result.exists()

    def test_get_resource_via_file_nonexistent_raises(self):
        from core.resources import _get_resource_via_file
        with pytest.raises(FileNotFoundError):
            _get_resource_via_file("core", "nonexistent_resource_xyz.html")

    def test_get_resource_via_file_bad_package_raises(self):
        from core.resources import _get_resource_via_file
        with pytest.raises(ImportError):
            _get_resource_via_file("nonexistent_package_xyz", "file.txt")

    def test_get_resource_via_repo_root_success(self, tmp_path):
        """Test _get_resource_via_repo_root quan la resource existeix."""
        from core.resources import _get_resource_via_repo_root
        # Buscar un recurs que existeix (personality/server.toml)
        result = _get_resource_via_repo_root("personality", "server.toml")
        assert result.exists()

    def test_get_resource_via_repo_root_nonexistent_raises(self):
        from core.resources import _get_resource_via_repo_root
        with pytest.raises(FileNotFoundError):
            _get_resource_via_repo_root("core", "nonexistent_xyz.html")

    def test_get_resource_path_use_importlib_false(self):
        """use_importlib=False força l'ús de _get_resource_via_file."""
        from core.resources import get_resource_path
        import core
        core_dir = Path(core.__file__).parent
        existing = next(core_dir.glob("*.py"), None)
        if existing:
            result = get_resource_path("core", existing.name, use_importlib=False)
            assert result.exists()

    def test_get_resource_path_fallback_chain(self):
        """Quan importlib falla, usa fallback chain."""
        from core.resources import get_resource_path
        # Intentar accés a un recurs inexistent → hauria de llançar RuntimeError
        with pytest.raises((RuntimeError, FileNotFoundError)):
            get_resource_path("core", "nonexistent_xyz.html")

    def test_get_resource_path_existing_via_importlib(self):
        """Test amb importlib per a un fitxer existent."""
        from core.resources import get_resource_path
        import core
        core_dir = Path(core.__file__).parent
        existing = next(core_dir.glob("*.py"), None)
        if existing:
            # Pot funcionar via importlib o fallback
            result = get_resource_path("core", existing.name)
            assert result.exists()
