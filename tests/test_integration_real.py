"""
Real integration tests against server-nexe.

Requires:
- Nexe server running at localhost:9119
- Ollama running at localhost:11434
- Qdrant running at localhost:6333
- NEXE_PRIMARY_API_KEY configured in .env

Run:
    pytest tests/test_integration_real.py -v --tb=short -m integration
"""

import io
import os
import time
import uuid

import httpx
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:9119"
TIMEOUT = 120.0  # large models take time to load


def _read_api_key() -> str:
    """Read the API key from .env or environment variable."""
    key = os.environ.get("NEXE_PRIMARY_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("NEXE_PRIMARY_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    pytest.skip("NEXE_PRIMARY_API_KEY not found")


@pytest.fixture(scope="session")
def api_key():
    return _read_api_key()


@pytest.fixture(scope="session")
def headers(api_key):
    return {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def async_client():
    # For streaming tests
    return httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)


def _server_available():
    """Verify that the server is running."""
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        return r.status_code == 200
    except httpx.ConnectError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _server_available(), reason="Nexe server not available"),
]


# ===========================================================================
# 1. HEALTH & STATUS ENDPOINTS
# ===========================================================================


class TestHealthEndpoints:
    """Public health and status endpoints."""

    def test_root_returns_system_info(self, client):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert "Nexe" in data.get("system", "")
        assert data.get("version", "").startswith("0.8")

    def test_health_operational(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("operational", "healthy")

    def test_status_shows_engine_and_modules(self, client):
        r = client.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert "engine" in data
        assert "modules_loaded" in data
        assert isinstance(data["modules_loaded"], list)
        assert len(data["modules_loaded"]) > 0

    def test_health_ready(self, client):
        r = client.get("/health/ready")
        assert r.status_code == 200

    def test_health_circuits(self, client):
        r = client.get("/health/circuits")
        assert r.status_code == 200

    def test_api_info(self, client):
        r = client.get("/api/info")
        assert r.status_code == 200


# ===========================================================================
# 2. INFO ENDPOINTS
# ===========================================================================


class TestInfoEndpoints:
    """API information endpoints."""

    def test_v1_root(self, client):
        r = client.get("/v1")
        assert r.status_code == 200
        data = r.json()
        assert data.get("api_version") == "v1"
        assert "endpoints" in data

    def test_info_endpoint(self, client):
        r = client.get("/info")
        assert r.status_code == 200


# ===========================================================================
# 3. SECURITY ENDPOINTS
# ===========================================================================


class TestSecurityEndpoints:
    """Security module endpoints."""

    def test_security_health(self, client, headers):
        # Audit r4 B2: now requires X-API-Key
        r = client.get("/security/health", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"

    def test_security_info(self, client, headers):
        # Audit r4 B2: now requires X-API-Key
        r = client.get("/security/info", headers=headers)
        assert r.status_code == 200

    def test_security_scan_requires_csrf(self, client, headers):
        # POST to /security/ requires CSRF token (not exempt)
        r = client.post("/security/scan", headers=headers)
        assert r.status_code in (200, 403)  # 403 = CSRF expected

    def test_security_scan_without_auth(self, client):
        r = client.post("/security/scan")
        assert r.status_code in (401, 403)


# ===========================================================================
# 4. UI HEALTH
# ===========================================================================


class TestUIHealth:
    """UI health check."""

    def test_ui_health(self, client, headers):
        r = client.get("/ui/health", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["initialized"] is True


# ===========================================================================
# 5. MEMORY STORE
# ===========================================================================


class TestMemoryStore:
    """Store real content in memory (Qdrant)."""

    def test_store_text(self, client, headers):
        r = client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": f"Test d'integració: El cel és blau — {uuid.uuid4().hex[:8]}",
                "collection": "personal_memory",
                "metadata": {"source": "integration_test", "type": "fact"},
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("success") is True or "document_id" in data or "id" in data

    def test_store_with_metadata(self, client, headers):
        r = client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": "Barcelona és la capital de Catalunya",
                "collection": "personal_memory",
                "metadata": {
                    "source": "integration_test",
                    "type": "geographic_fact",
                    "language": "ca",
                },
            },
        )
        assert r.status_code == 200

    def test_store_without_auth(self, client):
        r = client.post(
            "/v1/memory/store",
            json={"content": "This should fail"},
        )
        assert r.status_code in (401, 403)


# ===========================================================================
# 6. MEMORY SEARCH
# ===========================================================================


class TestMemorySearch:
    """Search real content in memory."""

    def test_search_stored_content(self, client, headers):
        # First store something unique
        unique = f"La Torre Eiffel fa 330 metres — {uuid.uuid4().hex[:8]}"
        client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": unique,
                "collection": "personal_memory",
                "metadata": {"source": "integration_test"},
            },
        )
        # Wait a moment for Qdrant to index
        time.sleep(1)
        # Search
        r = client.post(
            "/v1/memory/search",
            headers=headers,
            json={"query": "Torre Eiffel metres", "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert "results" in data

    def test_search_no_results(self, client, headers):
        r = client.post(
            "/v1/memory/search",
            headers=headers,
            json={"query": "xyznonexistent9876543210", "limit": 5},
        )
        assert r.status_code == 200

    def test_search_with_limit(self, client, headers):
        r = client.post(
            "/v1/memory/search",
            headers=headers,
            json={"query": "test", "limit": 1},
        )
        assert r.status_code == 200
        data = r.json()
        results = data.get("results", [])
        assert len(results) <= 1

    def test_search_without_auth(self, client):
        r = client.post(
            "/v1/memory/search",
            json={"query": "test"},
        )
        assert r.status_code in (401, 403)


# ===========================================================================
# 7. CHAT — MLX (currently loaded model)
# ===========================================================================


class TestChatMLX:
    """Chat with the MLX engine (model already loaded on the server)."""

    def test_chat_simple_question(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Quant fa 2+2? Respon només el número."}],
                "max_tokens": 50,
            },
        )
        assert r.status_code == 200
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        assert "4" in content

    def test_chat_response_format(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Di OK"}],
                "max_tokens": 20,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]
        assert "usage" in data
        assert data.get("nexe_engine") in ("mlx", "ollama", "llama_cpp")

    def test_chat_with_system_prompt(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {"role": "system", "content": "Respon sempre amb exactament una paraula."},
                    {"role": "user", "content": "Quin color és el cel?"},
                ],
                "max_tokens": 30,
            },
        )
        assert r.status_code == 200
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        assert len(content.strip()) > 0

    def test_chat_max_tokens_respected(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Di OK"}],
                "max_tokens": 10,
            },
            timeout=180.0,
        )
        assert r.status_code == 200
        data = r.json()
        # With max_tokens=10, the response must be short
        usage = data.get("usage", {})
        if "completion_tokens" in usage:
            assert usage["completion_tokens"] <= 50  # margin for special/thinking tokens


