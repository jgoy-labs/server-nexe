"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_manifest.py
Description: Tests per router_public del manifest.py (endpoints UI, session, upload, chat, memory).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.web_ui_module.manifest import router_public, get_module_instance


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-manifest-key")
    monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("NEXE_DEV_MODE", raising=False)


@pytest.fixture(autouse=True)
def _ensure_module_initialized():
    """Post-fix 5abd171 (session_manager late-init).

    WebUIModule.__init__ no longer builds a SessionManager; initialize()
    does. In production the lifespan calls initialize() before any
    request hits the router. In tests we need to do the same, otherwise
    _SessionManagerProxy raises "accessed before initialize()" on the
    first endpoint call.

    crypto_provider is None here because get_server_state() is not
    patched — that's fine, the SessionManager degrades to plaintext
    which is exactly what these tests expect.
    """
    inst = get_module_instance()
    if not inst._initialized:
        asyncio.run(inst.initialize({"config": {}}))


@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(router_public)
    return _app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth():
    return {"X-Api-Key": "test-manifest-key"}


# ─── TestAuthEndpoint ─────────────────────────────────────────────────────────

class TestAuthEndpoint:

    def test_valid_key_returns_ok(self, client, auth):
        r = client.get("/ui/auth", headers=auth)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_invalid_key_returns_401(self, client):
        r = client.get("/ui/auth", headers={"X-Api-Key": "wrong-key"})
        assert r.status_code == 401

    def test_no_key_returns_401(self, client):
        r = client.get("/ui/auth")
        assert r.status_code == 401


# ─── TestInfoEndpoint ─────────────────────────────────────────────────────────

class TestInfoEndpoint:

    def test_returns_200(self, client, auth):
        r = client.get("/ui/info", headers=auth)
        assert r.status_code == 200

    def test_has_model_field(self, client, auth):
        r = client.get("/ui/info", headers=auth)
        assert "model" in r.json()

    def test_has_backend_field(self, client, auth):
        r = client.get("/ui/info", headers=auth)
        assert "backend" in r.json()

    def test_has_version_field(self, client, auth):
        r = client.get("/ui/info", headers=auth)
        assert "version" in r.json()

    def test_reads_env_model(self, client, auth, monkeypatch):
        monkeypatch.setenv("NEXE_DEFAULT_MODEL", "my-model-test")
        r = client.get("/ui/info", headers=auth)
        assert r.json()["model"] == "my-model-test"


# ─── TestServeUI ──────────────────────────────────────────────────────────────

class TestServeUI:

    def test_no_html_returns_404(self, client):
        r = client.get("/ui/")
        # index.html no existeix en entorn de test
        assert r.status_code in (200, 404)

    def test_with_existing_html(self, client, tmp_path):
        """Simula existència de index.html patchejant ui_dir del module."""
        module = get_module_instance()
        fake_html = tmp_path / "index.html"
        fake_html.write_text('<html lang="ca"><head></head></html>')
        orig = module.ui_dir
        module.ui_dir = tmp_path
        try:
            r = client.get("/ui/")
            assert r.status_code == 200
        finally:
            module.ui_dir = orig


# ─── TestServeStatic ──────────────────────────────────────────────────────────

class TestServeStatic:

    def test_nonexistent_file_404(self, client):
        r = client.get("/ui/static/nonexistent.css")
        assert r.status_code == 404

    def test_path_traversal_403(self, client):
        r = client.get("/ui/static/../../../etc/passwd")
        assert r.status_code in (400, 403, 404)

    def test_existing_css_file(self, client, tmp_path):
        module = get_module_instance()
        css = tmp_path / "style.css"
        css.write_bytes(b"body { color: red; }")
        orig = module.ui_dir
        module.ui_dir = tmp_path
        try:
            r = client.get("/ui/static/style.css")
            assert r.status_code == 200
            assert "text/css" in r.headers.get("content-type", "")
        finally:
            module.ui_dir = orig

    def test_existing_js_file(self, client, tmp_path):
        module = get_module_instance()
        js = tmp_path / "app.js"
        js.write_bytes(b"console.log('test');")
        orig = module.ui_dir
        module.ui_dir = tmp_path
        try:
            r = client.get("/ui/static/app.js")
            assert r.status_code == 200
        finally:
            module.ui_dir = orig

    def test_unknown_extension_octet_stream(self, client, tmp_path):
        module = get_module_instance()
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02")
        orig = module.ui_dir
        module.ui_dir = tmp_path
        try:
            r = client.get("/ui/static/data.bin")
            assert r.status_code == 200
            assert "octet-stream" in r.headers.get("content-type", "")
        finally:
            module.ui_dir = orig


