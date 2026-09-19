"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_fd_block3_rag_unified.py
Description: Gate for F-D block 3 — one RAG retrieval engine for /v1 and
             /ui/chat (core.endpoints.chat_rag.build_rag_context), instead
             of two: per-collection thresholds + dedup (the API's, always
             correct) porting to the UI, and the UI's collection toggle +
             RAM-derived limit porting to the API. Drives the real functions,
             not a copy of the expression.
www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints.chat_rag import build_rag_context, system_rag_limit


def _result(text, score, collection):
    r = MagicMock()
    r.text = text
    r.score = score
    r.collection = collection
    r.metadata = {"source": collection}
    return r


class TestCollectionToggle:
    """F-D block 3: the collections param restricts the search — the UI's
    per-turn toggle, ported so /v1 has it too."""

    @pytest.mark.asyncio
    async def test_only_the_requested_collections_are_searched(self):
        searched = []

        async def _exists(name):
            return True

        async def _search(*, query, collection, top_k, threshold, **kw):
            searched.append(collection)
            return []

        memory = MagicMock()
        memory.collection_exists = AsyncMock(side_effect=_exists)
        memory.search = AsyncMock(side_effect=_search)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            await build_rag_context(
                "hola", app_state=None, server_lang="en",
                collections=["nexe_documentation"],
            )

        assert searched == ["nexe_documentation"], (
            "a toggle restricted to one collection must not search the others"
        )

    @pytest.mark.asyncio
    async def test_empty_toggle_searches_nothing(self):
        """C2 / MC-041-046 (2026-08-31 regression): [] means the user
        disabled every source — must search NONE, not fall through to
        "no restriction". `if collections else` (falsy) treated [] the same
        as None; the correct guard is `is not None`, same policy as the
        sibling functions in memory_helper.py. Privacy bug: personal_memory
        would otherwise answer despite the user turning it off."""
        searched = []

        async def _search(*, query, collection, top_k, threshold, **kw):
            searched.append(collection)
            return []

        memory = MagicMock()
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(side_effect=_search)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            await build_rag_context("hola", app_state=None, server_lang="en", collections=[])

        assert searched == [], (
            f"collections=[] must search NOTHING (user disabled every source), got {searched}"
        )

    @pytest.mark.asyncio
    async def test_no_toggle_searches_everything_discovered(self):
        """None (the default, unchanged from before this parameter existed)
        falls back to discovery — the mutation this guards: hard-coding the
        toggle branch would search nothing when collections=None."""
        from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION

        searched = []

        async def _search(*, query, collection, top_k, threshold, **kw):
            searched.append(collection)
            return []

        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])  # → SYSTEM_COLLECTIONS fallback
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(side_effect=_search)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            await build_rag_context("hola", app_state=None, server_lang="en", collections=None)

        assert set(searched) == {DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION}


class TestRamDerivedLimit:
    """F-D block 3: the RAM-derived limit caps results after dedup — the
    UI's system_rag_limit, ported so /v1 has it too."""

    @pytest.mark.asyncio
    async def test_explicit_limit_caps_results(self):
        results = [_result(f"text{i}", 0.9, "nexe_documentation") for i in range(5)]
        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(return_value=results)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            _context, rag_items = await build_rag_context(
                "hola", app_state=None, server_lang="en", collections=["nexe_documentation"], limit=2,
            )

        assert len(rag_items) == 2, f"limit=2 must cap results, got {len(rag_items)}"

    @pytest.mark.asyncio
    async def test_no_explicit_limit_uses_system_rag_limit(self):
        """Mutation guard: if build_rag_context stopped calling
        system_rag_limit() when limit=None, this goes red."""
        results = [_result(f"text{i}", 0.9, "nexe_documentation") for i in range(10)]
        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(return_value=results)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)), \
             patch("core.endpoints.chat_rag.system_rag_limit", return_value=1) as mock_limit:
            _context, rag_items = await build_rag_context(
                "hola", app_state=None, server_lang="en", collections=["nexe_documentation"],
            )

        mock_limit.assert_called_once()
        assert len(rag_items) == 1


