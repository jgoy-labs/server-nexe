"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_memory_access.py
Description: D-M — filtered memory view + manager veto (#875).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import ast
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.memory_access import (
    CollectionDenied,
    MemoryView,
    get_memory_view,
    resolve_memory_policy,
)


def _api(**methods):
    api = MagicMock()
    api.collection_exists = AsyncMock(return_value=True)
    api.create_collection = AsyncMock(return_value=True)
    api.delete_collection = AsyncMock(return_value=True)
    api.store = AsyncMock(return_value="doc-1")
    api.search = AsyncMock(return_value=[])
    api.count = AsyncMock(return_value=3)
    api.list_collections = AsyncMock(return_value=[])
    api.embed_query = AsyncMock(return_value=[0.1, 0.2])
    api.close = AsyncMock()
    for name, value in methods.items():
        setattr(api, name, value)
    return api


class _Info:
    def __init__(self, name):
        self.name = name


class TestMemoryViewDeny:
    @pytest.mark.asyncio
    async def test_default_allows_every_collection(self):
        api = _api()
        view = MemoryView(api, plugin_id="web_ui_module")
        await view.search("q", "personal_memory")
        await view.store("t", "user_knowledge")
        api.search.assert_awaited()
        api.store.assert_awaited()

    @pytest.mark.asyncio
    async def test_denied_search_and_store_raise(self):
        api = _api()
        view = MemoryView(api, plugin_id="agenda", denied=frozenset({"personal_memory"}))
        with pytest.raises(CollectionDenied) as exc:
            await view.search("q", "personal_memory")
        assert exc.value.plugin_id == "agenda"
        assert exc.value.collection == "personal_memory"
        api.search.assert_not_called()
        with pytest.raises(CollectionDenied):
            await view.store("secret", "personal_memory")
        api.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_collection_exists_is_false_for_denied(self):
        api = _api()
        view = MemoryView(api, plugin_id="agenda", denied=frozenset({"personal_memory"}))
        assert await view.collection_exists("personal_memory") is False
        api.collection_exists.assert_not_called()
        assert await view.collection_exists("user_knowledge") is True

    @pytest.mark.asyncio
    async def test_list_and_visible_names_drop_denied(self):
        api = _api(list_collections=AsyncMock(return_value=[
            _Info("personal_memory"),
            _Info("user_knowledge"),
            _Info("nexe_documentation"),
        ]))
        view = MemoryView(api, plugin_id="agenda", denied=frozenset({"personal_memory"}))
        listed = await view.list_collections()
        assert [i.name for i in listed] == ["user_knowledge", "nexe_documentation"]
        names = await view.visible_names()
        assert "personal_memory" not in names
        assert "user_knowledge" in names

    @pytest.mark.asyncio
    async def test_visible_names_falls_back_when_list_is_unusable(self):
        api = _api(list_collections=AsyncMock(return_value=MagicMock()))
        view = MemoryView(api, plugin_id="web_ui_module", denied=frozenset({"personal_memory"}))
        names = await view.visible_names()
        assert names == ["nexe_documentation", "user_knowledge"]

    def test_filter_requested_drops_denied(self):
        view = MemoryView(_api(), plugin_id="x", denied=frozenset({"personal_memory"}))
        assert view.filter_requested(["personal_memory", "user_knowledge"]) == ["user_knowledge"]

    def test_close_is_not_forwarded(self):
        api = _api()
        view = MemoryView(api, plugin_id="web_ui_module")
        assert not hasattr(view, "close") or inspect.getattr_static(type(view), "close", None) is None
        with pytest.raises(AttributeError):
            view.close  # noqa: B018 — must not exist on the view (B1)

    def test_is_not_the_raw_api(self):
        api = _api()
        view = MemoryView(api, plugin_id="web_ui_module")
        assert view is not api
        assert view._api is api


class TestPolicy:
    def test_manager_deny_unions_with_manifest_and_wins(self):
        with patch(
            "core.memory_access._manifest_deny",
            return_value=frozenset({"user_knowledge"}),
        ), patch(
            "core.memory_access._manager_deny",
            return_value=frozenset({"personal_memory"}),
        ):
            denied = resolve_memory_policy("agenda")
        assert denied == frozenset({"user_knowledge", "personal_memory"})

    def test_manager_deny_reads_plugins_memory_access(self):
        with patch(
            "core.memory_access._loaded_config",
            return_value={
                "plugins": {
                    "memory_access": {
                        "agenda": {"deny": ["personal_memory"]},
                    }
                }
            },
        ), patch("core.memory_access._manifest_deny", return_value=frozenset()):
            assert "personal_memory" in resolve_memory_policy("agenda")
            assert resolve_memory_policy("web_ui_module") == frozenset()

    def test_web_ui_manifest_denies_nothing(self):
        # Production web_ui must keep access to the three user collections.
        with patch("core.memory_access._manager_deny", return_value=frozenset()):
            assert resolve_memory_policy("web_ui_module") == frozenset()


class TestGetMemoryView:
    @pytest.mark.asyncio
    async def test_wraps_the_v1_singleton_and_never_constructs_api(self):
        api = _api()
        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=api)), patch(
            "memory.memory.api.MemoryAPI"
        ) as ctor:
            view = await get_memory_view("web_ui_module")
        ctor.assert_not_called()
        assert isinstance(view, MemoryView)
        assert view._api is api

    @pytest.mark.asyncio
    async def test_extra_deny_is_applied(self):
        api = _api()
        view = await get_memory_view("web_ui_module", api=api, extra_deny=["personal_memory"])
        with pytest.raises(CollectionDenied):
            await view.search("q", "personal_memory")


class TestPluginDoesNotImportMemory:
    def test_web_ui_sources_have_no_memory_import(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "plugins" / "web_ui_module"
        leaked = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "memory" or alias.name.startswith("memory."):
                            leaked.append(f"{path.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == "memory" or node.module.startswith("memory."):
                        leaked.append(f"{path.name}: from {node.module}")
        assert not leaked, leaked
