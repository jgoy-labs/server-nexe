"""
Tests for personality/loading/module_extractor.py
Covers uncovered lines: 50-70, 75-94, 98-108, 112-125, 129-156
"""
import inspect
import types
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from personality.loading.module_extractor import ModuleExtractor


def _make_module_info(name="test_module"):
    """Create a minimal ModuleInfo-like object."""
    from personality.data.models import ModuleInfo
    return ModuleInfo(
        name=name,
        path=Path("/tmp/test_module"),
        manifest_path=Path("/tmp/test_module/manifest.toml"),
        manifest={},
    )


class TestExtractModuleInstance:
    """Tests for extract_module_instance (lines 50-70)"""

    def test_returns_factory_result_when_available(self):
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.create_module = lambda: "factory_result"
        info = _make_module_info()
        result = extractor.extract_module_instance(module, "test_module", info)
        assert result == "factory_result"

    def test_returns_module_name_attribute(self):
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.test_module = "named_attr"
        info = _make_module_info()
        result = extractor.extract_module_instance(module, "test_module", info)
        assert result == "named_attr"

    def test_returns_common_attribute(self):
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.app = "the_app"
        info = _make_module_info()
        result = extractor.extract_module_instance(module, "test_module", info)
        assert result == "the_app"

    def test_returns_main_class_instance(self):
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class MyModule:
            pass

        module.MyModule = MyModule
        info = _make_module_info()
        result = extractor.extract_module_instance(module, "test_module", info)
        assert isinstance(result, MyModule)

    def test_falls_back_to_module_itself(self):
        """Lines 66-70: no factory, no attr, no class -> return module"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        info = _make_module_info()
        result = extractor.extract_module_instance(module, "test_module", info)
        assert result is module


class TestTryFactoryFunctions:
    """Tests for _try_factory_functions (lines 75-94)"""

    def test_factory_with_module_info_param(self):
        """Line 83-84: factory accepts module_info"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        info = _make_module_info()

        def create_module(module_info):
            return f"created_{module_info.name}"

        module.create_module = create_module
        result = extractor._try_factory_functions(module, "test_module", info)
        assert result == "created_test_module"

    def test_factory_without_module_info_param(self):
        """Line 85-86: factory without module_info"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.create_app = lambda: "app_created"
        info = _make_module_info()
        result = extractor._try_factory_functions(module, "test_module", info)
        assert result == "app_created"

    def test_factory_exception_continues(self):
        """Lines 87-92: factory raises exception, tries next"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        def bad_factory():
            raise RuntimeError("factory error")

        module.create_module = bad_factory
        module.create_app = lambda: "fallback_app"
        info = _make_module_info()
        result = extractor._try_factory_functions(module, "test_module", info)
        assert result == "fallback_app"

    def test_no_factory_returns_none(self):
        """Line 94: no factory found"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        info = _make_module_info()
        result = extractor._try_factory_functions(module, "test_module", info)
        assert result is None

    def test_non_callable_factory_skipped(self):
        """hasattr but not callable"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.create_module = "not_callable"
        info = _make_module_info()
        result = extractor._try_factory_functions(module, "test_module", info)
        assert result is None


class TestTryModuleNameAttribute:
    """Tests for _try_module_name_attribute (lines 98-108)"""

    def test_attribute_is_value(self):
        """Lines 98-106: attribute exists and is a value"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.my_mod = "some_value"
        result = extractor._try_module_name_attribute(module, "my_mod")
        assert result == "some_value"

    def test_attribute_is_class(self):
        """Lines 101-103: attribute is a class, instantiate it"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class MyMod:
            pass

        module.my_mod = MyMod
        result = extractor._try_module_name_attribute(module, "my_mod")
        assert isinstance(result, MyMod)

    def test_class_instantiation_fails_returns_class(self):
        """Lines 104-106: class raises TypeError on init, return class itself"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class MyMod:
            def __init__(self, required_arg):
                pass

        module.my_mod = MyMod
        result = extractor._try_module_name_attribute(module, "my_mod")
        assert result is MyMod

    def test_attribute_is_none_returns_none(self):
        """Line 100: attribute exists but is None"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.my_mod = None
        result = extractor._try_module_name_attribute(module, "my_mod")
        assert result is None

    def test_no_attribute_returns_none(self):
        """Line 108: attribute not found"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        result = extractor._try_module_name_attribute(module, "nonexistent")
        assert result is None


class TestTryCommonAttributes:
    """Tests for _try_common_attributes (lines 112-125)"""

    def test_finds_common_attribute(self):
        """Lines 112-123: finds 'app' attribute"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.router = "the_router"
        result = extractor._try_common_attributes(module)
        assert result == "the_router"

    def test_common_attribute_is_class(self):
        """Lines 118-120: common attr is a class"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class Router:
            pass

        module.router = Router
        result = extractor._try_common_attributes(module)
        assert isinstance(result, Router)

    def test_common_class_fails_continues(self):
        """Lines 121-122: class instantiation fails, continue to next"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class BadRouter:
            def __init__(self, x):
                pass

        module.app = BadRouter
        module.router = "good_router"
        result = extractor._try_common_attributes(module)
        assert result == "good_router"

    def test_none_attributes_skipped(self):
        """Line 117: attr is None, skip"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        module.app = None
        module.router = None
        result = extractor._try_common_attributes(module)
        assert result is None

    def test_no_common_attributes_returns_none(self):
        """Line 125: no common attributes"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        result = extractor._try_common_attributes(module)
        assert result is None


class TestTryMainClass:
    """Tests for _try_main_class (lines 129-156)"""

    def test_finds_class_with_priority_keyword(self):
        """Lines 143-149: finds class matching priority keyword"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class MyModuleClass:
            pass

        class OtherClass:
            pass

        module.MyModuleClass = MyModuleClass
        module.OtherClass = OtherClass
        result = extractor._try_main_class(module, "test")
        assert isinstance(result, MyModuleClass)

    def test_priority_class_fails_tries_next(self):
        """Lines 148-149: priority class can't instantiate, try next"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class MyModuleClass:
            def __init__(self, required):
                pass

        class ServiceClass:
            pass

        module.MyModuleClass = MyModuleClass
        module.ServiceClass = ServiceClass
        result = extractor._try_main_class(module, "test")
        assert isinstance(result, ServiceClass)

    def test_no_priority_match_uses_first_class(self):
        """Lines 151-152: no priority keyword match, use first class"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class PlainClass:
            pass

        module.PlainClass = PlainClass
        result = extractor._try_main_class(module, "test")
        assert isinstance(result, PlainClass)

    def test_first_class_fails_returns_none(self):
        """Lines 153-156: first class can't instantiate, return None"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class RequiresArgs:
            def __init__(self, x, y, z):
                pass

        module.RequiresArgs = RequiresArgs
        result = extractor._try_main_class(module, "test")
        assert result is None

    def test_no_classes_returns_none(self):
        """Lines 138-139: no classes in module"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")
        result = extractor._try_main_class(module, "test")
        assert result is None

    def test_skips_private_classes(self):
        """Line 131: skip classes starting with _"""
        extractor = ModuleExtractor()
        module = types.ModuleType("fake")

        class _Private:
            pass

        module._Private = _Private
        result = extractor._try_main_class(module, "test")
        assert result is None