class TestThresholdOverride:
    """F-D block 3: the UI's per-turn rag_threshold slider (and the CLI's
    --rag-threshold) applies the SAME threshold to every collection —
    ported so /v1 has it too, without losing the 3 tuned defaults when
    it's not set."""

    @pytest.mark.asyncio
    async def test_override_applies_to_every_collection_search(self):
        from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION

        thresholds_used = []

        async def _search(*, query, collection, top_k, threshold, **kw):
            thresholds_used.append((collection, threshold))
            return []

        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(side_effect=_search)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            await build_rag_context(
                "hola", app_state=None, server_lang="en", threshold_override=0.6,
            )

        got = dict(thresholds_used)
        assert got[DOCS_COLLECTION] == 0.6
        assert got[KNOWLEDGE_COLLECTION] == 0.6
        assert got[MEMORY_COLLECTION] == 0.6

    @pytest.mark.asyncio
    async def test_no_override_keeps_the_3_tuned_thresholds(self):
        from core.endpoints.chat_rag import RAG_DOCS_THRESHOLD, RAG_KNOWLEDGE_THRESHOLD, RAG_MEMORY_THRESHOLD
        from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION

        thresholds_used = []

        async def _search(*, query, collection, top_k, threshold, **kw):
            thresholds_used.append((collection, threshold))
            return []

        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(side_effect=_search)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            await build_rag_context("hola", app_state=None, server_lang="en")

        got = dict(thresholds_used)
        assert got[DOCS_COLLECTION] == RAG_DOCS_THRESHOLD
        assert got[KNOWLEDGE_COLLECTION] == RAG_KNOWLEDGE_THRESHOLD
        assert got[MEMORY_COLLECTION] == RAG_MEMORY_THRESHOLD


class TestRagItemsReturned:
    @pytest.mark.asyncio
    async def test_rag_items_carries_collection_and_score(self):
        results = [_result("text", 0.77, "user_knowledge")]
        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(return_value=results)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            context, rag_items = await build_rag_context(
                "hola", app_state=None, server_lang="en", collections=["user_knowledge"],
            )

        assert rag_items == [("user_knowledge", 0.77)]
        assert "text" in context


class TestLabelledSections:
    """C3: the system prompt (server.toml, ca/es/en) tells the model to look
    for section markers ([DOCUMENTACIO DEL SISTEMA] etc.) — _format_results
    must actually emit them, grouped by collection, not just a flat
    [Font: x] per result with no section the prompt refers to."""

    @pytest.mark.asyncio
    async def test_sections_labelled_per_collection_ca(self):
        results = [
            _result("doc text", 0.9, "nexe_documentation"),
            _result("mem text", 0.9, "personal_memory"),
        ]
        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(return_value=results)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            context, _rag_items = await build_rag_context(
                "hola", app_state=None, server_lang="ca",
                collections=["nexe_documentation", "personal_memory"],
            )

        assert "[DOCUMENTACIO DEL SISTEMA]" in context
        assert "[MEMORIA DE L'USUARI]" in context
        assert "[Font: nexe_documentation]" in context
        assert "[Font: personal_memory]" in context
        # No section header for a collection with no results this turn.
        assert "[DOCUMENTACIO TECNICA]" not in context

    @pytest.mark.asyncio
    async def test_sections_labelled_per_collection_en(self):
        results = [_result("k text", 0.9, "user_knowledge")]
        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(return_value=results)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            context, _rag_items = await build_rag_context(
                "hola", app_state=None, server_lang="en", collections=["user_knowledge"],
            )

        assert "[TECHNICAL DOCUMENTATION]" in context
        assert "[SYSTEM DOCUMENTATION]" not in context
        assert "[USER MEMORY]" not in context
        assert "[Font: user_knowledge]" in context

    @pytest.mark.asyncio
    async def test_unrecognized_collection_falls_back_to_knowledge_section(self):
        """A plugin's own collection (#896 discovery, no tuned section of its
        own) lands in the "knowledge" bucket — same treatment _rag_params_for
        already gives it for the threshold."""
        results = [_result("plugin text", 0.9, "some_plugin_collection")]
        memory = MagicMock()
        memory.list_collections = AsyncMock(return_value=[])
        memory.collection_exists = AsyncMock(return_value=True)
        memory.search = AsyncMock(return_value=results)
        memory.embed_query = AsyncMock(return_value=[0.0])

        with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
            context, _rag_items = await build_rag_context(
                "hola", app_state=None, server_lang="en", collections=["some_plugin_collection"],
            )

        assert "[TECHNICAL DOCUMENTATION]" in context
        assert "[Font: some_plugin_collection]" in context


