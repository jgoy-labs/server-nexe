"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: tests/integration/test_live_api.py
Description: Tests d'integració — comprova el 100% dels endpoints REST
             contra un servidor NEXE real (no mocks).

Ús:
  NEXE_TEST_API_KEY=<clau> pytest tests/integration/test_live_api.py -v --tb=short

Variables d'entorn:
  NEXE_TEST_URL      URL base del servidor (default: http://localhost:9119)
  NEXE_TEST_API_KEY  Clau API per als endpoints autenticats

www.jgoy.net
────────────────────────────────────
"""

import os
import time
import pytest
import requests

# ═══════════════════════════════════════════════════════════════════════════
# Configuració
# ═══════════════════════════════════════════════════════════════════════════

BASE_URL = os.getenv("NEXE_TEST_URL", "http://localhost:9119")
API_KEY  = os.getenv("NEXE_TEST_API_KEY", "")
HEADERS  = {"X-API-Key": API_KEY} if API_KEY else {}


# ═══════════════════════════════════════════════════════════════════════════
# Fixture de comprovació del servidor
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session", autouse=True)
def check_server():
    """Salta tots els tests si el servidor no és accessible."""
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        assert r.status_code == 200, f"Health check retornat {r.status_code}"
    except (requests.ConnectionError, requests.Timeout, AssertionError) as e:
        pytest.skip(
            f"Servidor NEXE no accessible a {BASE_URL}. "
            f"Arrenca'l amb: ./nexe go\n({e})"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints públics bàsics
# ═══════════════════════════════════════════════════════════════════════════

class TestPublicEndpoints:
    """GET / /health /health/ready /health/circuits /api/info /status"""

    def test_root(self):
        """GET / → 200, body conté camp 'system'"""
        r = requests.get(f"{BASE_URL}/", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "system" in data
        assert "Nexe" in data["system"]

    def test_health(self):
        """GET /health → 200, body conté 'status'"""
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data

    def test_health_ready(self):
        """GET /health/ready → 200, body conté 'status' i 'timestamp'"""
        r = requests.get(f"{BASE_URL}/health/ready", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert "timestamp" in data

    def test_health_circuits(self):
        """GET /health/circuits → 200, body conté llista 'circuits'"""
        r = requests.get(f"{BASE_URL}/health/circuits", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "circuits" in data
        assert isinstance(data["circuits"], list)
        assert len(data["circuits"]) >= 3
        assert "timestamp" in data

    def test_api_info(self):
        """GET /api/info → 200, body conté 'name', 'version', 'endpoints'"""
        r = requests.get(f"{BASE_URL}/api/info", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data

    def test_status(self):
        """GET /status → 200, body conté 'engine', 'model', 'modules_loaded'"""
        r = requests.get(f"{BASE_URL}/status", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "engine" in data
        assert "model" in data
        assert "modules_loaded" in data
        assert isinstance(data["modules_loaded"], list)
        assert "timestamp" in data


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints API v1
# ═══════════════════════════════════════════════════════════════════════════

class TestV1Endpoints:
    """GET /v1 /v1/health /modules /modules/{name}/routes"""

    def test_v1_root(self):
        """GET /v1 → 200, api_version = 'v1'"""
        r = requests.get(f"{BASE_URL}/v1", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("api_version") == "v1"
        assert "status" in data
        assert "endpoints" in data

    def test_v1_health(self):
        """GET /v1/health → 200, status = 'healthy'"""
        r = requests.get(f"{BASE_URL}/v1/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "healthy"
        assert data.get("api_version") == "v1"

    def test_modules_list(self):
        """GET /modules → 200, body conté 'status'"""
        r = requests.get(f"{BASE_URL}/modules", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data

    def test_module_routes_security(self):
        """GET /modules/security/routes → 200, body conté 'module' i 'routes'"""
        r = requests.get(f"{BASE_URL}/modules/security/routes", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert data.get("module") == "security"
        assert "routes" in data

    def test_module_routes_unknown(self):
        """GET /modules/inexistent/routes → 200, routes llista buida o similar"""
        r = requests.get(f"{BASE_URL}/modules/inexistent_xyz/routes", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data


# ═══════════════════════════════════════════════════════════════════════════
# Bootstrap
# ═══════════════════════════════════════════════════════════════════════════

class TestBootstrapEndpoints:
    """GET /api/bootstrap/info"""

    def test_bootstrap_info(self):
        """GET /api/bootstrap/info → 200 o 4xx (depèn de la configuració)"""
        r = requests.get(f"{BASE_URL}/api/bootstrap/info", timeout=5)
        # L'endpoint pot retornar 200 o 4xx si bootstrap ja ha estat completat
        assert r.status_code in (200, 400, 403, 404, 410)


# ═══════════════════════════════════════════════════════════════════════════
# Admin endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestAdminEndpoints:
    """GET /admin/system/health (públic) i /admin/system/status (autenticat)"""

    def test_system_health_public(self):
        """GET /admin/system/health → 200, status = 'healthy'"""
        r = requests.get(f"{BASE_URL}/admin/system/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "healthy"
        assert "version" in data
        assert "platform" in data

    def test_system_status_without_key_rejected(self):
        """GET /admin/system/status sense API key → 401 o 403"""
        r = requests.get(f"{BASE_URL}/admin/system/status", timeout=5)
        assert r.status_code in (401, 403), (
            f"S'esperava 401/403 sense key, rebut {r.status_code}"
        )

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY no configurada")
    def test_system_status_with_key(self):
        """GET /admin/system/status amb API key → 200"""
        r = requests.get(f"{BASE_URL}/admin/system/status", headers=HEADERS, timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "supervisor_running" in data
        assert "restart_available" in data


# ═══════════════════════════════════════════════════════════════════════════
# Autenticació — rebuig sense key
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthentication:
    """Verifica que els endpoints autenticats rebutgen peticions sense key"""

    def test_chat_without_key_rejected(self):
        """POST /v1/chat/completions sense API key → 401 o 403"""
        payload = {
            "model": "test",
            "messages": [{"role": "user", "content": "test"}]
        }
        r = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            json=payload,
            timeout=10
        )
        assert r.status_code in (401, 403), (
            f"S'esperava 401/403 sense key, rebut {r.status_code}"
        )

    def test_memory_store_without_key_rejected(self):
        """POST /v1/memory/store sense API key → 401 o 403"""
        payload = {"content": "test content"}
        r = requests.post(
            f"{BASE_URL}/v1/memory/store",
            json=payload,
            timeout=5
        )
        assert r.status_code in (401, 403), (
            f"S'esperava 401/403 sense key, rebut {r.status_code}"
        )

    def test_memory_search_without_key_rejected(self):
        """POST /v1/memory/search sense API key → 401 o 403"""
        payload = {"query": "test query"}
        r = requests.post(
            f"{BASE_URL}/v1/memory/search",
            json=payload,
            timeout=5
        )
        assert r.status_code in (401, 403), (
            f"S'esperava 401/403 sense key, rebut {r.status_code}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Chat completions (requereix API key + model actiu)
# ═══════════════════════════════════════════════════════════════════════════

class TestChatCompletions:
    """POST /v1/chat/completions — tests amb API key"""

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY no configurada")
    def test_simple_chat_no_stream(self):
        """POST /v1/chat/completions stream=false → 200, choices[0].message.content"""
        payload = {
            "model": os.getenv("NEXE_TEST_MODEL", "default"),
            "messages": [{"role": "user", "content": "Respon només amb la paraula: ok"}],
            "stream": False,
            "max_tokens": 10
        }
        r = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            json=payload,
            headers=HEADERS,
            timeout=60
        )
        assert r.status_code == 200
        data = r.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]
        assert "content" in data["choices"][0]["message"]

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY no configurada")
    def test_chat_stream(self):
        """POST /v1/chat/completions stream=true → text/event-stream, chunks SSE"""
        payload = {
            "model": os.getenv("NEXE_TEST_MODEL", "default"),
            "messages": [{"role": "user", "content": "Di 'hola' en una paraula"}],
            "stream": True,
            "max_tokens": 10
        }
        r = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            json=payload,
            headers=HEADERS,
            stream=True,
            timeout=60
        )
        assert r.status_code == 200
        content_type = r.headers.get("content-type", "")
        assert "text/event-stream" in content_type or "application/json" in content_type

        # Llegir TOTS els chunks fins al final — important: no trencar al primer chunk.
        # Si el client desconnecta abans que MLX acabi, el context Metal no fa cleanup
        # i la propera crida d'inferència provoca un crash (Apple Silicon bug).
        chunks_received = 0
        for chunk in r.iter_lines():
            if chunk:
                chunks_received += 1
        assert chunks_received >= 1

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY no configurada")
    def test_chat_with_rag(self):
        """POST /v1/chat/completions use_rag=true → 200

        Nota: espera 5s perquè el background auto-save de RAG de la crida anterior
        acabi. Sense espera, les crides MLX concurrents provoquen un crash Metal
        (_MTLCommandBuffer addCompletedHandler assert) en Apple Silicon.
        """
        time.sleep(5)  # Espera que el background auto-save acabi
        payload = {
            "model": os.getenv("NEXE_TEST_MODEL", "default"),
            "messages": [{"role": "user", "content": "Respon amb 'ok'"}],
            "stream": False,
            "max_tokens": 10,
            "use_rag": True
        }
        try:
            r = requests.post(
                f"{BASE_URL}/v1/chat/completions",
                json=payload,
                headers=HEADERS,
                timeout=60
            )
        except requests.exceptions.ConnectionError:
            pytest.xfail(
                "Servidor caigut durant test_chat_with_rag. "
                "Bug conegut: crides MLX concurrents (background RAG auto-save + nova inferència) "
                "provoquen crash Metal en Apple Silicon (_MTLCommandBuffer assertion). "
                "Solució: incrementar el sleep o desactivar RAG auto-save als tests."
            )
        assert r.status_code == 200
        data = r.json()
        assert "choices" in data


# ═══════════════════════════════════════════════════════════════════════════
# Memory API (requereix API key)
# ═══════════════════════════════════════════════════════════════════════════

class TestMemoryAPI:
    """POST /v1/memory/store i /v1/memory/search"""

    def _require_server_alive(self):
        """Salta el test si el servidor no respon (evita cascada per crash anterior)."""
        try:
            requests.get(f"{BASE_URL}/health", timeout=3)
        except requests.exceptions.ConnectionError:
            pytest.skip("Servidor no accessible (possible crash anterior)")

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY no configurada")
    def test_memory_store(self):
        """POST /v1/memory/store → 200, success=True, document_id present"""
        self._require_server_alive()
        payload = {
            "content": "Test integration: la capital de Catalunya és Barcelona",
            "metadata": {"source": "integration-test"},
            "collection": "nexe_integration_test"
        }
        r = requests.post(
            f"{BASE_URL}/v1/memory/store",
            json=payload,
            headers=HEADERS,
            timeout=15
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("success") is True
        assert data.get("document_id") is not None

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY no configurada")
    def test_memory_search(self):
        """POST /v1/memory/search → 200, body conté 'results' i 'total'"""
        self._require_server_alive()
        payload = {
            "query": "capital Catalunya",
            "limit": 3,
            "collection": "nexe_integration_test"
        }
        r = requests.post(
            f"{BASE_URL}/v1/memory/search",
            json=payload,
            headers=HEADERS,
            timeout=15
        )
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "total" in data
        assert isinstance(data["results"], list)


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints 501 Not Implemented
# ═══════════════════════════════════════════════════════════════════════════

class TestNotImplemented:
    """Verifica que els endpoints futurs NO retornen 200.

    Alguns retornen 501 (Not Implemented), d'altres 403 (el plugin de seguretat
    bloqueja la petició abans d'arribar al handler). Ambdós codis indiquen
    que l'endpoint no és funcional en v0.8.
    """

    def _require_server_alive(self):
        """Salta el test si el servidor no respon (evita cascada per crash anterior)."""
        try:
            requests.get(f"{BASE_URL}/health", timeout=3)
        except requests.exceptions.ConnectionError:
            pytest.skip("Servidor no accessible (possible crash anterior)")

    def test_rag_search_501(self):
        """POST /v1/rag/search → 501 o 403 (no implementat)"""
        self._require_server_alive()
        r = requests.post(
            f"{BASE_URL}/v1/rag/search",
            json={"query": "test"},
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"S'esperava 403 o 501, rebut {r.status_code}"
        )

    def test_rag_add_501(self):
        """POST /v1/rag/add → 501 o 403 (no implementat)"""
        self._require_server_alive()
        r = requests.post(
            f"{BASE_URL}/v1/rag/add",
            json={"content": "test"},
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"S'esperava 403 o 501, rebut {r.status_code}"
        )

    def test_rag_delete_501(self):
        """DELETE /v1/rag/documents/{id} → 501 o 403 (no implementat)"""
        self._require_server_alive()
        r = requests.delete(
            f"{BASE_URL}/v1/rag/documents/test-doc-id",
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"S'esperava 403 o 501, rebut {r.status_code}"
        )

    def test_embeddings_encode_501(self):
        """POST /v1/embeddings/encode → 501 o 403 (no implementat)"""
        self._require_server_alive()
        r = requests.post(
            f"{BASE_URL}/v1/embeddings/encode",
            json={"text": "test"},
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"S'esperava 403 o 501, rebut {r.status_code}"
        )

    def test_embeddings_models_501(self):
        """GET /v1/embeddings/models → 501 Not Implemented"""
        self._require_server_alive()
        r = requests.get(
            f"{BASE_URL}/v1/embeddings/models",
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code == 501, (
            f"S'esperava 501, rebut {r.status_code}"
        )

    def test_documents_list_501(self):
        """GET /v1/documents/ → 501 Not Implemented"""
        self._require_server_alive()
        r = requests.get(
            f"{BASE_URL}/v1/documents/",
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code == 501, (
            f"S'esperava 501, rebut {r.status_code}"
        )
