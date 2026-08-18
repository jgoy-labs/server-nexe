"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: conftest.py
Description: Global Pytest fixtures for all tests.

Lives at the repository root so every test (under ``tests/`` and elsewhere)
shares the same FastAPI app, TestClient and auth fixtures.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time
import types
from dataclasses import dataclass, field
from typing import Any

import pytest


def _install_nexe_flow_mock():
    """Font ÚNICA de veritat del mock de `nexe_flow` (paquet no instal·lat → sempre mockejat).

    Viu al conftest ARREL perquè s'instal·li a sys.modules abans de qualsevol col·lecció en
    QUALSEVOL invocació de pytest (sota tests/, sobre l'arbre font, o la comanda de CI
    `pytest core memory personality plugins`). Abans (E-002) el mock vivia DIVERGENT en 14
    llocs (7 fitxers inline + 4 conftests sota tests/ + 3 conftests morts a l'arbre font), amb
    estratègies barrejades (guard/setdefault/force-replace) i un Node sense validate_inputs al
    sanitizer → hazard d'ordre de col·lecció (OllamaNode.execute crida validate_inputs).

    El contracte és un SUPERCONJUNT que satisfà tots els consumidors del codi font:
      - Node.validate_inputs        → l'invoca OllamaNode.execute (ollama_node.py)
      - NodeMetadata.config_schema   → l'usa RAGSearchNode (rag_search_node.py)
      - NodeInput.json_schema/default
      - NodeOutput.json_schema
    """

    @dataclass
    class NodeMetadata:
        node_type: str = ""
        id: str = ""
        name: str = ""
        version: str = "1.0.0"
        description: str = ""
        category: str = ""
        inputs: Any = field(default_factory=list)
        outputs: Any = field(default_factory=dict)
        icon: str = ""
        color: str = ""
        config_schema: Any = field(default_factory=dict)

    @dataclass
    class NodeInput:
        name: str = ""
        type: str = "string"
        required: bool = False
        description: str = ""
        default: Any = None
        json_schema: Any = field(default_factory=dict)

    @dataclass
    class NodeOutput:
        name: str = ""
        type: str = "string"
        description: str = ""
        json_schema: Any = field(default_factory=dict)

    class Node:
        def __init__(self):
            pass
        def get_metadata(self):
            raise NotImplementedError
        async def execute(self, inputs):
            raise NotImplementedError
        def validate_inputs(self, inputs):
            metadata = self.get_metadata()
            for inp in metadata.inputs:
                if inp.required and inp.name not in inputs:
                    raise ValueError(f"Missing required input: '{inp.name}'")

    nf = types.ModuleType("nexe_flow")
    nfc = types.ModuleType("nexe_flow.core")
    nfcn = types.ModuleType("nexe_flow.core.node")
    nfcn.Node = Node
    nfcn.NodeMetadata = NodeMetadata
    nfcn.NodeInput = NodeInput
    nfcn.NodeOutput = NodeOutput
    nf.core = nfc
    nfc.node = nfcn
    sys.modules["nexe_flow"] = nf
    sys.modules["nexe_flow.core"] = nfc
    sys.modules["nexe_flow.core.node"] = nfcn


_install_nexe_flow_mock()

# Configure environment for tests
os.environ.setdefault("NEXE_ENV", "test")
os.environ.setdefault("NEXE_LOG_LEVEL", "WARNING")
os.environ.setdefault("NEXE_APPROVED_MODULES", "security,rag,memory,ollama_module,mlx_module,llama_cpp_module,web_ui_module")
os.environ.setdefault("NEXE_AUTOSTART_QDRANT", "false")
os.environ.setdefault("NEXE_AUTOSTART_OLLAMA", "false")
os.environ.setdefault("NEXE_AUTO_INGEST_KNOWLEDGE", "false")
os.environ.setdefault("NEXE_QDRANT_HEALTH_TIMEOUT", "0.2")
os.environ.setdefault("NEXE_OLLAMA_HEALTH_TIMEOUT", "0.2")


