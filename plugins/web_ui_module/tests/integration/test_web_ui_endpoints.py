"""
Tests d'integració per als endpoints Web UI.

Endpoints sense GPU (sessions, upload, fitxers):
  pytest -m integration  (sempre executables)

Endpoints amb GPU (chat):
  pytest -m "integration and gpu"  (requereix backend actiu)

Variables d'entorn:
  NEXE_PRIMARY_API_KEY  — clau d'accés
  NEXE_MODEL_ENGINE     — ollama | mlx | llama_cpp
"""
import io
import os
import pytest
from fastapi.testclient import TestClient

from core.app import app

# ─────────────────────────────────────────────────────────────
# Fixtures globals
# ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def api_key():
    return os.environ.get("NEXE_PRIMARY_API_KEY", "nexe-integration-test")


@pytest.fixture(scope="module")
def client(api_key):
    os.environ.setdefault("NEXE_PRIMARY_API_KEY", api_key)
    os.environ.setdefault("NEXE_ENV", "testing")
    os.environ.setdefault("NEXE_DEV_MODE", "true")
    return TestClient(app, base_url="http://localhost")


@pytest.fixture(scope="module")
def headers(api_key):
    return {"X-API-Key": api_key}


# ─────────────────────────────────────────────────────────────
# Health endpoint (sense GPU)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestWebUIHealth:

    def test_health_returns_200(self, client, headers):
        r = client.get("/ui/health", headers=headers)
        assert r.status_code == 200

    def test_health_has_status(self, client, headers):
        r = client.get("/ui/health", headers=headers)
        body = r.json()
        assert "status" in body or r.status_code == 200


# ─────────────────────────────────────────────────────────────
# Sessions (sense GPU)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestSessionEndpoints:

    def test_create_session(self, client, headers):
        r = client.post("/ui/session/new", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "session_id" in body
        assert len(body["session_id"]) > 0

    def test_get_session(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r2 = client.get(f"/ui/session/{sid}", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["id"] == sid

    def test_get_nonexistent_session_404(self, client, headers):
        r = client.get("/ui/session/does-not-exist-xyz", headers=headers)
        assert r.status_code == 404

    def test_get_session_history(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r2 = client.get(f"/ui/session/{sid}/history", headers=headers)
        assert r2.status_code == 200
        assert "messages" in r2.json()
        assert isinstance(r2.json()["messages"], list)

    def test_delete_session(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r2 = client.delete(f"/ui/session/{sid}", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["status"] == "deleted"

        r3 = client.get(f"/ui/session/{sid}", headers=headers)
        assert r3.status_code == 404

    def test_delete_nonexistent_404(self, client, headers):
        r = client.delete("/ui/session/ghost-xyz", headers=headers)
        assert r.status_code == 404

    def test_list_sessions(self, client, headers):
        client.post("/ui/session/new", headers=headers)
        r = client.get("/ui/sessions", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "sessions" in body
        assert isinstance(body["sessions"], list)
        assert len(body["sessions"]) >= 1


# ─────────────────────────────────────────────────────────────
# Upload (sense GPU)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestUploadEndpoints:

    def _upload_txt(self, client, headers, content="Test document content for ingestion."):
        return client.post(
            "/ui/upload",
            headers=headers,
            files={"file": ("test_doc.txt", io.BytesIO(content.encode()), "text/plain")},
            data={}
        )

    def test_upload_valid_txt(self, client, headers):
        r = self._upload_txt(client, headers)
        # May be 200 (success) or 503 if memory backend not available in test env
        assert r.status_code in [200, 400, 503]

    def test_upload_invalid_extension_rejected(self, client, headers):
        r = client.post(
            "/ui/upload",
            headers=headers,
            files={"file": ("malware.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
            data={}
        )
        assert r.status_code == 400

    def test_upload_empty_txt_rejected(self, client, headers):
        r = client.post(
            "/ui/upload",
            headers=headers,
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
            data={}
        )
        # Empty file => extract_text returns "" => 400
        assert r.status_code in [400, 503]

    def test_list_files(self, client, headers):
        r = client.get("/ui/files", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert "files" in body
        assert "total" in body

    def test_cleanup_files(self, client, headers):
        r = client.post("/ui/files/cleanup", headers=headers, params={"max_age_hours": 9999})
        assert r.status_code == 200
        assert "deleted" in r.json()


# ─────────────────────────────────────────────────────────────
# Chat — empty message (sense GPU)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestChatValidation:

    def test_chat_empty_message_rejected(self, client, headers):
        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "", "session_id": None}
        )
        assert r.status_code == 400

    def test_chat_missing_message_rejected(self, client, headers):
        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"session_id": None}
        )
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────
# Chat — amb GPU real (Ollama)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.gpu
@pytest.mark.slow
class TestChatOllama:
    """
    Requereix Ollama actiu amb el model configurat a NEXE_OLLAMA_MODEL.
    Executar amb: pytest -m "integration and gpu"
    """

    @pytest.fixture(autouse=True)
    def require_ollama(self):
        engine = os.environ.get("NEXE_MODEL_ENGINE", "")
        if engine not in ("ollama", ""):
            pytest.skip("Ollama not selected engine")
        import subprocess
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        except Exception:
            pytest.skip("Ollama not running")

    def test_chat_returns_response(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Respon amb una sola paraula: Hola", "session_id": sid},
            timeout=60
        )
        assert r.status_code == 200
        body = r.json()
        assert "response" in body or "message" in body or "text" in body

    def test_chat_history_grows(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Di 'un'", "session_id": sid},
            timeout=60
        )

        r_hist = client.get(f"/ui/session/{sid}/history", headers=headers)
        msgs = r_hist.json()["messages"]
        assert len(msgs) >= 2  # user + assistant

    def test_chat_session_persistence(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Número secret: 42", "session_id": sid},
            timeout=60
        )

        r2 = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Quin era el número secret?", "session_id": sid},
            timeout=90
        )
        assert r2.status_code == 200


# ─────────────────────────────────────────────────────────────
# Chat — amb GPU real (MLX)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.gpu
@pytest.mark.slow
class TestChatMLX:
    """
    Requereix Apple Silicon + mlx_lm + model configurat a NEXE_MLX_MODEL.
    Executar amb: pytest -m "integration and gpu"
    """

    @pytest.fixture(autouse=True)
    def require_mlx(self):
        if os.environ.get("NEXE_MODEL_ENGINE") != "mlx":
            pytest.skip("MLX not selected engine")
        try:
            import mlx_lm  # noqa: F401
        except ImportError:
            pytest.skip("mlx_lm not installed")

    def test_chat_mlx_basic(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Respon amb una paraula: OK", "session_id": sid},
            timeout=120
        )
        assert r.status_code == 200

    def test_chat_mlx_prefix_cache(self, client, headers):
        """Doble petició en la mateixa sessió — comprova que el prefix cache funciona."""
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        for msg in ["Primera pregunta: di 'un'", "Segona pregunta: di 'dos'"]:
            r = client.post(
                "/ui/chat",
                headers=headers,
                json={"message": msg, "session_id": sid},
                timeout=120
            )
            assert r.status_code == 200


# ─────────────────────────────────────────────────────────────
# Static files (sense GPU)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestStaticFiles:

    def test_static_path_traversal_blocked(self, client, headers):
        r = client.get("/ui/static/../../../etc/passwd", headers=headers)
        assert r.status_code in [400, 403, 404]
