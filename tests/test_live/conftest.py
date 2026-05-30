"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/conftest.py
Description: Fixtures for live server tests (test_live marker).
             Auto-starts the server if not already running.
             Reuses an external server (Tauri sidecar, dev manual) if found.

Usage:
  pytest tests/test_live/ -m test_live          # auto-start
  NEXE_TEST_URL=http://localhost:9119 pytest ... # reuse external
  python dev-tools/run_live.py                  # via orchestrator

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Generator

import pytest
import httpx

# ─── Paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# ─── Config ───────────────────────────────────────────────────────────────────

def _load_dotenv(path: Path) -> dict[str, str]:
    """Parse .env file into a dict without importing dotenv."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip().strip('"').strip("'")
    return result


_dotenv = _load_dotenv(ENV_FILE)

NEXE_TEST_URL = os.getenv("NEXE_TEST_URL", "http://localhost:9119")
NEXE_API_KEY = (
    os.getenv("NEXE_TEST_API_KEY")
    or os.getenv("NEXE_PRIMARY_API_KEY")
    or _dotenv.get("NEXE_PRIMARY_API_KEY", "")
)
STARTUP_TIMEOUT = int(os.getenv("NEXE_TEST_STARTUP_TIMEOUT", "45"))

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_up(url: str, timeout: float = 2.0) -> bool:
    """Return True if the server responds to /health."""
    try:
        r = httpx.get(f"{url}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _wait_ready(url: str, timeout: int = STARTUP_TIMEOUT) -> None:
    """Poll /health until the server is ready or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_up(url, timeout=1.0):
            return
        time.sleep(0.5)
    raise TimeoutError(
        f"Nexe server did not start within {timeout}s at {url}. "
        "Check server logs for errors."
    )


def _ensure_onboarding_state(data_dir: Path) -> None:
    """Create a minimal onboarding.json so the server exits MINIMAL MODE."""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    state_file = data_dir / "onboarding.json"
    if state_file.exists():
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    state_file.write_text(_json.dumps({
        "version": 2,
        "engine": "ollama",
        "model_id": "qwen3.5:4b",
        "model_path": "qwen3.5:4b",
        "completed_at": _dt.now(_tz.utc).isoformat(timespec="seconds"),
        "has_token": False,
    }), encoding="utf-8")


def _build_env() -> dict[str, str]:
    """Merge process env with .env file values (process env wins).

    Runs server in standalone mode with a synthetic onboarding state so all
    modules load normally (not MINIMAL MODE).
    """
    merged = {**_dotenv, **os.environ}
    merged["NEXE_NO_TRAY"] = "1"
    merged["NEXE_ENV"] = merged.get("NEXE_ENV", "test")
    merged["NEXE_LOG_LEVEL"] = merged.get("NEXE_LOG_LEVEL", "WARNING")
    merged["NEXE_APPROVED_MODULES"] = merged.get(
        "NEXE_APPROVED_MODULES",
        "security,memory,rag,embeddings,mlx_module,llama_cpp_module,ollama_module,web_ui_module",
    )
    merged.pop("NEXE_SIDECAR", None)
    data_dir = Path(merged.get("NEXE_DATA_DIR", str(PROJECT_ROOT / ".test_data")))
    _ensure_onboarding_state(data_dir)
    merged["NEXE_DATA_DIR"] = str(data_dir)
    return merged


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def nexe_server() -> Generator[str, None, None]:
    """
    Provide the live server URL for test_live tests.

    - If a server is already running at NEXE_TEST_URL → reuse it (no teardown).
    - Otherwise → start the server via subprocess, yield URL, stop on teardown.

    Compatible with Tauri sidecar: set NEXE_TEST_URL env var before running.
    """
    if _is_up(NEXE_TEST_URL):
        yield NEXE_TEST_URL
        return  # external server — do not terminate

    if not ENV_FILE.exists():
        pytest.skip(
            f"No .env file found at {ENV_FILE} and no server running at "
            f"{NEXE_TEST_URL}. Either start the server manually (`./nexe go`) "
            "or create a .env file."
        )

    # Redirect the server's stdout/stderr to a file, NOT subprocess.PIPE.
    # With PIPE nobody drains the buffer during the session, so once the OS
    # pipe (~64KB) fills with accumulated logs the server blocks on its next
    # write() — the in-flight request hangs forever (GPU idle, client times
    # out). A file sink never blocks the writer and keeps logs for debugging.
    server_log_path = PROJECT_ROOT / "dev-tools" / "reports" / "live_server.log"
    server_log_path.parent.mkdir(parents=True, exist_ok=True)
    server_log = server_log_path.open("w", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "core.app"],
        cwd=str(PROJECT_ROOT),
        env=_build_env(),
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_ready(NEXE_TEST_URL, timeout=STARTUP_TIMEOUT)
    except TimeoutError as exc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        server_log.close()
        pytest.skip(str(exc))

    yield NEXE_TEST_URL

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    server_log.close()


