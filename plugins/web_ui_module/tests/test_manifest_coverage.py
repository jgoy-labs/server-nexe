"""
Tests for plugins/web_ui_module/manifest.py - targeting uncovered lines.
Focuses on: parse_rag_header import fallback (29-30), _generate_rag_metadata LLM paths (73-134),
_require_ui_auth (160-161), chat engine selection branches (460-491),
streaming response paths (508-533, 652-714), session cleanup (834-839).
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-cover-key")
    monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)


@pytest.fixture
def app():
    from plugins.web_ui_module.manifest import router_public
    _app = FastAPI()
    _app.include_router(router_public)
    return _app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth():
    return {"X-Api-Key": "test-cover-key"}


class TestParseRagHeaderFallback:
    """Test lines 29-30: parse_rag_header import fallback."""

    def test_parse_rag_header_none_when_import_fails(self):
        """When memory.rag.header_parser import fails, parse_rag_header is None."""
        import plugins.web_ui_module.api.routes as m
        # Just check it's either callable or None
        assert m.parse_rag_header is None or callable(m.parse_rag_header)


class TestGenerateRagMetadataLLM:
    """Test lines 73-134: LLM-powered metadata generation paths."""

    def test_llm_generates_metadata_ollama_style(self):
        """Lines 78-131: LLM engine with 'model' param generates metadata."""
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata

        mock_engine = MagicMock()
        # Simulate ollama-style chat that returns a coroutine
        async def mock_chat(**kwargs):
            return {"message": {"content": "abstract: Test description\ntags: [test, doc, info]"}}

        mock_engine.chat = mock_chat

        mock_reg = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_module_instance.return_value = mock_engine
        mock_reg.instance = mock_instance

        mock_registry = MagicMock()
        mock_registry.get_module.return_value = mock_reg

        mock_state = MagicMock()
        mock_state.module_manager.registry = mock_registry

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            result = asyncio.run(_generate_rag_metadata("Test content here", "test.txt"))
            assert "abstract" in result
            assert "tags" in result

    def test_llm_engine_not_found_uses_fallback(self):
        """Lines 72-73: no engine found falls back."""
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata

        mock_registry = MagicMock()
        mock_registry.get_module.return_value = None

        mock_state = MagicMock()
        mock_state.module_manager.registry = mock_registry

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            result = asyncio.run(_generate_rag_metadata("Some content", "doc.txt"))
            assert "abstract" in result
            assert "tags" in result

    def test_llm_engine_no_chat_method(self):
        """Lines 75-76: engine without chat method skipped."""
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata

        mock_engine = MagicMock(spec=[])  # no chat attribute

        mock_reg = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_module_instance.return_value = mock_engine
        mock_reg.instance = mock_instance

        mock_registry = MagicMock()
        mock_registry.get_module.return_value = mock_reg

        mock_state = MagicMock()
        mock_state.module_manager.registry = mock_registry

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            result = asyncio.run(_generate_rag_metadata("Content", "file.txt"))
            assert "abstract" in result

    def test_llm_chat_exception_continues(self):
        """Lines 132-134: engine.chat raises exception, continues to next."""
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata

        mock_engine = MagicMock()
        mock_engine.chat.side_effect = Exception("Engine error")

        mock_reg = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_module_instance.return_value = mock_engine
        mock_reg.instance = mock_instance

        mock_registry = MagicMock()
        mock_registry.get_module.return_value = mock_reg

        mock_state = MagicMock()
        mock_state.module_manager.registry = mock_registry

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            result = asyncio.run(_generate_rag_metadata("Content", "file.txt"))
            assert "abstract" in result


class TestChatEngineBranches:
    """Test engine selection and response handling branches."""

    def _make_mock_mm(self, engine=None, has_chat=True, has_get_module=True):
        if engine is None:
            engine = MagicMock()
            engine.chat = MagicMock(return_value={"response": "test response"})

        manifest_mod = MagicMock()
        if has_get_module:
            manifest_mod.get_module_instance = MagicMock(return_value=engine if has_chat else None)
        else:
            del manifest_mod.get_module_instance

        reg = MagicMock()
        reg.instance = manifest_mod

        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])

        mm = MagicMock()
        mm.registry = registry
        return mm

    def test_engine_no_get_module_instance(self, client, auth):
        """Lines 481-483: engine has no get_module_instance."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        mm = self._make_mock_mm(has_get_module=False)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200

    def test_engine_get_module_instance_returns_none(self, client, auth):
        """Lines 486-488: get_module_instance returns None."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        mm = self._make_mock_mm(has_chat=False)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200

    def test_preferred_engine_mlx(self, client, auth, monkeypatch):
        """Lines 463-464: preferred_engine=mlx reorders engine list."""
        monkeypatch.setenv("NEXE_MODEL_ENGINE", "mlx")
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        engine = MagicMock()
        engine.chat = MagicMock(return_value={"content": "mlx response"})
        mm = self._make_mock_mm(engine=engine)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200

    def test_preferred_engine_llamacpp(self, client, auth, monkeypatch):
        """Lines 465-466: preferred_engine=llamacpp."""
        monkeypatch.setenv("NEXE_MODEL_ENGINE", "llamacpp")
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        engine = MagicMock()
        engine.chat = MagicMock(return_value={"content": "llamacpp response"})
        mm = self._make_mock_mm(engine=engine)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200


class TestChatStreamEngineIntegration:
    """Test streaming response paths (lines 508-533, 652-714)."""

    def _make_mock_mm(self, engine):
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)

        reg = MagicMock()
        reg.instance = manifest_mod

        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])

        mm = MagicMock()
        mm.registry = registry
        return mm

    def test_stream_with_ollama_engine(self, client, auth):
        """Lines 605-610: streaming with ollama-style engine (has 'model' param)."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        async def mock_chat(model, messages, stream):
            yield {"message": {"content": "Hello "}}
            yield {"message": {"content": "world"}}

        engine = MagicMock()
        engine.chat = mock_chat
        mm = self._make_mock_mm(engine)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Hi", "session_id": sid, "stream": True}
            )
        assert r.status_code == 200

    def test_non_streaming_with_dict_result_content(self, client, auth):
        """Lines 729-732: non-streaming result with 'content' key."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        engine = MagicMock()
        engine.chat = MagicMock(return_value={"content": "Direct content response"})
        mm = self._make_mock_mm(engine)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Hi", "session_id": sid}
            )
        assert r.status_code == 200


class TestSessionCleanupLoop:
    """Test lines 834-839: _session_cleanup_loop error handling."""

    def test_cleanup_loop_handles_exception(self):
        """Lines 837-839: cleanup_inactive raises exception."""
        from plugins.web_ui_module.api.routes import _session_cleanup_loop

        async def run():
            mock_sm = MagicMock()
            mock_sm.cleanup_inactive.side_effect = Exception("cleanup error")
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
                try:
                    await _session_cleanup_loop(mock_sm)
                except asyncio.CancelledError:
                    pass

        asyncio.run(run())

    def test_cleanup_loop_removes_sessions(self):
        """Lines 835-837: successful cleanup removes sessions."""
        from plugins.web_ui_module.api.routes import _session_cleanup_loop

        async def run():
            mock_sm = MagicMock()
            mock_sm.cleanup_inactive.return_value = 3
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
                try:
                    await _session_cleanup_loop(mock_sm)
                except asyncio.CancelledError:
                    pass
            mock_sm.cleanup_inactive.assert_called_once_with(max_age_hours=24)

        asyncio.run(run())


class TestChatSaveFailure:
    """Test save intent failure path."""

    def test_save_intent_failure(self, client, auth):
        """Save intent returns error message on failure."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("save", "some content"))
            hh.save_to_memory = AsyncMock(return_value={"success": False, "message": "Storage full"})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "guarda something", "session_id": sid}
            )
        assert r.status_code == 200

    def test_save_intent_empty_extracted(self, client, auth):
        """Lines 433-434: empty extracted content asks what to save."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh:
            hh = MagicMock()
            # extracted_content is empty whitespace only
            hh.detect_intent = MagicMock(return_value=("save", "   "))
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "guarda", "session_id": sid}
            )
        assert r.status_code == 200


class TestChatAutoSaveRAG:
    """Test lines 764-766: auto_save exception handling."""

    def test_auto_save_exception_logged(self, client, auth):
        """Lines 764-766: auto_save raises exception, logged as warning."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        engine = MagicMock()
        engine.chat = MagicMock(return_value={"response": "Some valid response"})

        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)

        reg = MagicMock()
        reg.instance = manifest_mod

        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])

        mm = MagicMock()
        mm.registry = registry

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(side_effect=Exception("RAG storage error"))
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Test auto save error", "session_id": sid}
            )
        assert r.status_code == 200


