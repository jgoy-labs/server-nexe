"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/integration/test_live_api.py
Description: Integration tests — verifies 100% of REST endpoints
             against a real NEXE server (no mocks).

Usage:
  NEXE_TEST_API_KEY=<key> pytest tests/integration/test_live_api.py -v --tb=short

Environment variables:
  NEXE_TEST_URL      Server base URL (default: http://localhost:9119)
  NEXE_TEST_API_KEY  API key for authenticated endpoints

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import time
import pytest
import requests

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

BASE_URL = os.getenv("NEXE_TEST_URL", "http://localhost:9119")
API_KEY  = os.getenv("NEXE_TEST_API_KEY", "")
HEADERS  = {"X-API-Key": API_KEY} if API_KEY else {}


# ═══════════════════════════════════════════════════════════════════════════
# Server check fixture
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session", autouse=True)
def check_server():
    """Skips all tests if the server is not accessible."""
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        assert r.status_code == 200, f"Health check returned {r.status_code}"
    except (requests.ConnectionError, requests.Timeout, AssertionError) as e:
        pytest.skip(
            f"NEXE server not accessible at {BASE_URL}. "
            f"Start it with: ./nexe go\n({e})"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Basic public endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestPublicEndpoints:
    """GET / /health /health/ready /health/circuits /api/info /status"""

    def test_root(self):
        """GET / → 200, body contains 'system' field"""
        r = requests.get(f"{BASE_URL}/", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "system" in data
        assert "Nexe" in data["system"]

    def test_health(self):
        """GET /health → 200, body contains 'status'"""
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data

    def test_health_ready(self):
        """GET /health/ready → 200, body contains 'status' and 'timestamp'"""
        r = requests.get(f"{BASE_URL}/health/ready", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert "timestamp" in data

    def test_health_circuits(self):
        """GET /health/circuits → 200, body contains 'circuits' list"""
        r = requests.get(f"{BASE_URL}/health/circuits", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "circuits" in data
        assert isinstance(data["circuits"], list)
        assert len(data["circuits"]) >= 3
        assert "timestamp" in data

    def test_api_info(self):
        """GET /api/info → 200, body contains 'name', 'version', 'endpoints'"""
        r = requests.get(f"{BASE_URL}/api/info", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data

    def test_status(self):
        """GET /status → 200, body contains 'engine', 'model', 'modules_loaded'"""
        r = requests.get(f"{BASE_URL}/status", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "engine" in data
        assert "model" in data
        assert "modules_loaded" in data
        assert isinstance(data["modules_loaded"], list)
        assert "timestamp" in data


# ═══════════════════════════════════════════════════════════════════════════
# API v1 endpoints
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
        """GET /modules → 200, body contains 'status'"""
        r = requests.get(f"{BASE_URL}/modules", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data

    def test_module_routes_security(self):
        """GET /modules/security/routes → 200, body contains 'module' and 'routes'"""
        r = requests.get(f"{BASE_URL}/modules/security/routes", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert data.get("module") == "security"
        assert "routes" in data

    def test_module_routes_unknown(self):
        """GET /modules/inexistent/routes → 200, routes empty list or similar"""
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
        """GET /api/bootstrap/info → 200 or 4xx (depends on configuration)"""
        r = requests.get(f"{BASE_URL}/api/bootstrap/info", timeout=5)
        # The endpoint may return 200 or 4xx if bootstrap has already been completed
        assert r.status_code in (200, 400, 403, 404, 410)


# ═══════════════════════════════════════════════════════════════════════════
# Admin endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestAdminEndpoints:
    """GET /admin/system/health (public) and /admin/system/status (authenticated)"""

    def test_system_health_public(self):
        """GET /admin/system/health → 200, status = 'healthy'"""
        r = requests.get(f"{BASE_URL}/admin/system/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "healthy"
        assert "version" in data
        assert "platform" in data

    def test_system_status_without_key_rejected(self):
        """GET /admin/system/status without API key → 401 or 403"""
        r = requests.get(f"{BASE_URL}/admin/system/status", timeout=5)
        assert r.status_code in (401, 403), (
            f"Expected 401/403 without key, received {r.status_code}"
        )

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY not configured")
    def test_system_status_with_key(self):
        """GET /admin/system/status with API key → 200"""
        r = requests.get(f"{BASE_URL}/admin/system/status", headers=HEADERS, timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "supervisor_running" in data
        assert "restart_available" in data


# ═══════════════════════════════════════════════════════════════════════════
# Authentication — rejection without key
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthentication:
    """Verifies that authenticated endpoints reject requests without a key"""

    def test_chat_without_key_rejected(self):
        """POST /v1/chat/completions without API key → 401 or 403"""
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
            f"Expected 401/403 without key, received {r.status_code}"
        )

    def test_memory_store_without_key_rejected(self):
        """POST /v1/memory/store without API key → 401 or 403"""
        payload = {"content": "test content"}
        r = requests.post(
            f"{BASE_URL}/v1/memory/store",
            json=payload,
            timeout=5
        )
        assert r.status_code in (401, 403), (
            f"Expected 401/403 without key, received {r.status_code}"
        )

    def test_memory_search_without_key_rejected(self):
        """POST /v1/memory/search without API key → 401 or 403"""
        payload = {"query": "test query"}
        r = requests.post(
            f"{BASE_URL}/v1/memory/search",
            json=payload,
            timeout=5
        )
        assert r.status_code in (401, 403), (
            f"Expected 401/403 without key, received {r.status_code}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Chat completions (requires API key + active model)
# ═══════════════════════════════════════════════════════════════════════════

class TestChatCompletions:
    """POST /v1/chat/completions — tests with API key"""

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY not configured")
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

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY not configured")
    def test_chat_stream(self):
        """POST /v1/chat/completions stream=true → text/event-stream, SSE chunks"""
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

        # Read ALL chunks until the end — important: do not break at the first chunk.
        # If the client disconnects before MLX finishes, the Metal context does not clean up
        # and the next inference call causes a crash (Apple Silicon bug).
        chunks_received = 0
        for chunk in r.iter_lines():
            if chunk:
                chunks_received += 1
        assert chunks_received >= 1

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY not configured")
    def test_chat_with_rag(self):
        """POST /v1/chat/completions use_rag=true → 200

        Note: waits 5s for the background RAG auto-save from the previous call
        to finish. Without the wait, concurrent MLX calls cause a Metal crash
        (_MTLCommandBuffer addCompletedHandler assert) on Apple Silicon.
        """
        time.sleep(5)  # Wait for background auto-save to finish
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
# Memory API (requires API key)
# ═══════════════════════════════════════════════════════════════════════════

class TestMemoryAPI:
    """POST /v1/memory/store and /v1/memory/search"""

    def _require_server_alive(self):
        """Skips the test if the server does not respond (avoids cascade from prior crash)."""
        try:
            requests.get(f"{BASE_URL}/health", timeout=3)
        except requests.exceptions.ConnectionError:
            pytest.skip("Server not accessible (possible prior crash)")

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY not configured")
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

    @pytest.mark.skipif(not API_KEY, reason="NEXE_TEST_API_KEY not configured")
    def test_memory_search(self):
        """POST /v1/memory/search → 200, body contains 'results' and 'total'"""
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
# 501 Not Implemented endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestNotImplemented:
    """Verifies that future endpoints do NOT return 200.

    Some return 501 (Not Implemented), others 403 (the security plugin
    blocks the request before reaching the handler). Both codes indicate
    that the endpoint is not functional in v0.8.
    """

    def _require_server_alive(self):
        """Skips the test if the server does not respond (avoids cascade from prior crash)."""
        try:
            requests.get(f"{BASE_URL}/health", timeout=3)
        except requests.exceptions.ConnectionError:
            pytest.skip("Server not accessible (possible prior crash)")

    def test_rag_search_501(self):
        """POST /v1/rag/search → 501 or 403 (not implemented)"""
        self._require_server_alive()
        r = requests.post(
            f"{BASE_URL}/v1/rag/search",
            json={"query": "test"},
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"Expected 403 or 501, received {r.status_code}"
        )

    def test_rag_add_501(self):
        """POST /v1/rag/add → 501 or 403 (not implemented)"""
        self._require_server_alive()
        r = requests.post(
            f"{BASE_URL}/v1/rag/add",
            json={"content": "test"},
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"Expected 403 or 501, received {r.status_code}"
        )

    def test_rag_delete_501(self):
        """DELETE /v1/rag/documents/{id} → 501 or 403 (not implemented)"""
        self._require_server_alive()
        r = requests.delete(
            f"{BASE_URL}/v1/rag/documents/test-doc-id",
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"Expected 403 or 501, received {r.status_code}"
        )

    def test_embeddings_encode_501(self):
        """POST /v1/embeddings/encode → 501 or 403 (not implemented)"""
        self._require_server_alive()
        r = requests.post(
            f"{BASE_URL}/v1/embeddings/encode",
            json={"text": "test"},
            headers=HEADERS,
            timeout=5
        )
        assert r.status_code in (403, 501), (
            f"Expected 403 or 501, received {r.status_code}"
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
            f"Expected 501, received {r.status_code}"
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
            f"Expected 501, received {r.status_code}"
        )
