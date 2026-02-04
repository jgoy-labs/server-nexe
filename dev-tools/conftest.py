"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: conftest.py
Description: Global Pytest fixtures for all tests.

www.jgoy.net
────────────────────────────────────
"""

import os
import pytest
import secrets
import shutil
import subprocess
import time
from typing import Generator

# Configure environment for tests
os.environ.setdefault("NEXE_ENV", "test")
os.environ.setdefault("NEXE_LOG_LEVEL", "WARNING")
os.environ.setdefault("NEXE_APPROVED_MODULES", "security,rag,memory,ollama_module,mlx_module,llama_cpp_module")


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
    except Exception:
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

    ollama_url = "http://localhost:11434"

    # Check if Ollama is already running
    try:
        httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
        print("\n[pytest] Ollama: Already running ✓")
        yield
        return
    except Exception:
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
        _ollama_process = subprocess.Popen(
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
            except Exception:
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
    except Exception:
        pass

    pytest.skip("Ollama not available - skipping test")