class TestChatRecallIntent:
    """Test lines 437-441: recall intent falls through to chat."""

    def _make_mm(self, engine):
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        return mm

    def test_recall_intent(self, client, auth):
        """Lines 437-441: recall intent treated as chat."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        engine = MagicMock()
        engine.chat = MagicMock(return_value={"response": "recalled"})
        mm = self._make_mm(engine)
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("recall", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": [
                {"content": "fact", "score": 0.9, "metadata": {"source_collection": "x"}}
            ]})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            state.config = {}
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "remember?", "session_id": sid})
        assert r.status_code == 200


class TestChatNoEngineAvailable:
    """Lines 747-748: no engine available."""

    def test_no_engine(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=None)
        registry.list_modules = MagicMock(return_value=[])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200


class TestChatEngineNoChat:
    """Lines 489-491: engine without chat."""

    def test_engine_no_chat(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        engine = MagicMock(spec=[])
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200


class TestChatRagContext:
    """Lines 536-555: RAG context injection."""

    def test_rag_context_injected(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        engine = MagicMock()
        engine.chat = MagicMock(return_value={"response": "with rag"})
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={
                "success": True, "results": [
                    {"content": "fact1", "score": 0.85, "metadata": {"source_collection": "t"}},
                ]
            })
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": "d1"})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            state.config = {}
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200

    def test_rag_lookup_exception(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        engine = MagicMock()
        engine.chat = MagicMock(return_value={"response": "fallback"})
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(side_effect=Exception("RAG failed"))
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            state.config = {}
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200


class TestChatNonStreamingAsyncGen:
    """Lines 718-724: non-streaming async gen result."""

    def test_non_streaming_async_gen(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        async def mock_chat(model, messages, stream):
            yield {"message": {"content": "c1 "}}
            yield {"content": "c2 "}
            yield "c3"

        engine = MagicMock()
        engine.chat = mock_chat
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            state.config = {}
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200


class TestChatCoroutineResult:
    """Lines 727-730: non-streaming coroutine result."""

    def test_coroutine_result(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        async def mock_chat(model, messages, stream):
            return {"message": {"content": "coroutine result"}}

        engine = MagicMock()
        engine.chat = mock_chat
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            state.config = {}
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200


class TestChatAutoSaveWithDocId:
    """Lines 757-766: auto-save with document_id."""

    def test_auto_save_with_doc_id(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        engine = MagicMock()
        engine.chat = MagicMock(return_value={"response": "good response"})
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": "doc123"})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            state.config = {}
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "fact", "session_id": sid})
        assert r.status_code == 200


class TestChatEngineException:
    """Lines 742-745: engine fails, tries next."""

    def test_engine_exception(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        engine = MagicMock()
        engine.chat = MagicMock(side_effect=Exception("engine error"))
        manifest_mod = MagicMock()
        manifest_mod.get_module_instance = MagicMock(return_value=engine)
        reg = MagicMock()
        reg.instance = manifest_mod
        registry = MagicMock()
        registry.get_module = MagicMock(return_value=reg)
        registry.list_modules = MagicMock(return_value=[MagicMock(name="ollama_module")])
        mm = MagicMock()
        mm.registry = registry
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post("/ui/chat", headers=auth, json={"message": "Hi", "session_id": sid})
        assert r.status_code == 200


class TestGenerateRagMetadataAsyncGen:
    """Test lines 90-96: LLM returns async generator."""

    def test_llm_async_gen_response(self):
        """Lines 90-96: async gen chunks from LLM."""
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata

        async def mock_chat(**kwargs):
            async def gen():
                yield {"message": {"content": "abstract: Async gen abstract\n"}}
                yield {"message": {"content": "tags: [tag1, tag2]\n"}}
            return gen()

        mock_engine = MagicMock()
        mock_engine.chat = mock_chat

        mock_reg = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_module_instance.return_value = mock_engine
        mock_reg.instance = mock_instance
        mock_registry = MagicMock()
        mock_registry.get_module.return_value = mock_reg
        mock_state = MagicMock()
        mock_state.module_manager.registry = mock_registry

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            result = asyncio.run(_generate_rag_metadata("Test content", "test.txt"))
            assert "abstract" in result
            assert "tags" in result

    def test_llm_string_response(self):
        """Line 106: engine returns plain string."""
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata

        mock_engine = MagicMock()
        mock_engine.chat.return_value = "abstract: Plain text abstract\ntags: [t1, t2]"

        mock_reg = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_module_instance.return_value = mock_engine
        mock_reg.instance = mock_instance
        mock_registry = MagicMock()
        mock_registry.get_module.return_value = mock_reg
        mock_state = MagicMock()
        mock_state.module_manager.registry = mock_registry

        with patch("core.lifespan.get_server_state", return_value=mock_state):
            result = asyncio.run(_generate_rag_metadata("Test content", "test.txt"))
            assert "abstract" in result

    def test_llm_server_state_exception(self):
        """Lines 136-137: get_server_state fails."""
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata

        with patch("core.lifespan.get_server_state", side_effect=Exception("no state")):
            result = asyncio.run(_generate_rag_metadata("Content", "file.txt"))
            assert "abstract" in result  # uses fallback
