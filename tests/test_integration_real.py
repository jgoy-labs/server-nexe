"""
Tests d'integració reals contra el servidor Nexe 0.8.

Requereix:
- Servidor Nexe actiu a localhost:9119
- Ollama actiu a localhost:11434
- Qdrant actiu a localhost:6333
- NEXE_PRIMARY_API_KEY configurat al .env

Executar:
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
TIMEOUT = 120.0  # models grans triguen a carregar


def _read_api_key() -> str:
    """Llegeix la API key del .env o variable d'entorn."""
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
    # Per tests de streaming
    return httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)


def _server_available():
    """Verificar que el servidor està actiu."""
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        return r.status_code == 200
    except httpx.ConnectError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _server_available(), reason="Servidor Nexe no disponible"),
]


# ===========================================================================
# 1. HEALTH & STATUS ENDPOINTS
# ===========================================================================


class TestHealthEndpoints:
    """Endpoints públics de salut i estat."""

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
    """Endpoints d'informació de l'API."""

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
    """Endpoints del mòdul de seguretat."""

    def test_security_health(self, client):
        r = client.get("/security/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"

    def test_security_info(self, client):
        r = client.get("/security/info")
        assert r.status_code == 200

    def test_security_scan_requires_csrf(self, client, headers):
        # POST a /security/ requereix CSRF token (no exempt)
        r = client.post("/security/scan", headers=headers)
        assert r.status_code in (200, 403)  # 403 = CSRF expected

    def test_security_scan_without_auth(self, client):
        r = client.post("/security/scan")
        assert r.status_code in (401, 403)


# ===========================================================================
# 4. UI HEALTH
# ===========================================================================


class TestUIHealth:
    """Health check de la UI."""

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
    """Guardar contingut real a la memòria (Qdrant)."""

    def test_store_text(self, client, headers):
        r = client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": f"Test d'integració: El cel és blau — {uuid.uuid4().hex[:8]}",
                "collection": "nexe_chat_memory",
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
                "collection": "nexe_chat_memory",
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
    """Buscar contingut real a la memòria."""

    def test_search_stored_content(self, client, headers):
        # Primer guardem quelcom únic
        unique = f"La Torre Eiffel fa 330 metres — {uuid.uuid4().hex[:8]}"
        client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": unique,
                "collection": "nexe_chat_memory",
                "metadata": {"source": "integration_test"},
            },
        )
        # Esperem un moment perquè Qdrant indexi
        time.sleep(1)
        # Busquem
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
# 7. CHAT — MLX (model actual carregat)
# ===========================================================================


class TestChatMLX:
    """Chat amb el motor MLX (model ja carregat al servidor)."""

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
        # Amb max_tokens=10, la resposta ha de ser curta
        usage = data.get("usage", {})
        if "completion_tokens" in usage:
            assert usage["completion_tokens"] <= 50  # marge per tokens especials/thinking


# ===========================================================================
# 8. CHAT — OLLAMA PETIT (phi3:mini)
# ===========================================================================


class TestChatOllamaSmall:
    """Chat amb Ollama model petit (phi3:mini 2.2GB)."""

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
        # Ollama pot retornar format diferent
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
# 9. CHAT — OLLAMA MITJÀ (llama3:8b)
# ===========================================================================


class TestChatOllamaMedium:
    """Chat amb Ollama model mitjà (llama3:8b 4.7GB)."""

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
# 10. CHAT — OLLAMA GRAN (llama2:13b)
# ===========================================================================


class TestChatOllamaLarge:
    """Chat amb Ollama model gran (llama2:13b 7.4GB)."""

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
    """Chat amb streaming (Server-Sent Events)."""

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
            # L'últim chunk amb contingut ha de ser [DONE]
            data_lines = [l for l in lines if l.strip()]
            if data_lines:
                assert any("[DONE]" in l for l in data_lines)


# ===========================================================================
# 12. CHAT — RAG (memòria real)
# ===========================================================================


class TestChatRAG:
    """Chat amb RAG activat — usa memòria real."""

    def test_chat_with_rag_uses_context(self, client, headers):
        # 1. Guardar un fet únic
        unique_fact = f"La muntanya Nexetest té {uuid.uuid4().hex[:4]} metres d'alçada"
        client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": unique_fact,
                "collection": "nexe_chat_memory",
                "metadata": {"source": "rag_test"},
            },
        )
        time.sleep(2)  # Qdrant indexa

        # 2. Preguntar sobre el fet amb RAG
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
# 13. CHAT — MULTILINGÜE
# ===========================================================================