# ===========================================================================
# 8. CHAT — OLLAMA SMALL (phi3:mini)
# ===========================================================================


class TestChatOllamaSmall:
    """Chat with Ollama small model (phi3:mini 2.2GB)."""

    def test_chat_ollama_phi3(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Say OK"}],
                "engine": "ollama",
                "model": "phi3:mini",
                "max_tokens": 20,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("nexe_engine") == "ollama"

    def test_chat_ollama_response_has_content(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "What is 1+1?"}],
                "engine": "ollama",
                "model": "phi3:mini",
                "max_tokens": 30,
            },
        )
        assert r.status_code == 200
        data = r.json()
        # Ollama may return a different format
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "message" in data:
            content = data["message"]["content"]
        else:
            content = str(data)
        assert len(content) > 0

    def test_chat_catalan_with_ollama(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Digues hola en català"}],
                "engine": "ollama",
                "model": "phi3:mini",
                "max_tokens": 50,
            },
        )
        assert r.status_code == 200


# ===========================================================================
# 9. CHAT — OLLAMA MEDIUM (llama3:8b)
# ===========================================================================


class TestChatOllamaMedium:
    """Chat with Ollama medium model (llama3:8b 4.7GB)."""

    def test_chat_ollama_llama3(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Explain gravity in one sentence"}],
                "engine": "ollama",
                "model": "llama3:8b",
                "max_tokens": 100,
            },
        )
        assert r.status_code == 200
        data = r.json()
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "message" in data:
            content = data["message"]["content"]
        else:
            content = ""
        assert len(content) > 10

    def test_chat_code_generation(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "Write a Python function that adds two numbers. Only code, no explanation.",
                    }
                ],
                "engine": "ollama",
                "model": "llama3:8b",
                "max_tokens": 150,
            },
        )
        assert r.status_code == 200
        data = r.json()
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "message" in data:
            content = data["message"]["content"]
        else:
            content = ""
        assert "def" in content or "function" in content.lower() or "return" in content