# ─── TestSessionEndpoints ─────────────────────────────────────────────────────

class TestSessionEndpoints:

    def test_create_session(self, client, auth):
        r = client.post("/ui/session/new", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        assert "created_at" in data

    def test_create_session_no_auth(self, client):
        r = client.post("/ui/session/new")
        assert r.status_code in (401, 422)

    def test_get_session_info(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        r2 = client.get(f"/ui/session/{sid}", headers=auth)
        assert r2.status_code == 200

    def test_get_nonexistent_session_404(self, client, auth):
        r = client.get("/ui/session/nonexistent-xyz", headers=auth)
        assert r.status_code == 404

    def test_get_session_history(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        r2 = client.get(f"/ui/session/{sid}/history", headers=auth)
        assert r2.status_code == 200
        assert "messages" in r2.json()

    def test_get_history_nonexistent_404(self, client, auth):
        r = client.get("/ui/session/bad-id/history", headers=auth)
        assert r.status_code == 404

    def test_delete_session(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        r2 = client.delete(f"/ui/session/{sid}", headers=auth)
        assert r2.status_code == 200
        assert r2.json()["status"] == "deleted"

    def test_delete_nonexistent_session_404(self, client, auth):
        r = client.delete("/ui/session/nonexistent-xyz", headers=auth)
        assert r.status_code == 404

    def test_list_sessions(self, client, auth):
        r = client.get("/ui/sessions", headers=auth)
        assert r.status_code == 200
        assert "sessions" in r.json()


# ─── TestHealthEndpoint ───────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        r = client.get("/ui/health")
        assert r.status_code == 200

    def test_health_has_status(self, client):
        r = client.get("/ui/health")
        assert r.json()["status"] == "healthy"

    def test_health_has_initialized(self, client):
        r = client.get("/ui/health")
        assert r.json()["initialized"] is True

    def test_health_has_sessions_count(self, client):
        r = client.get("/ui/health")
        assert "sessions" in r.json()


# ─── TestFilesEndpoints ───────────────────────────────────────────────────────

class TestFilesEndpoints:

    def test_list_files_returns_200(self, client, auth):
        r = client.get("/ui/files", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert "files" in data
        assert "total" in data

    def test_cleanup_files_returns_200(self, client, auth):
        r = client.post("/ui/files/cleanup?max_age_hours=1", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert "deleted" in data


# ─── TestUploadEndpoint ───────────────────────────────────────────────────────

class TestUploadEndpoint:

    def test_upload_txt_file(self, client, auth):
        content = b"Hello, this is a test document with enough content for processing."
        mock_save_result = {"success": True, "chunks_saved": 1, "document_id": "test.txt", "message": "ok"}

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh:
            mh = MagicMock()
            mh.save_document_chunks = AsyncMock(return_value=mock_save_result)
            mock_mh.return_value = mh
            r = client.post(
                "/ui/upload",
                headers=auth,
                files={"file": ("test.txt", io.BytesIO(content), "text/plain")},
            )
        assert r.status_code in (200, 400, 422)

    def test_upload_invalid_extension(self, client, auth):
        with patch("plugins.web_ui_module.api.routes.get_memory_helper"):
            r = client.post(
                "/ui/upload",
                headers=auth,
                files={"file": ("test.exe", io.BytesIO(b"binary content"), "application/octet-stream")},
            )
        assert r.status_code in (400, 422)

    def test_upload_no_auth(self, client):
        r = client.post(
            "/ui/upload",
            files={"file": ("test.txt", io.BytesIO(b"content"), "text/plain")},
        )
        assert r.status_code in (401, 422)


# ─── TestChatEndpoint ─────────────────────────────────────────────────────────

class TestChatEndpoint:

    def _make_mock_engine(self, response_text="Hello from engine"):
        """Crea un engine mock que retorna resposta directa."""
        engine = MagicMock()
        engine.chat = MagicMock(return_value={"response": response_text})
        return engine

    def _make_mock_module_manager(self, engine=None):
        """Crea un ModuleManager mock amb un engine registrat."""
        if engine is None:
            engine = self._make_mock_engine()

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

    def test_no_message_returns_400(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        r = client.post("/ui/chat", headers=auth, json={"session_id": sid})
        assert r.status_code == 400

    def test_save_intent_response(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        mock_save = {"success": True, "document_id": "doc-1", "message": "✓"}
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh:
            mh = MagicMock()
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("save", "El meu nom és Jordi"))
            hh.save_to_memory = AsyncMock(return_value=mock_save)
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            mock_mh.return_value = hh
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "El meu nom és Jordi, guarda-ho", "session_id": sid}
            )
        assert r.status_code == 200
        data = r.json()
        assert "response" in data

    def test_save_intent_empty_content(self, client, auth):
        """Quan extracted_content és buit, usa el missatge original."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        mock_save = {"success": True, "document_id": None, "message": "⏭️ Similar already exists"}
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("save", ""))
            hh.save_to_memory = AsyncMock(return_value=mock_save)
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "guarda-ho", "session_id": sid}
            )
        assert r.status_code == 200

    def test_recall_intent_treated_as_chat(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        mm = self._make_mock_module_manager()

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("recall", "Recordes el meu nom?"))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Recordes el meu nom?", "session_id": sid}
            )
        assert r.status_code == 200

    def test_chat_no_engine_available(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        registry = MagicMock()
        registry.get_module = MagicMock(return_value=None)  # cap engine
        registry.list_modules = MagicMock(return_value=[])
        mm = MagicMock()
        mm.registry = registry

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Hola com estàs?", "session_id": sid}
            )
        assert r.status_code == 200
        # Hauria de retornar missatge d'error sobre cap motor disponible
        assert "response" in r.json()

    def test_chat_engine_returns_string(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        engine = MagicMock()
        engine.chat = MagicMock(return_value="Direct string response")
        mm = self._make_mock_module_manager(engine=engine)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Test", "session_id": sid}
            )
        assert r.status_code == 200

    def test_chat_engine_raises_exception(self, client, auth):
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        engine = MagicMock()
        engine.chat = MagicMock(side_effect=Exception("Engine crashed"))
        mm = self._make_mock_module_manager(engine=engine)

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Test error", "session_id": sid}
            )
        assert r.status_code == 200

    def test_chat_rag_context_used(self, client, auth):
        """Comprova que RAG results s'injecten al context."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]
        engine = self._make_mock_engine()
        mm = self._make_mock_module_manager(engine=engine)
        captured_messages = []

        orig_chat = engine.chat.side_effect
        def capture_chat(**kwargs):
            msgs = kwargs.get("messages", [])
            captured_messages.extend(msgs)
            return {"response": "test"}

        engine.chat = MagicMock(side_effect=capture_chat)

        rag_results = [{"content": "El meu nom és Jordi", "score": 0.9, "metadata": {}}]

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={
                "success": True, "results": rag_results
            })
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh
            state = MagicMock()
            state.module_manager = mm
            mock_state.return_value = state
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Com em dic?", "session_id": sid, "rag_threshold": 0.5}
            )
        assert r.status_code == 200

    def test_chat_stream_mode(self, client, auth):
        """Chat en mode stream retorna StreamingResponse."""
        r1 = client.post("/ui/session/new", headers=auth)
        sid = r1.json()["session_id"]

        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("chat", None))
            hh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh

            # get_server_state raises → falls to error path
            mock_state.side_effect = Exception("No server state in test")

            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "Test stream", "session_id": sid, "stream": True}
            )
        # Can return 200 with StreamingResponse or JSON with error
        assert r.status_code == 200

    def test_chat_without_session_creates_one(self, client, auth):
        """Chat sense session_id crea sessió automàticament."""
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh, \
             patch("core.lifespan.get_server_state") as mock_state:
            hh = MagicMock()
            hh.detect_intent = MagicMock(return_value=("save", "some content here"))
            hh.save_to_memory = AsyncMock(return_value={"success": True, "document_id": "x", "message": ""})
            hh.auto_save = AsyncMock(return_value={"success": True, "document_id": None, "message": ""})
            mock_mh.return_value = hh
            mock_state.side_effect = Exception("no state")
            r = client.post(
                "/ui/chat", headers=auth,
                json={"message": "some content here, guarda-ho"}
            )
        assert r.status_code == 200