def _get_test_api_key() -> str:
    """
    Get API key for tests.
    Priority: NEXE_PRIMARY_API_KEY > NEXE_ADMIN_API_KEY > generated
    """
    # Load .env if it exists
    from pathlib import Path
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except Exception:  # nosec B110: dotenv import or read failure — comment below documents fallback to env vars
        pass  # Ignore dotenv errors, rely on env vars

    # Get existing key or generate a new one
    key = os.environ.get("NEXE_PRIMARY_API_KEY") or os.environ.get("NEXE_ADMIN_API_KEY")
    if not key:
        key = f"nexe_test_{secrets.token_hex(16)}"
        os.environ["NEXE_ADMIN_API_KEY"] = key
    return key


_TEST_API_KEY = _get_test_api_key()


@pytest.fixture(scope="session")
def app():
    """
    Fixture that creates the FastAPI app for tests.
    Scope session to reuse between tests.
    """
    from core.server.factory import create_app

    application = create_app(force_reload=True)
    return application


@pytest.fixture(scope="function")
def test_client(app):
    """
    Fixture that creates a TestClient to make HTTP requests.
    """
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def client(test_client):
    """
    Alias for test_client - some tests use 'client' instead of 'test_client'.
    """
    return test_client


@pytest.fixture(scope="session")
def admin_api_key():
    """
    Fixture that returns a valid API key for tests.
    """
    return _TEST_API_KEY


@pytest.fixture(scope="function")
def auth_headers(admin_api_key):
    """
    Fixture that returns authentication headers.
    """
    return {"X-API-Key": admin_api_key}


@pytest.fixture(scope="function")
def mock_ollama(monkeypatch):
    """
    Fixture that mocks Ollama for tests without real server.
    """
    import httpx
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "model": "llama3.2",
        "response": "Mock response for testing",
        "done": True
    }
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def mock_post(*args, **kwargs):
        return mock_response

    # Patch httpx.AsyncClient
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    return mock_client


# ═══════════════════════════════════════════════════════════════════════════
# OLLAMA AUTO-START FIXTURE
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_auth_failure_window():
    """Clear the shared per-IP failed-auth window between tests.

    plugins.security.core.auth_rate_limit keeps a process-wide dict fed by
    BOTH conversation paths (D-I / #883). Without this reset, the hundreds
    of deliberately-unauthenticated requests the suite makes burn the
    20-failures/60s window and unrelated tests start seeing 429s.
    """
    def _clear_windows():
        try:
            from plugins.security.core.auth_rate_limit import auth_failures
            auth_failures.clear()
        except Exception:
            pass
        # Same class of state: the slowapi limiter on /ui/chat (B030,
        # 20/minute) is a process-wide singleton too — the suite's many
        # direct endpoint calls burn its window and unrelated tests 429.
        try:
            from core.dependencies import limiter
            limiter.reset()
            # Each register_chat_routes() re-decorates the same function and
            # slowapi APPENDS its "20/minute" to the same _route_limits key.
            # Tests that build the router repeatedly amplify one request into
            # N hits — the first call after ~20 registrations 429s with an
            # EMPTY window. Production registers once; keep one limit per key.
            for _k, _v in list(limiter._route_limits.items()):
                if len(_v) > 1:
                    limiter._route_limits[_k] = _v[:1]
        except Exception:
            pass

    _clear_windows()
    yield
    _clear_windows()


_ollama_process = None