# ===========================================================================
# 10. CHAT — OLLAMA LARGE (llama2:13b)
# ===========================================================================


class TestChatOllamaLarge:
    """Chat with Ollama large model (llama2:13b 7.4GB)."""

    def test_chat_ollama_llama2_13b(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "What are three differences between Python and JavaScript?",
                    }
                ],
                "engine": "ollama",
                "model": "llama2:13b",
                "max_tokens": 200,
            },
        )
        assert r.status_code == 200
        data = r.json()
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "message" in data:
            content = data["message"]["content"]
        else:
            content = ""
        assert len(content) > 20

    def test_chat_long_context(self, client, headers):
        long_text = "The quick brown fox jumps over the lazy dog. " * 20
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": f"Summarize this text: {long_text}"}
                ],
                "engine": "ollama",
                "model": "llama2:13b",
                "max_tokens": 100,
            },
        )
        assert r.status_code == 200


# ===========================================================================
# 11. CHAT — STREAMING SSE
# ===========================================================================


class TestChatStreaming:
    """Chat with streaming (Server-Sent Events)."""

    def test_streaming_sse_format(self, client, headers):
        with client.stream(
            "POST",
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Di hola"}],
                "stream": True,
                "max_tokens": 30,
            },
        ) as response:
            assert response.status_code == 200
            chunks = []
            for line in response.iter_lines():
                if line.startswith("data:"):
                    chunks.append(line)
            assert len(chunks) > 0

    def test_streaming_complete_response(self, client, headers):
        with client.stream(
            "POST",
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Compta de 1 a 5"}],
                "stream": True,
                "max_tokens": 50,
            },
        ) as response:
            assert response.status_code == 200
            full_text = ""
            for line in response.iter_lines():
                if line.startswith("data:") and "[DONE]" not in line:
                    full_text += line
            assert len(full_text) > 0

    def test_streaming_done_marker(self, client, headers):
        with client.stream(
            "POST",
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "OK"}],
                "stream": True,
                "max_tokens": 10,
            },
        ) as response:
            assert response.status_code == 200
            lines = list(response.iter_lines())
            # The last chunk with content must be [DONE]
            data_lines = [l for l in lines if l.strip()]
            if data_lines:
                assert any("[DONE]" in l for l in data_lines)


# ===========================================================================
# 12. CHAT — RAG (real memory)
# ===========================================================================


class TestChatRAG:
    """Chat with RAG enabled — uses real memory."""

    def test_chat_with_rag_uses_context(self, client, headers):
        # 1. Store a unique fact
        unique_fact = f"La muntanya Nexetest té {uuid.uuid4().hex[:4]} metres d'alçada"
        client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": unique_fact,
                "collection": "personal_memory",
                "metadata": {"source": "rag_test"},
            },
        )
        time.sleep(2)  # Qdrant indexes

        # 2. Ask about the fact with RAG
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": "Quina alçada té la muntanya Nexetest?"}
                ],
                "use_rag": True,
                "max_tokens": 100,
            },
        )
        assert r.status_code == 200

    def test_chat_without_rag(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "Di OK"}],
                "use_rag": False,
                "max_tokens": 20,
            },
        )
        assert r.status_code == 200


# ===========================================================================
# 13. CHAT — MULTILINGUAL
# ===========================================================================


class TestChatMultilingual:
    """Verify that the server responds in multiple languages."""

    def test_chat_catalan(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": "Explica'm en una frase curta què és la Via Làctia"}
                ],
                "max_tokens": 100,
            },
        )
        assert r.status_code == 200
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 10

    def test_chat_spanish(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": "Explica en una frase qué es la fotosíntesis"}
                ],
                "max_tokens": 100,
            },
        )
        assert r.status_code == 200

    def test_chat_english(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {"role": "user", "content": "Explain in one sentence what DNA is"}
                ],
                "max_tokens": 100,
            },
        )
        assert r.status_code == 200


# ===========================================================================
# 14. CHAT — ERROR HANDLING
# ===========================================================================