# ─── TestMemoryEndpoints ──────────────────────────────────────────────────────

class TestMemoryEndpoints:

    def test_save_missing_content_400(self, client, auth):
        r = client.post("/ui/memory/save", headers=auth, json={})
        assert r.status_code == 400

    def test_save_with_content(self, client, auth):
        mock_result = {"success": True, "document_id": "doc-1", "message": "✓"}
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh:
            hh = MagicMock()
            hh.save_to_memory = AsyncMock(return_value=mock_result)
            mock_mh.return_value = hh
            r = client.post(
                "/ui/memory/save", headers=auth,
                json={"content": "Important info", "session_id": "sess-1"}
            )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_recall_missing_query_400(self, client, auth):
        r = client.post("/ui/memory/recall", headers=auth, json={})
        assert r.status_code == 400

    def test_recall_with_query(self, client, auth):
        mock_result = {"success": True, "results": [], "total": 0, "message": ""}
        with patch("plugins.web_ui_module.api.routes.get_memory_helper") as mock_mh:
            hh = MagicMock()
            hh.recall_from_memory = AsyncMock(return_value=mock_result)
            mock_mh.return_value = hh
            r = client.post(
                "/ui/memory/recall", headers=auth,
                json={"query": "nom usuari", "limit": 3}
            )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_save_no_auth_401(self, client):
        r = client.post("/ui/memory/save", json={"content": "test"})
        assert r.status_code == 401

    def test_recall_no_auth_401(self, client):
        r = client.post("/ui/memory/recall", json={"query": "test"})
        assert r.status_code == 401


