"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_rag_empty_collections_mc041_mc046.py
Description: MC-041 + MC-046 — una llista buida de col·leccions ([] = l'usuari ha
             desactivat TOTES les fonts RAG) NO ha de caure al branch "totes". El
             guard correcte és `is not None` (com les funcions germanes a
             memory_helper.py:715/776), no truthiness. RED abans del fix (cerca a
             les 3 col·leccions); GREEN després (no cerca a cap). `None` segueix
             buscant a totes (cap font especificada).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _reset_memory_helper_globals():
    import asyncio as _a
    import plugins.web_ui_module.core.memory_helper as mh
    mh._memory_api_instance = None
    mh._memory_api_init_failed = False
    mh._memory_api_last_failure_ts = None
    mh._memory_init_lock = _a.Lock()


class TestRecallEmptyCollectionsMC041:
    """recall_from_memory: distingir [] (cap font) de None (totes)."""

    def setup_method(self):
        _reset_memory_helper_globals()

    def teardown_method(self):
        _reset_memory_helper_globals()

    async def _run(self, collections):
        import plugins.web_ui_module.core.memory_helper as mh
        helper = mh.get_memory_helper()
        searched = []

        async def fake_search(memory, query, collection, limit, session_id, query_embedding=None):
            searched.append(collection)
            return []

        with patch.object(helper, "get_memory_api", new=AsyncMock(return_value=MagicMock())), \
                patch.object(helper, "_search_collection_results", new=fake_search):
            result = await helper.recall_from_memory("q", collections=collections)
        return searched, result

    @pytest.mark.asyncio
    async def test_empty_list_searches_nothing(self):
        searched, result = await self._run([])
        assert searched == [], (
            f"collections=[] (totes les fonts desactivades) ha de cercar a CAP, no a {searched}"
        )
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_none_searches_all(self):
        searched, _result = await self._run(None)
        assert set(searched) == {"nexe_documentation", "personal_memory", "user_knowledge"}, (
            f"collections=None ha de cercar a totes 3, no a {searched}"
        )


class TestResolveSearchCollectionsMC046:
    """_resolve_search_collections: [] -> [] (res); None -> les 3 per defecte."""

    def test_empty_list_returns_empty(self):
        from memory.memory.api.v1 import _resolve_search_collections, MemorySearchRequest
        body = MemorySearchRequest(query="q", collections=[])
        assert _resolve_search_collections(body) == []

    def test_none_returns_default_three(self):
        from memory.memory.api.v1 import _resolve_search_collections, MemorySearchRequest
        body = MemorySearchRequest(query="q", collections=None)
        assert _resolve_search_collections(body) == [
            "nexe_documentation",
            "personal_memory",
            "user_knowledge",
        ]

    def test_single_collection_field_still_works(self):
        from memory.memory.api.v1 import _resolve_search_collections, MemorySearchRequest
        body = MemorySearchRequest(query="q", collection="personal_memory")
        assert _resolve_search_collections(body) == ["personal_memory"]