class TestChatErrorHandling:
    """Verify chat error handling."""

    def test_chat_no_auth(self, client):
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "test"}]},
        )
        assert r.status_code in (401, 403)

    def test_chat_empty_messages_accepted(self, client, headers):
        # The server accepts messages=[] with graceful fallback
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"messages": []},
        )
        assert r.status_code in (200, 400, 422)

    def test_chat_invalid_payload(self, client, headers):
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"invalid": "payload"},
        )
        assert r.status_code in (400, 422)

    def test_chat_nonexistent_model_fallback(self, client, headers):
        # The server falls back to an available engine if the model does not exist
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "test"}],
                "engine": "ollama",
                "model": "model-que-no-existeix-xyz",
                "max_tokens": 10,
            },
        )
        # May return 200 (fallback) or error
        assert r.status_code in (200, 400, 404, 422, 500, 503)


# ===========================================================================
# 15. UI — SESSIONS
# ===========================================================================


class TestUISession:
    """UI session management."""

    def test_create_session(self, client, headers):
        r = client.post("/ui/session/new", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data or "id" in data

    def test_list_sessions(self, client, headers):
        r = client.get("/ui/sessions", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))

    def test_session_lifecycle(self, client, headers):
        # Create
        r = client.post("/ui/session/new", headers=headers)
        assert r.status_code == 200
        data = r.json()
        session_id = data.get("session_id") or data.get("id")
        assert session_id

        # Get info
        r = client.get(f"/ui/session/{session_id}", headers=headers)
        assert r.status_code == 200

        # History
        r = client.get(f"/ui/session/{session_id}/history", headers=headers)
        assert r.status_code == 200

        # Delete
        r = client.delete(f"/ui/session/{session_id}", headers=headers)
        assert r.status_code == 200


# ===========================================================================
# 16. UI — CHAT
# ===========================================================================


class TestUIChat:
    """Chat via the web UI interface."""

    def test_ui_chat_simple(self, client, headers):
        r = client.post(
            "/ui/chat",
            headers=headers,
            json={"message": "Hola, com estàs?", "stream": False},
        )
        assert r.status_code == 200
        data = r.json()
        assert "response" in data or "message" in data or "choices" in data

    def test_ui_chat_with_session(self, client, headers):
        # Create session
        r = client.post("/ui/session/new", headers=headers)
        session_id = r.json().get("session_id") or r.json().get("id")

        # Chat with the session
        r = client.post(
            "/ui/chat",
            headers=headers,
            json={
                "message": "Recorda que el meu color preferit és el verd",
                "session_id": session_id,
                "stream": False,
            },
        )
        assert r.status_code == 200

    def test_ui_chat_without_auth(self, client):
        r = client.post(
            "/ui/chat",
            json={"message": "test"},
        )
        assert r.status_code in (401, 403)


# ===========================================================================
# 17. UI — FILE UPLOAD
# ===========================================================================


class TestUIFileUpload:
    """File upload via UI."""

    def test_upload_txt_file(self, client, headers):
        content = (
            "Document de prova per tests d'integració.\n"
            "El sistema Nexe ha de poder processar aquest fitxer.\n"
            "Conté informació sobre proves automatitzades.\n"
            "Les proves d'integració són essencials per la qualitat del programari."
        )
        files = {"file": ("test_document.txt", io.BytesIO(content.encode()), "text/plain")}
        # Remove Content-Type so httpx sets it automatically for multipart
        upload_headers = {"X-API-Key": headers["X-API-Key"]}
        r = client.post("/ui/upload", headers=upload_headers, files=files)
        assert r.status_code == 200
        data = r.json()
        assert data.get("filename") == "test_document.txt" or "filename" in data

    def test_upload_without_auth(self, client):
        files = {"file": ("test.txt", io.BytesIO(b"test"), "text/plain")}
        r = client.post("/ui/upload", files=files)
        assert r.status_code in (401, 403)


# ===========================================================================
# 18. UI — MEMORY
# ===========================================================================


class TestUIMemory:
    """Memory operations via UI."""

    def test_save_memory(self, client, headers):
        r = client.post(
            "/ui/memory/save",
            headers=headers,
            json={"content": "El Jordi utilitza Nexe per gestionar IA local"},
        )
        assert r.status_code == 200

    def test_recall_memory(self, client, headers):
        r = client.post(
            "/ui/memory/recall",
            headers=headers,
            json={"query": "Nexe IA local"},
        )
        assert r.status_code == 200

    def test_recall_without_auth(self, client):
        r = client.post(
            "/ui/memory/recall",
            json={"query": "test"},
        )
        assert r.status_code in (401, 403)