@pytest.fixture(scope="session")
def api_key() -> str:
    """API key for authenticated endpoints."""
    if not NEXE_API_KEY:
        pytest.skip(
            "No API key found. Set NEXE_TEST_API_KEY, NEXE_PRIMARY_API_KEY, "
            "or define NEXE_PRIMARY_API_KEY in .env"
        )
    return NEXE_API_KEY


@pytest.fixture(scope="session")
def auth_headers(api_key: str) -> dict[str, str]:
    """Headers dict with API key."""
    return {"X-API-Key": api_key}


@pytest.fixture(scope="session")
def client(nexe_server: str) -> httpx.Client:  # noqa: F811
    """Synchronous httpx client pointed at the live server."""
    with httpx.Client(base_url=nexe_server, timeout=60.0) as c:
        yield c


# ─── Rate-limit guard ─────────────────────────────────────────────────────────

_INTER_TEST_DELAY = float(os.getenv("NEXE_TEST_DELAY", "1.5"))
_SLOW_TEST_DELAY = float(os.getenv("NEXE_TEST_SLOW_DELAY", "10.0"))


@pytest.fixture(autouse=True, scope="function")
def _rate_limit_guard(request: pytest.FixtureRequest) -> "Generator[None, None, None]":
    """
    Pause between tests to avoid hitting the server's rate limiter or saturating
    Ollama. Default 1.5s normal / 10s after a `slow`-marked test (Bug #4
    2026-05-21: Ollama calls take ~8-10s and accumulate when chained, causing
    httpcore timeouts on later non-LLM tests). Override with
    `NEXE_TEST_DELAY=0` / `NEXE_TEST_SLOW_DELAY=0` to disable.
    """
    yield
    if request.node.get_closest_marker("slow"):
        delay = _SLOW_TEST_DELAY
    else:
        delay = _INTER_TEST_DELAY
    if delay > 0:
        time.sleep(delay)


# ─── Test ordering — slow tests last ──────────────────────────────────────────