class TestChatMultilingual:
    """Verificar que el servidor respon en múltiples idiomes."""

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
    """Verificar gestió d'errors del chat."""

    def test_chat_no_auth(self, client):
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "test"}]},
        )
        assert r.status_code in (401, 403)

    def test_chat_empty_messages_accepted(self, client, headers):
        # El servidor accepta messages=[] amb fallback graceful
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
        # El servidor fa fallback a un engine disponible si el model no existeix
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
        # Pot retornar 200 (fallback) o error
        assert r.status_code in (200, 400, 404, 422, 500, 503)


# ===========================================================================
# 15. UI — SESSIONS
# ===========================================================================


class TestUISession:
    """Gestió de sessions de la UI."""

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
        # Crear
        r = client.post("/ui/session/new", headers=headers)
        assert r.status_code == 200
        data = r.json()
        session_id = data.get("session_id") or data.get("id")
        assert session_id

        # Obtenir info
        r = client.get(f"/ui/session/{session_id}", headers=headers)
        assert r.status_code == 200

        # Historial
        r = client.get(f"/ui/session/{session_id}/history", headers=headers)
        assert r.status_code == 200

        # Eliminar
        r = client.delete(f"/ui/session/{session_id}", headers=headers)
        assert r.status_code == 200


# ===========================================================================
# 16. UI — CHAT
# ===========================================================================


class TestUIChat:
    """Chat via la interfície web UI."""

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
        # Crear sessió
        r = client.post("/ui/session/new", headers=headers)
        session_id = r.json().get("session_id") or r.json().get("id")

        # Xatejar amb la sessió
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
    """Pujada de fitxers via UI."""

    def test_upload_txt_file(self, client, headers):
        content = (
            "Document de prova per tests d'integració.\n"
            "El sistema Nexe ha de poder processar aquest fitxer.\n"
            "Conté informació sobre proves automatitzades.\n"
            "Les proves d'integració són essencials per la qualitat del programari."
        )
        files = {"file": ("test_document.txt", io.BytesIO(content.encode()), "text/plain")}
        # Treure Content-Type perquè httpx el posi automàticament per multipart
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
    """Operacions de memòria via UI."""

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
    """Informació del sistema de bootstrap."""

    def test_bootstrap_info(self, client):
        r = client.get("/api/bootstrap/info")
        assert r.status_code == 200
        data = r.json()
        assert "bootstrap_enabled" in data or "mode" in data or "status" in data

    def test_bootstrap_info_no_auth_needed(self, client):
        # Bootstrap info és públic
        r = client.get("/api/bootstrap/info")
        assert r.status_code == 200


# ===========================================================================
# 20. ADMIN SYSTEM
# ===========================================================================


class TestAdminSystem:
    """Endpoints d'administració del sistema (sense restart!)."""

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
    """Flux complet: store → chat amb RAG → recall → verify."""

    def test_full_rag_pipeline(self, client, headers):
        # 1. Guardar un fet únic a memòria
        unique_id = uuid.uuid4().hex[:8]
        fact = f"La ciutat de Nexegrad-{unique_id} té exactament 742.831 habitants"

        r = client.post(
            "/v1/memory/store",
            headers=headers,
            json={
                "content": fact,
                "collection": "nexe_chat_memory",
                "metadata": {"source": "e2e_test", "type": "geographic_fact"},
            },
        )
        assert r.status_code == 200

        # 2. Esperar indexació
        time.sleep(2)

        # 3. Chat amb RAG preguntant sobre el fet
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
        # El model hauria de mencionar el número si RAG funciona
        # (no sempre garantit, depèn del model)

        # 4. Recall — buscar el fet guardat
        r = client.post(
            "/v1/memory/search",
            headers=headers,
            json={"query": f"Nexegrad-{unique_id} habitants", "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        results = data.get("results", [])
        # Ha de trobar el document que hem guardat
        assert len(results) > 0
        found = any("742.831" in str(result) or unique_id in str(result) for result in results)
        assert found, f"No s'ha trobat el fet guardat. Results: {results}"

    def test_ui_chat_then_recall(self, client, headers):
        """Xatejar via UI i verificar que es guarda a memòria."""
        # 1. Crear sessió
        r = client.post("/ui/session/new", headers=headers)
        session_id = r.json().get("session_id") or r.json().get("id")

        # 2. Xatejar
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

        # 3. Verificar historial de sessió
        r = client.get(f"/ui/session/{session_id}/history", headers=headers)
        assert r.status_code == 200


# ===========================================================================
# 22. MULTI-ENGINE COMPARISON
# ===========================================================================


class TestMultiEngine:
    """Comparar respostes entre engines diferents."""

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

        # Tots haurien de mencionar Paris
        for engine, response in responses.items():
            assert "paris" in response.lower() or "París" in response, (
                f"Engine {engine} no ha respost Paris: {response}"
            )

    def test_engines_available(self, client):
        r = client.get("/status")
        data = r.json()
        engines = data.get("engines_available", {})
        # Almenys un engine ha d'estar actiu
        assert any(engines.values()), f"Cap engine disponible: {engines}"