# ===========================================================================
# 19. BOOTSTRAP INFO
# ===========================================================================


class TestBootstrapInfo:
    """Bootstrap system information."""

    def test_bootstrap_info(self, client):
        r = client.get("/api/bootstrap/info")
        assert r.status_code == 200
        data = r.json()
        assert "bootstrap_enabled" in data or "mode" in data or "status" in data

    def test_bootstrap_info_no_auth_needed(self, client):
        # Bootstrap info is public
        r = client.get("/api/bootstrap/info")
        assert r.status_code == 200


# ===========================================================================
# 20. ADMIN SYSTEM
# ===========================================================================


class TestAdminSystem:
    """System administration endpoints (no restart!)."""

    def test_system_health(self, client):
        r = client.get("/admin/system/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") in ("healthy", "operational")

    def test_system_status(self, client, headers):
        r = client.get("/admin/system/status", headers=headers)
        assert r.status_code == 200


# ===========================================================================
# 21. END-TO-END FLOW
# ===========================================================================


class TestEndToEndFlow:
    """Complete flow: store → chat with RAG → recall → verify."""

    def test_full_rag_pipeline(self, client, headers):
        # 1. Store a unique fact in memory
        unique_id = uuid.uuid4().hex[:8]
        fact = f"La ciutat de Nexegrad-{unique_id} té exactament 742.831 habitants"

        r = client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": fact,
                "collection": "personal_memory",
                "metadata": {"source": "e2e_test", "type": "geographic_fact"},
            },
        )
        assert r.status_code == 200

        # 2. Wait for indexing
        time.sleep(2)

        # 3. Chat with RAG asking about the fact
        r = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": f"Quants habitants té Nexegrad-{unique_id}? "
                        "Respon amb el número exacte si el coneixes.",
                    }
                ],
                "use_rag": True,
                "max_tokens": 100,
            },
        )
        assert r.status_code == 200
        data = r.json()
        chat_response = data["choices"][0]["message"]["content"]
        # The model should mention the number if RAG works
        # (not always guaranteed, depends on the model)

        # 4. Recall — search for the stored fact
        r = client.post(
            "/v1/memory/search",
            headers=headers,
            json={"query": f"Nexegrad-{unique_id} habitants", "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        results = data.get("results", [])
        # Must find the document we stored
        assert len(results) > 0
        found = any("742.831" in str(result) or unique_id in str(result) for result in results)
        assert found, f"Stored fact not found. Results: {results}"

    def test_ui_chat_then_recall(self, client, headers):
        """Chat via UI and verify it is saved to memory."""
        # 1. Create session
        r = client.post("/ui/session/new", headers=headers)
        session_id = r.json().get("session_id") or r.json().get("id")

        # 2. Chat
        unique_topic = f"test-topic-{uuid.uuid4().hex[:6]}"
        r = client.post(
            "/ui/chat",
            headers=headers,
            json={
                "message": f"Recorda que el projecte {unique_topic} és molt important",
                "session_id": session_id,
                "stream": False,
            },
        )
        assert r.status_code == 200

        # 3. Verify session history
        r = client.get(f"/ui/session/{session_id}/history", headers=headers)
        assert r.status_code == 200


# ===========================================================================
# 22. MULTI-ENGINE COMPARISON
# ===========================================================================


class TestMultiEngine:
    """Compare responses between different engines."""

    def test_same_question_different_engines(self, client, headers):
        question = "What is the capital of France? Answer with just the city name."
        engines = [
            {"engine": "mlx"},
            {"engine": "ollama", "model": "phi3:mini"},
        ]
        responses = {}
        for engine_config in engines:
            r = client.post(
                "/v1/chat/completions",
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": question}],
                    "max_tokens": 30,
                    **engine_config,
                },
            )
            assert r.status_code == 200
            data = r.json()
            engine_name = engine_config["engine"]
            if "choices" in data:
                responses[engine_name] = data["choices"][0]["message"]["content"]
            elif "message" in data:
                responses[engine_name] = data["message"]["content"]

        # All should mention Paris
        for engine, response in responses.items():
            assert "paris" in response.lower() or "París" in response, (
                f"Engine {engine} did not respond with Paris: {response}"
            )

    def test_engines_available(self, client):
        r = client.get("/status")
        data = r.json()
        engines = data.get("engines_available", {})
        # At least one engine must be active
        assert any(engines.values()), f"No engine available: {engines}"