def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Schedule slow (Ollama-heavy) tests after the fast ones.

    Bug #4 (2026-05-21): the prompt-injection + chat-Ollama tests each take
    ~8-10s and accumulate server load. When they run before non-LLM tests
    (alphabetical default: test_security → test_sessions), the later tests
    hit httpcore timeouts because Ollama is still busy. Reordering keeps
    fast tests first so the server is fresh when they run; slow tests then
    cluster at the end where their delay only affects themselves.

    Stable within each group: keeps the original collection order, only
    splits by `slow` marker. xfail/skip items keep their position.
    """
    slow = [it for it in items if it.get_closest_marker("slow")]
    fast = [it for it in items if not it.get_closest_marker("slow")]
    items[:] = fast + slow


# ─── Backend detection ────────────────────────────────────────────────────────

def _resolve_ollama_host() -> str:
    """Resolve the Ollama host the same way the server does.

    ``OLLAMA_HOST=0.0.0.0`` (a common bind-all setting) is not a connectable
    client URL — a raw ``os.getenv`` would hand ``"0.0.0.0"`` to httpx, which
    raises *missing protocol* and silently skips every live chat test. Reuse the
    canonical ``resolve_base_url()`` so the fixtures see the exact host the
    production Ollama client connects to. Falls back to the previous behaviour
    if the plugin module is unavailable (never worse than before).
    """
    try:
        from plugins.ollama_module.core.client import resolve_base_url

        return resolve_base_url()
    except Exception:
        return os.getenv("OLLAMA_HOST", "http://localhost:11434")


OLLAMA_HOST = _resolve_ollama_host()

# Models >32B skipped in automated tests (too slow; run manually if needed)
_MAX_AUTO_MODEL_GB = 32

# Size hints by name fragment (GB) — used to skip very large models
_MODEL_SIZE_HINTS: dict[str, float] = {
    "122b": 75.0,
    "70b": 40.0,
    "65b": 38.0,
    "coder-next": 52.0,
}


def _model_size_gb(name: str) -> float:
    """Heuristic: estimate model size from name. Returns 0 if unknown."""
    lower = name.lower()
    for fragment, gb in _MODEL_SIZE_HINTS.items():
        if fragment in lower:
            return gb
    return 0.0


@pytest.fixture(scope="session")
def ollama_models(nexe_server: str) -> list[str]:  # noqa: ARG001
    """List of Ollama model names available locally. Empty if Ollama is down."""
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


@pytest.fixture(scope="session")
def smallest_ollama_model(ollama_models: list[str]) -> str:
    """Smallest available Ollama model (for fast tests)."""
    # gemma4:e4b is a VL model — fails MLX streaming path (needs PyTorch bundle)
    # Prefer pure-text models for automated tests
    for preferred in ("qwen3.5:4b", "qwen3.5:9b", "qwen3:4b", "llama3.2:3b",
                      "mistral-nemo:12b", "gpt-oss:20b", "gemma3:4b"):
        if any(preferred in m for m in ollama_models):
            return preferred
    if ollama_models:
        return ollama_models[0]
    pytest.skip("No Ollama models available — start Ollama and pull a model first")
    return ""  # unreachable, satisfies type checker


@pytest.fixture(scope="session")
def backends_info(client: httpx.Client, auth_headers: dict[str, str]) -> dict:
    """Raw backends response from /ui/backends."""
    try:
        r = client.get("/ui/backends", headers=auth_headers, timeout=10.0)
        if r.status_code == 200:
            return r.json() if isinstance(r.json(), dict) else {"backends": r.json()}
    except Exception:
        pass
    return {}


def _backend_is_available(info: dict, names: tuple[str, ...]) -> bool:
    # Match on the canonical backend id (e.g. "mlx", "llamacpp"), case-insensitive.
    # /ui/backends returns {"id": "mlx", "name": "MLX", ...}; comparing the display
    # "name" missed every backend (case + id/name mismatch).
    backends = info.get("backends", info) if isinstance(info, dict) else info
    if not isinstance(backends, list):
        return False
    wanted = {n.lower() for n in names}
    for b in backends:
        if isinstance(b, dict):
            ident = str(b.get("id") or b.get("name") or "").lower()
            available = b.get("available", True)
        else:
            ident = str(b).lower()
            available = True
        if ident in wanted and available:
            return True
    return False


@pytest.fixture(scope="session")
def mlx_available(backends_info: dict) -> bool:
    """True if the MLX backend is loaded and available."""
    return _backend_is_available(backends_info, ("mlx",))


@pytest.fixture(scope="session")
def llama_cpp_available(backends_info: dict) -> bool:
    """True if the llama.cpp backend is loaded and available."""
    return _backend_is_available(backends_info, ("llamacpp", "llama_cpp", "llama-cpp"))
