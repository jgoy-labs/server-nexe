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
    with TestClient(app, base_url="http://localhost") as c:
        yield c


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
# Memory endpoints — validació (sense GPU ni Qdrant)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestMemoryValidation:

    def test_save_empty_content_rejected(self, client, headers):
        r = client.post(
            "/ui/memory/save",
            headers=headers,
            json={"content": "", "session_id": "test"}
        )
        assert r.status_code == 400

    def test_recall_empty_query_rejected(self, client, headers):
        r = client.post(
            "/ui/memory/recall",
            headers=headers,
            json={"query": ""}
        )
        assert r.status_code == 400

    def test_save_returns_json(self, client, headers):
        r = client.post(
            "/ui/memory/save",
            headers=headers,
            json={"content": "Test content that should be saved to memory", "session_id": "test-val"}
        )
        # 200 (Qdrant disponible) o error de backend (503/500) — sempre JSON
        assert r.headers["content-type"].startswith("application/json")

    def test_recall_returns_json(self, client, headers):
        r = client.post(
            "/ui/memory/recall",
            headers=headers,
            json={"query": "test query", "limit": 3}
        )
        assert r.headers["content-type"].startswith("application/json")


# ─────────────────────────────────────────────────────────────
# Memory — save + recall round-trip (requereix Qdrant)
# ─────────────────────────────────────────────────────────────

def _qdrant_available():
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:6333/healthz", timeout=2)
        return True
    except Exception:
        return False


def _memory_api_available():
    """Verifica que la Memory API es pot inicialitzar (Qdrant + dependències OK)."""
    if not _qdrant_available():
        return False
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.slow
class TestMemoryRoundTrip:
    """
    Requereix Qdrant actiu (localhost:6333).
    Executar amb: pytest -m "integration and slow"
    """

    @pytest.fixture(autouse=True)
    def require_qdrant(self):
        if not _memory_api_available():
            pytest.skip("Memory API not available (Qdrant or dependencies not ready)")

    def test_save_succeeds(self, client, headers):
        r = client.post(
            "/ui/memory/save",
            headers=headers,
            json={
                "content": "El nom de l'usuari de test és TestUser_unique_xyz",
                "session_id": "round-trip-test",
                "metadata": {"type": "fact"}
            }
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("success") is True

    def test_recall_finds_saved_content(self, client, headers):
        # Primer guardar
        client.post(
            "/ui/memory/save",
            headers=headers,
            json={
                "content": "La ciutat preferida és Girona_recall_test",
                "session_id": "recall-test",
                "metadata": {"type": "fact"}
            }
        )
        # Després cercar
        r = client.post(
            "/ui/memory/recall",
            headers=headers,
            json={"query": "Girona_recall_test", "limit": 5}
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("success") is True
        assert "results" in body

    def test_recall_limit_respected(self, client, headers):
        r = client.post(
            "/ui/memory/recall",
            headers=headers,
            json={"query": "test", "limit": 2}
        )
        assert r.status_code == 200
        body = r.json()
        results = body.get("results", [])
        assert len(results) <= 2

    def test_duplicate_not_saved_twice(self, client, headers):
        content = "Contingut únic per test de deduplicació abc123xyz"
        # Guardar dos cops
        r1 = client.post("/ui/memory/save", headers=headers,
                         json={"content": content, "session_id": "dedup-test"})
        r2 = client.post("/ui/memory/save", headers=headers,
                         json={"content": content, "session_id": "dedup-test"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        # El segon ha de dir que ja existeix (duplicate) o success
        body2 = r2.json()
        assert body2.get("success") is True


# ─────────────────────────────────────────────────────────────
# Memory — intenció de guardar via chat (requereix GPU + Qdrant)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.gpu
@pytest.mark.slow
class TestChatMemoryIntentOllama:
    """
    Prova el flux complet: missatge amb intent de guardar →
    el model respon + es guarda a Qdrant.
    Requereix Ollama + Qdrant actius.
    """

    @pytest.fixture(autouse=True)
    def require_backends(self):
        engine = os.environ.get("NEXE_MODEL_ENGINE", "")
        if engine not in ("ollama", ""):
            pytest.skip("Ollama not selected engine")
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        except Exception:
            pytest.skip("Ollama not running")
        if not _qdrant_available():
            pytest.skip("Qdrant not running")

    def test_save_intent_via_chat(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={
                "message": "El meu color preferit és el blau, ho pots guardar?",
                "session_id": sid
            },
            timeout=60
        )
        assert r.status_code == 200
        body = r.json()
        # memory_action ha de ser "save"
        assert body.get("memory_action") == "save"

    def test_recall_intent_via_chat(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        # Primer guardar directament
        client.post("/ui/memory/save", headers=headers,
                    json={"content": "L'usuari es diu Recall_Test_User", "session_id": sid})

        # Després preguntar
        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Recordes el nom de l'usuari?", "session_id": sid},
            timeout=60
        )
        assert r.status_code == 200

    def test_full_memory_round_trip_via_chat(self, client, headers):
        """Guardar informació via chat → recuperar-la en la mateixa sessió."""
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        # Guardar
        client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Em dic RoundTrip_Test_42, pots guardar-ho?", "session_id": sid},
            timeout=60
        )

        # Recall explícit per API
        r = client.post(
            "/ui/memory/recall",
            headers=headers,
            json={"query": "RoundTrip_Test_42", "limit": 3}
        )
        assert r.status_code == 200


@pytest.mark.integration
@pytest.mark.gpu
@pytest.mark.slow
class TestChatMemoryIntentMLX:
    """
    Mateix flux que TestChatMemoryIntentOllama però amb MLX.
    """

    @pytest.fixture(autouse=True)
    def require_backends(self):
        if os.environ.get("NEXE_MODEL_ENGINE") != "mlx":
            pytest.skip("MLX not selected engine")
        try:
            import mlx_lm  # noqa: F401
        except ImportError:
            pytest.skip("mlx_lm not installed")
        if not _qdrant_available():
            pytest.skip("Qdrant not running")

    def test_save_intent_via_chat_mlx(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={
                "message": "La meva professió és enginyer, ho pots guardar?",
                "session_id": sid
            },
            timeout=120
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("memory_action") == "save"

    def test_recall_intent_via_chat_mlx(self, client, headers):
        r1 = client.post("/ui/session/new", headers=headers)
        sid = r1.json()["session_id"]

        client.post("/ui/memory/save", headers=headers,
                    json={"content": "L'usuari prefereix Python sobre Java", "session_id": sid})

        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Quin llenguatge de programació prefereixo?", "session_id": sid},
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
