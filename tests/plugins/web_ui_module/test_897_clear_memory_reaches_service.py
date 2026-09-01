"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_897_clear_memory_reaches_service.py
Description: #897 — the wiring half. clear_memory() dropped the Qdrant RAG
            collection and stopped there; the plugin never called
            get_memory_service() once, so everything MemoryService held
            survived while routes_chat told the user «Ja no recordo res sobre
            tu». The plugin may not import memory/ (D-M), so the wipe has to
            travel through the core.memory_access porter.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.memory_access import MemoryView


class _FakeApi:
    """Just enough MemoryAPI for clear_memory's RAG half."""

    def __init__(self):
        self.deleted = []
        self.created = []

    async def collection_exists(self, name):
        return True

    async def delete_collection(self, name):
        self.deleted.append(name)

    async def create_collection(self, name, *a, **k):
        self.created.append(name)


class TestClearMemoryWipesBothStores:
    @pytest.mark.asyncio
    async def test_the_service_stores_are_wiped_too(self, monkeypatch):
        from plugins.web_ui_module.core import memory_helper as mh

        api = _FakeApi()
        wiped = {}

        class _View(MemoryView):
            async def forget_everything(self, user_id: str = "default"):
                wiped["called"] = user_id
                return {"profile": 3, "episodic": 7}

        async def _fake_view(plugin_id, **kwargs):
            return _View(api, plugin_id=plugin_id)

        monkeypatch.setattr(mh, "get_memory_view", _fake_view)

        helper = mh.MemoryHelper() if hasattr(mh, "MemoryHelper") else None
        assert helper is not None, "MemoryHelper must exist for this wiring test"
        monkeypatch.setattr(helper, "get_memory_api", lambda: _coro(api))

        result = await helper.clear_memory(confirm=True)

        assert result["success"] is True
        assert api.deleted == ["personal_memory"], "the RAG half must still happen"
        assert wiped.get("called") == "default", (
            "#897: clearing memory must reach MemoryService, not just Qdrant"
        )

    @pytest.mark.asyncio
    async def test_an_empty_wipe_dict_is_not_success(self, monkeypatch):
        """forget_everything() returns {} when the service is not running.
        That is 'never reached', not 'wiped nothing'. success:True here is
        the original #897 confirmation-vs-delete, now only on this path."""
        from plugins.web_ui_module.core import memory_helper as mh

        api = _FakeApi()

        class _View(MemoryView):
            async def forget_everything(self, user_id: str = "default"):
                return {}

        async def _fake_view(plugin_id, **kwargs):
            return _View(api, plugin_id=plugin_id)

        monkeypatch.setattr(mh, "get_memory_view", _fake_view)
        helper = mh.MemoryHelper()
        monkeypatch.setattr(helper, "get_memory_api", lambda: _coro(api))

        result = await helper.clear_memory(confirm=True)

        assert result["success"] is False, (
            "must not tell the user the facts are gone when MemoryService did not run"
        )
        assert api.deleted == ["personal_memory"], (
            "the RAG half may still have run; the failure is that facts were not reached"
        )

    @pytest.mark.asyncio
    async def test_without_confirmation_nothing_is_touched(self, monkeypatch):
        """The 2-turn confirm gate stays in front of a now-bigger deletion."""
        from plugins.web_ui_module.core import memory_helper as mh

        called = {}

        async def _fake_view(plugin_id, **kwargs):
            called["view"] = True
            raise AssertionError("must not be reached without confirm=True")

        monkeypatch.setattr(mh, "get_memory_view", _fake_view)
        helper = mh.MemoryHelper()
        result = await helper.clear_memory()

        assert result["success"] is False
        assert "view" not in called


async def _coro(value):
    return value