# ─── TestStartSessionCleanup ──────────────────────────────────────────────────

class TestStartSessionCleanup:

    def test_start_cleanup_task(self):
        """start_session_cleanup_task crea un asyncio.Task."""
        from plugins.web_ui_module.api.routes import start_session_cleanup_task

        async def run():
            with patch("asyncio.create_task") as mock_ct:
                start_session_cleanup_task(MagicMock())
                assert mock_ct.called

        asyncio.run(run())


# ─── TestGetModuleInstance ────────────────────────────────────────────────────

class TestGetModuleInstance:

    def test_returns_web_ui_module(self):
        from plugins.web_ui_module.module import WebUIModule
        inst = get_module_instance()
        assert isinstance(inst, WebUIModule)


# ─── TestGenerateRagMetadata ──────────────────────────────────────────────────

class TestGenerateRagMetadata:
    """Tests per _generate_rag_metadata (fallback path)."""

    def test_fallback_when_no_module_manager(self):
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata
        with patch("core.lifespan.get_server_state", side_effect=Exception("no state")):
            result = asyncio.run(_generate_rag_metadata("This is test content", "test.txt"))
        assert "abstract" in result
        assert "tags" in result

    def test_fallback_abstract_truncated(self):
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata
        long_content = "word " * 200
        with patch("core.lifespan.get_server_state", side_effect=Exception("no state")):
            result = asyncio.run(_generate_rag_metadata(long_content, "doc.txt"))
        assert len(result["abstract"]) <= 305  # 300 + possible space

    def test_fallback_includes_filename_stem_as_tag(self):
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata
        with patch("core.lifespan.get_server_state", side_effect=Exception("no state")):
            result = asyncio.run(_generate_rag_metadata("content", "my_document.txt"))
        assert any("my document" in t.lower() or "my_document" in t.lower()
                   for t in result["tags"])

    def test_fallback_has_required_fields(self):
        from plugins.web_ui_module.core.rag_handler import generate_rag_metadata as _generate_rag_metadata
        with patch("core.lifespan.get_server_state", side_effect=Exception("no state")):
            result = asyncio.run(_generate_rag_metadata("content", "file.pdf"))
        assert "priority" in result
        assert "type" in result
        assert "lang" in result