class TestUiRouteDelegatesToCore:
    """F-D block 3: no second threshold/dedup/limit implementation left in the
    plugin. C4.2: retrieval is the turn's `recall` step (`core/turn/recall.py`)
    and the UI door reaches it through its adapter, so these drive the adapter
    — what the door does — instead of a function that has moved twice."""

    @staticmethod
    async def _recall(body: dict, *, attached_doc=None):
        """Run the UI door's real `recall` step and return its context."""
        from unittest.mock import MagicMock as _MM

        from core.turn.context import TurnContext
        from plugins.web_ui_module.api.turn_adapters import ui_adapters

        session = _MM()
        session.has_attached_document.return_value = attached_doc is not None
        ctx = TurnContext(
            turn_id="t", entry="ui", message=body.get("message", "hola"),
            lang="en", body=body, app_state=None, session=session,
        )
        # C4.3: `recall` takes the document from the context, where the
        # `session` step writes it (declared in `steps.py`: session writes
        # `attachments`, recall reads them). Driving one step by hand means
        # standing in for the step before it.
        if attached_doc is not None:
            ctx.attachments["document"] = attached_doc
        await ui_adapters(_MM(), streaming=False)["recall"](ctx)
        return ctx.recall_text, ctx.usage.get("ui", {}).get("rag_count", 0), ctx.recall

    @pytest.mark.asyncio
    async def test_attached_doc_narrows_the_collections_instead_of_skipping(self):
        """#1064: it used to short-circuit, and that took personal memory with it.

        One retrieval covers three collections, so skipping the step because a
        document is attached also silenced every fact the user had asked the
        assistant to remember. The document's own collection is still not
        searched — the document IS that context for the turn — but the other
        two are.
        """
        from core.memory_access import (
            DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION,
        )

        with patch(
            "core.endpoints.chat_rag.build_rag_context",
            new=AsyncMock(return_value=("text", [])),
        ) as mock_core:
            await self._recall({"message": "hola"}, attached_doc={"filename": "x"})

        mock_core.assert_called_once()
        asked = mock_core.call_args.kwargs["collections"]
        assert KNOWLEDGE_COLLECTION not in asked, asked
        assert MEMORY_COLLECTION in asked and DOCS_COLLECTION in asked, asked

    @pytest.mark.asyncio
    async def test_delegates_to_core_with_the_toggle(self):
        with patch(
            "core.endpoints.chat_rag.build_rag_context",
            new=AsyncMock(return_value=("[Font: x]\ntext", [("nexe_documentation", 0.9)])),
        ) as mock_core:
            rag_context, rag_count, rag_items = await self._recall(
                {"message": "hola", "rag_collections": ["nexe_documentation"]}
            )

        mock_core.assert_called_once()
        _args, kwargs = mock_core.call_args
        assert kwargs.get("collections") == ["nexe_documentation"], (
            "the UI's rag_collections toggle must reach the shared core function"
        )
        assert rag_count == 1
        assert rag_items == [("nexe_documentation", 0.9)]
        assert "text" in rag_context

    @pytest.mark.asyncio
    async def test_rag_threshold_reaches_the_shared_core_function(self):
        """C1 regression: the UI's rag_threshold slider must actually reach
        build_rag_context as threshold_override, not be silently dropped —
        the old `_build_rag_context` read body["rag_threshold"] into a local
        variable and never passed it on."""
        with patch(
            "core.endpoints.chat_rag.build_rag_context",
            new=AsyncMock(return_value=("[Font: x]\ntext", [("nexe_documentation", 0.9)])),
        ) as mock_core:
            await self._recall({"message": "hola", "rag_threshold": 0.9})

        _args, kwargs = mock_core.call_args
        assert kwargs.get("threshold_override") == 0.9, (
            "a custom rag_threshold from the UI slider must reach the shared "
            "RAG engine — not be read into a local variable and dropped"
        )

    @pytest.mark.asyncio
    async def test_no_rag_threshold_passes_none_override(self):
        """No rag_threshold in the body must keep the 3 tuned per-collection
        thresholds (None override), not accidentally pass 0 or ''."""
        with patch(
            "core.endpoints.chat_rag.build_rag_context",
            new=AsyncMock(return_value=("", [])),
        ) as mock_core:
            await self._recall({"message": "hola"})

        _args, kwargs = mock_core.call_args
        assert kwargs.get("threshold_override") is None

    @pytest.mark.asyncio
    async def test_core_failure_degrades_to_no_context_not_a_crash(self):
        with patch("core.endpoints.chat_rag.build_rag_context",
                   new=AsyncMock(side_effect=RuntimeError("down"))):
            out = await self._recall({"message": "hola"})

        assert out == ("", 0, [])