@pytest.fixture(scope="session", autouse=True)
def ensure_ollama_running():
    """
    Ensure Ollama is running for all tests that need it.

    This fixture:
    1. Checks if Ollama is already running
    2. If not, starts it automatically
    3. Waits for it to be ready (max 15s)
    4. Cleans up on session end

    This fixes tests that fail with "All connection attempts failed"
    when running outside of FastAPI lifespan.
    """
    global _ollama_process
    import httpx

    if os.getenv("NEXE_AUTOSTART_OLLAMA", "true").lower() != "true":
        yield
        return

    ollama_url = "http://localhost:11434"

    # Check if Ollama is already running
    try:
        httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
        print("\n[pytest] Ollama: Already running ✓")
        yield
        return
    except Exception:  # nosec B110: Ollama probe failed → fall through to install check + auto-start
        pass

    # Check if Ollama is installed
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        print("\n[pytest] Ollama: Not installed - tests requiring Ollama will be skipped")
        yield
        return

    # Start Ollama
    print("\n[pytest] Ollama: Starting for tests...")
    try:
        _ollama_process = subprocess.Popen(  # nosec B603 B607: literal `ollama serve` for pytest session fixture; ollama via PATH (test infra)
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait for Ollama to be ready (max 15 seconds)
        for i in range(30):
            time.sleep(0.5)
            try:
                httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
                print(f"[pytest] Ollama: Ready ✓ (took {(i+1)*0.5:.1f}s)")
                break
            except Exception:  # nosec B110: best-effort readiness probe inside retry loop; loop falls through to "failed to start" message
                pass
        else:
            print("[pytest] Ollama: Failed to start within 15s ⚠")

    except Exception as e:
        print(f"[pytest] Ollama: Could not start: {e}")

    yield

    # Cleanup: terminate Ollama if we started it
    if _ollama_process:
        print("\n[pytest] Ollama: Stopping...")
        _ollama_process.terminate()
        try:
            _ollama_process.wait(timeout=5)
            print("[pytest] Ollama: Stopped ✓")
        except subprocess.TimeoutExpired:
            _ollama_process.kill()
            print("[pytest] Ollama: Force killed")


@pytest.fixture(autouse=True)
def _f56_reset_rate_limiter():
    """Reset the slowapi limiter between every test.

    Without this, pytest-randomly could schedule a test that hits a
    rate-limited endpoint after another test in the same session has
    already exhausted the per-IP window, producing a spurious 429 that
    only appeared with certain seeds. Resetting before each function
    (function-scope autouse) keeps the limiter state local to the test.

    Best-effort — older slowapi versions may not expose .reset(); in
    that case the fixture is a no-op rather than blocking the suite.
    """
    try:
        from core.dependencies import limiter
        if hasattr(limiter, "reset"):
            limiter.reset()
    except Exception:  # nosec B110: limiter unavailable in some test paths — non-fatal
        pass
    yield


@pytest.fixture(scope="function")
def ollama_available():
    """
    Fixture that skips the test if Ollama is not available.
    Use this for tests that absolutely require Ollama.

    Usage:
        def test_with_ollama(ollama_available):
            # This test will be skipped if Ollama isn't running
            ...
    """
    import httpx

    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if response.status_code == 200:
            return True
    except Exception:  # nosec B110: Ollama unavailable → pytest.skip below (intentional)
        pass

    pytest.skip("Ollama not available - skipping test")


@pytest.fixture(autouse=True)
def _reset_shared_embedders():
    """Isolate the process-wide fastembed session cache between tests.

    memory.embeddings.shared keeps one TextEmbedding per (model, cache_dir,
    threads) so the sidecar does not pay ~1.4 GB twice for the same ONNX
    session. Like any process-wide singleton it leaks across tests: an instance
    built while `fastembed` was mocked would be handed to a later test that
    expects the real model (seen as IndexError on an empty embed result), and a
    cached instance makes the "model not downloaded" error path unreachable.

    Resetting per test keeps production sharing intact while restoring
    isolation — rather than disabling sharing under pytest, which would leave
    the shipped code path untested.
    """
    from memory.embeddings.shared import reset_shared_embedders

    reset_shared_embedders()
    yield
    reset_shared_embedders()
