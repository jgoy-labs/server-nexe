"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/tests/test_security_n_series.py
Description: Security tests: production configuration, endpoints, path traversal, sessions.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # server-nexe/


# ═══════════════════════════════════════════════════════════════════════════
# server.toml — reload desactivat, environment=production
# ═══════════════════════════════════════════════════════════════════════════

class TestServerTomlProductionConfig:
    """
    Verifies that the server.toml included in the repository has safe values for
    production. If used without overriding, it must not expose stack traces
    nor enable live-reload.
    """

    def _read_toml(self) -> str:
        toml_path = PROJECT_ROOT / "personality" / "server.toml"
        return toml_path.read_text(encoding="utf-8")

    def test_environment_is_production(self):
        """environment = 'production' (no 'development')."""
        content = self._read_toml()
        assert 'environment = "production"' in content, (
            "server.toml must have environment = \"production\""
        )
        assert 'environment = "development"' not in content

    def test_reload_is_disabled(self):
        """reload = false prevents live-reload in production."""
        content = self._read_toml()
        assert "reload = false" in content, "server.toml must have reload = false"
        assert "reload = true" not in content


# ═══════════════════════════════════════════════════════════════════════════
# system.py — PID and kill commands not exposed in HTTP responses
# ═══════════════════════════════════════════════════════════════════════════

class TestSystemEndpointInfoDisclosure:
    """
    Verifies that the /admin/system/restart and /admin/system/status endpoints
    do not return supervisor_pid, restart_command or shutdown_command.
    Exposing the PID + the exact command to stop it enables lateral movement
    if the API key is stolen.
    """

    def test_restart_response_no_supervisor_pid(self):
        """/restart must not return supervisor_pid to the client."""
        from core.endpoints.system import restart_server
        source = inspect.getsource(restart_server)
        # Get the return section (after background_tasks.add_task)
        return_section = source.split('"status": "restart_initiated"')[1] if '"status": "restart_initiated"' in source else source
        assert '"supervisor_pid"' not in return_section

    def test_status_response_no_supervisor_pid(self, monkeypatch):
        """/status JSON response must not expose supervisor_pid under any key.

        T88 — reforçat: l'original usava inspect.getsource i cercava la cadena
        literal '"supervisor_pid"' al codi font, cosa que passaria verd si el PID
        s'exposés sota una altra clau (p.ex. "pid", "proc_id") o es construís
        dinàmicament.  Aquest test crida l'endpoint real i inspeciona el JSON
        retornat.

        Prova de mutació: afegir supervisor_pid al dict de retorn de
        supervisor_status() → l'assert es posa VERMELL.
        """
        import secrets
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.util import get_remote_address
        from slowapi.middleware import SlowAPIMiddleware
        from slowapi.errors import RateLimitExceeded

        api_key = f"nexe_test_{secrets.token_hex(8)}"
        # Use monkeypatch.setenv so the original value (if any) is restored
        # automatically at teardown — prevents test pollution when .env or
        # a previous conftest has already set NEXE_PRIMARY_API_KEY.
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", api_key)

        # Minimal app — without TrustedHostMiddleware so testclient host does not
        # trigger a 400 before the endpoint logic runs.
        app = FastAPI()
        app.state.config = {}
        app.state.modules = {}
        limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = limiter
        app.add_middleware(SlowAPIMiddleware)
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        from core.endpoints.system import get_router
        app.include_router(get_router())

        with TestClient(app) as client:
            resp = client.get(
                "/admin/system/status",
                headers={"X-API-Key": api_key},
            )

        # No manual cleanup needed: monkeypatch restores the original value
        # (or removes the key if it did not exist before) at teardown.

        # The endpoint always returns 200 (supervisor up or down):
        # supervisor_running=True/False, restart_available=True/False, optional error.
        assert resp.status_code == 200, (
            f"/admin/system/status returned {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert isinstance(data, dict), "Response must be a JSON object"

        # Recursively collect every key in the response (handles nested dicts).
        def _all_keys(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k
                    yield from _all_keys(v)
            elif isinstance(obj, list):
                for item in obj:
                    yield from _all_keys(item)

        all_keys = list(_all_keys(data))

        # Check 1: no key may be exactly "supervisor_pid" (or obvious aliases like
        # "pid", "proc_id").  "pid_file" (the path string) is intentionally allowed
        # as it does not expose a numeric PID — the concern is the process ID integer.
        FORBIDDEN_PID_KEYS = {"supervisor_pid", "pid", "proc_id", "supervisor_pid_value"}
        for key in all_keys:
            assert key not in FORBIDDEN_PID_KEYS, (
                f"/status response must not expose a numeric supervisor PID; "
                f"found forbidden key '{key}' in response: {data}"
            )

        # Check 2: no value in the response is a raw integer that could be a PID
        # (positive int > 1 — boolean True/False are ints in Python but never PIDs).
        def _all_values(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    yield from _all_values(v)
            elif isinstance(obj, list):
                for item in obj:
                    yield from _all_values(item)
            else:
                yield obj

        for val in _all_values(data):
            if isinstance(val, int) and not isinstance(val, bool) and val > 1:
                assert False, (
                    f"/status response must not expose a raw integer PID; "
                    f"found integer value {val!r} in response: {data}"
                )

    def test_status_response_no_restart_command(self):
        """/status must not return the kill -HUP <pid> command."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"restart_command"' not in source
        assert "kill -HUP" not in source

    def test_status_response_no_shutdown_command(self):
        """/status must not return the kill -TERM <pid> command."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"shutdown_command"' not in source
        assert "kill -TERM" not in source

    def test_status_response_keeps_supervisor_running(self):
        """/status keeps supervisor_running (boolean, no PID)."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"supervisor_running"' in source

    def test_status_response_keeps_restart_available(self):
        """/status keeps restart_available (boolean)."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"restart_available"' in source


# ═══════════════════════════════════════════════════════════════════════════
# memory/api/v1.py — str(e) not returned to the HTTP client
# ═══════════════════════════════════════════════════════════════════════════

def _build_minimal_memory_app():
    """Minimal FastAPI app mounting the memory router (no TrustedHostMiddleware).

    Sufficient to exercise the memory/api/v1.py error handlers behaviourally
    (B072 regression guard). Mirrors the inline app built in the T45 store test.
    """
    from fastapi import FastAPI
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded
    import memory.memory.api.v1 as mem_v1_mod

    app = FastAPI()
    app.state.config = {}
    app.state.modules = {}
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(mem_v1_mod.router)
    return app


class TestMemoryAPIErrorDisclosure:
    """
    Verifies that internal exceptions in memory/api/v1.py do not expose
    the internal error (str(e)) in the HTTP response. str(e) may contain the
    internal Qdrant URL, network topology or connection messages.
    """

    def test_store_exception_no_str_e_in_http_detail(self, monkeypatch):
        """memory_store HTTP response must not contain the raw exception text.

        T45 — reforçat: l'original usava inspect.getsource + assert 'str(e)' not in
        source, que passaria VERD si l'excepció es filtrés mitjançant f'{e}' o
        .format(e) (REPRO confirmat a /tmp/fn-theatre/repro_str_e.py).

        Aquest test:
        1. Construeix una app mínima (sense TrustedHostMiddleware) amb el router
           de memòria.
        2. Força get_memory_api() a llançar una excepció amb text únic i
           identificable ("SENTINEL_EXCEPTION_TEXT_T45").
        3. POST a /v1/memory/store.
        4. Asserta que la resposta HTTP 500 NO conté el text del sentinel.

        Prova de mutació: si memory_store filtres str(e) — p.ex. canviant
        "Internal error. Check server logs." per f"Internal error: {e}" —
        la resposta contindria "SENTINEL_EXCEPTION_TEXT_T45" i el test es
        posaria VERMELL.
        """
        import secrets
        from unittest.mock import patch, AsyncMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.util import get_remote_address
        from slowapi.middleware import SlowAPIMiddleware
        from slowapi.errors import RateLimitExceeded

        SENTINEL = "SENTINEL_EXCEPTION_TEXT_T45"

        api_key = f"nexe_test_{secrets.token_hex(8)}"
        # Use monkeypatch.setenv so the original value (if any) is restored
        # automatically at teardown — prevents test pollution when .env or
        # a previous conftest has already set NEXE_PRIMARY_API_KEY.
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", api_key)

        # Minimal app — without TrustedHostMiddleware.
        app = FastAPI()
        app.state.config = {}
        app.state.modules = {}
        limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = limiter
        app.add_middleware(SlowAPIMiddleware)
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        import memory.memory.api.v1 as mem_v1_mod
        # Include the memory router directly (prefix /memory → /memory/store).
        # In production it is nested under /v1 via router_v1, but a minimal app
        # mounting it at /memory is sufficient to exercise the error handler.
        app.include_router(mem_v1_mod.router)

        # Force get_memory_api() to raise an exception with the sentinel string
        # so we can verify it does NOT leak through to the HTTP response.
        _sentinel_exc = RuntimeError(SENTINEL)

        with patch("memory.memory.api.v1.get_memory_api", side_effect=_sentinel_exc):
            with TestClient(app) as client:
                resp = client.post(
                    "/memory/store",
                    json={"content": "test content", "collection": "personal_memory"},
                    headers={"X-API-Key": api_key},
                )
        # No manual cleanup needed: monkeypatch restores the original value
        # (or removes the key if it did not exist before) at teardown.

        # The handler must return 500 with a GENERIC message, not the raw exception.
        assert resp.status_code == 500, (
            f"Expected 500 from memory_store on exception, got {resp.status_code}: {resp.text}"
        )
        response_text = resp.text
        assert SENTINEL not in response_text, (
            f"memory_store leaked the raw exception text into the HTTP response body. "
            f"Found sentinel '{SENTINEL}' in: {response_text!r}. "
            f"The handler must use a generic message, not str(e) or f'{{e}}'."
        )

    def test_search_exception_no_str_e_in_http_detail(self, monkeypatch):
        """memory_search HTTP 500 must not contain the raw exception text.

        B072 — reforçat de teatre a conductual. L'original feia
        source.split("except Exception")[1], que agafava l'except INTERN
        per-col·lecció, no el handler extern: filtrar str(e) al handler real
        hauria passat VERD. Aquest test força get_memory_api() a llançar un
        sentinel i asserta que NO apareix al body 500.

        Prova de mutació: canviar el detail extern per f"Internal error: {e}"
        → el sentinel apareix al body → VERMELL.
        """
        import secrets
        from unittest.mock import patch
        from fastapi.testclient import TestClient

        SENTINEL = "SENTINEL_SEARCH_EXC_B072"
        api_key = f"nexe_test_{secrets.token_hex(8)}"
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", api_key)
        app = _build_minimal_memory_app()

        with patch("memory.memory.api.v1.get_memory_api", side_effect=RuntimeError(SENTINEL)):
            with TestClient(app) as client:
                resp = client.post(
                    "/memory/search",
                    json={"query": "test", "collection": "personal_memory", "limit": 5},
                    headers={"X-API-Key": api_key},
                )
        assert resp.status_code == 500, (
            f"Expected 500 from memory_search on exception, got {resp.status_code}: {resp.text}"
        )
        assert SENTINEL not in resp.text, (
            f"memory_search leaked the raw exception into the HTTP body: {resp.text!r}"
        )

    def test_health_exception_no_str_e_in_response(self):
        """memory_health (unauthenticated) must not contain str(e) on failure.

        B072 — reforçat de teatre a conductual. memory_health retorna 200 amb un
        dict genèric quan falla; el text de l'excepció no hi pot aparèixer.

        Prova de mutació: afegir str(e) al dict de resposta → VERMELL.
        """
        from unittest.mock import patch
        from fastapi.testclient import TestClient

        SENTINEL = "SENTINEL_HEALTH_EXC_B072"
        app = _build_minimal_memory_app()
        with patch("memory.memory.api.v1.get_memory_api", side_effect=RuntimeError(SENTINEL)):
            with TestClient(app) as client:
                resp = client.get("/memory/health")
        assert resp.status_code == 200, (
            f"memory_health should return 200 even when unhealthy, got {resp.status_code}: {resp.text}"
        )
        assert SENTINEL not in resp.text, (
            f"memory_health leaked the raw exception into the response: {resp.text!r}"
        )

    def test_store_uses_generic_error_message(self):
        """memory_store uses a generic message, not the exception detail."""
        from memory.memory.api.v1 import memory_store
        source = inspect.getsource(memory_store)
        assert "Internal error" in source

    def test_search_uses_generic_error_message(self):
        """memory_search uses a generic message, not the exception detail."""
        from memory.memory.api.v1 import memory_search
        source = inspect.getsource(memory_search)
        assert "Internal error" in source

    def test_store_logs_with_exc_info(self):
        """memory_store calls logger.error with exc_info=True to maintain traceability."""
        from memory.memory.api.v1 import memory_store
        source = inspect.getsource(memory_store)
        assert "exc_info=True" in source

    def test_search_logs_with_exc_info(self):
        """memory_search calls logger.error with exc_info=True."""
        from memory.memory.api.v1 import memory_search
        source = inspect.getsource(memory_search)
        assert "exc_info=True" in source


# ═══════════════════════════════════════════════════════════════════════════
# Path traversal /ui/static/{filename}
# ═══════════════════════════════════════════════════════════════════════════

class TestStaticFilePathTraversal:
    """
    Verifies that /ui/static/ is immune to path traversal.
    Without protection, GET /ui/static/../../etc/passwd would read system files
    outside the static/ directory.
    """

    def test_route_uses_path_type_parameter(self):
        """The route uses {filename:path} to capture subpaths containing '/'."""
        from plugins.web_ui_module.api import routes_static
        source = inspect.getsource(routes_static)
        assert '"/static/{filename:path}"' in source, (
            "The route must be /static/{filename:path}, not /static/{filename}"
        )

    def test_serve_static_uses_resolve(self):
        """serve_static calls .resolve() to normalise the path (removes ..)."""
        from plugins.web_ui_module.api import routes_static
        source = inspect.getsource(routes_static)
        assert ".resolve()" in source

    def test_serve_static_checks_containment(self):
        """serve_static checks that the resulting path is inside static_dir."""
        from plugins.web_ui_module.api import routes_static
        source = inspect.getsource(routes_static)
        assert "is_relative_to" in source

    def test_serve_static_returns_403_on_traversal(self, tmp_path):
        """serve_static raises HTTP 403 on path traversal (behavioural, B071).

        L'original (assert "403" in inspect.getsource) era teatre: passava VERD
        encara que la guarda is_relative_to es trenqués. Aquest crida la FUNCIÓ de
        producció serve_static directament amb un filename de traversal, evitant la
        normalització d'httpx (TestClient) que col·lapsa '..' abans del guard.

        Prova de mutació: treure/invertir el check is_relative_to a routes_static.py
        → el traversal ja no dona 403 (proseguiria a 404/serve) → VERMELL.
        """
        import asyncio
        import types
        from fastapi import APIRouter, HTTPException
        from plugins.web_ui_module.api.routes_static import register_static_routes

        router = APIRouter()
        register_static_routes(router, module_ref=types.SimpleNamespace(ui_dir=tmp_path))
        serve_static = next(
            r.endpoint for r in router.routes
            if getattr(r, "path", "").endswith("/static/{filename:path}")
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(serve_static(filename="../../../etc/passwd", i18n=None))
        assert exc.value.status_code == 403, (
            f"Path traversal must yield 403, got {exc.value.status_code}"
        )

    def test_traversal_logic_rejects_dotdot(self):
        """Direct validation: path with .. ends up outside static_dir."""
        static_dir = Path("/app/static").resolve()
        traversal = (Path("/app/static") / "../../etc/passwd").resolve()
        assert not str(traversal).startswith(str(static_dir)), (
            "Path traversal must be detected by startswith()"
        )

    def test_traversal_logic_accepts_valid_path(self):
        """Direct validation: legitimate path inside static_dir is accepted."""
        static_dir = Path("/app/static").resolve()
        valid = (Path("/app/static") / "styles.css").resolve()
        assert str(valid).startswith(str(static_dir))

    def test_traversal_nested_path_rejected(self):
        """Path traversal with an intermediate subdir is equally rejected."""
        static_dir = Path("/app/static").resolve()
        # /app/static/css/../../etc/passwd → /app/etc/passwd → outside static/
        traversal = (Path("/app/static") / "css/../../etc/passwd").resolve()
        assert not str(traversal).startswith(str(static_dir))


# ═══════════════════════════════════════════════════════════════════════════
# Automatic session cleanup (periodic asyncio task)
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionCleanupTask:
    """
    Verifies that the inactive session cleanup has an asyncio task
    that runs automatically every hour. Without this, sessions
    accumulate in RAM and on disk indefinitely.
    """

    def test_cleanup_loop_is_coroutine(self):
        """_session_cleanup_loop is a coroutine (async def)."""
        import asyncio
        from plugins.web_ui_module.api.routes import _session_cleanup_loop
        assert asyncio.iscoroutinefunction(_session_cleanup_loop)

    def test_start_cleanup_task_function_exists(self):
        """start_session_cleanup_task() exists and is callable."""
        from plugins.web_ui_module.api.routes import start_session_cleanup_task
        assert callable(start_session_cleanup_task)

    def test_cleanup_loop_uses_hourly_interval(self):
        """T46: _session_cleanup_loop must pass 3600 to asyncio.sleep at runtime.

        The original test-theatre used inspect.getsource and asserted '3600' appears
        anywhere in the source text — a loop using sleep(60) with '3600' only in a
        comment would still pass GREEN (REPRO confirmed).

        This test intercepts the actual asyncio.sleep() call during execution and
        asserts that the value passed is exactly 3600, not just present as a string.

        Mutation target: change `asyncio.sleep(3600)` to `asyncio.sleep(60)` in
        routes.py → captured_seconds == 60 → assert fails → RED.
        """
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        captured_seconds = []

        async def _fake_sleep(seconds):
            captured_seconds.append(seconds)
            raise StopAsyncIteration("stop after first sleep")

        session_mgr = MagicMock()
        session_mgr.cleanup_inactive.return_value = 0

        # Import here so the patch targets the right namespace.
        import plugins.web_ui_module.api.routes as routes_mod
        from plugins.web_ui_module.api.routes import _session_cleanup_loop

        with patch.object(routes_mod.asyncio, "sleep", _fake_sleep):
            try:
                asyncio.run(_session_cleanup_loop(session_mgr))
            except StopAsyncIteration:
                pass  # expected: loop stopped after first sleep

        assert len(captured_seconds) == 1, (
            "Expected exactly one asyncio.sleep() call before stopping"
        )
        assert captured_seconds[0] == 3600, (
            f"_session_cleanup_loop must sleep 3600s (1 hour); "
            f"got asyncio.sleep({captured_seconds[0]})"
        )

    def test_cleanup_loop_calls_cleanup_inactive(self):
        """The loop calls cleanup_inactive() on the session_manager."""
        from plugins.web_ui_module.api.routes import _session_cleanup_loop
        source = inspect.getsource(_session_cleanup_loop)
        assert "cleanup_inactive" in source

    def test_cleanup_loop_has_max_age_hours(self):
        """cleanup_inactive is called with max_age_hours (session TTL)."""
        from plugins.web_ui_module.api.routes import _session_cleanup_loop
        source = inspect.getsource(_session_cleanup_loop)
        assert "max_age_hours" in source

    def test_lifespan_imports_and_calls_cleanup_task(self):
        """lifespan.py delegates session cleanup startup to _startup_session_cleanup."""
        from core import lifespan
        source = inspect.getsource(lifespan)
        assert "_startup_session_cleanup" in source


# ═══════════════════════════════════════════════════════════════════════════
# Version read from config (not hardcoded)
# ═══════════════════════════════════════════════════════════════════════════

class TestSystemHealthVersion:
    """
    Verifies that /admin/system/health returns the real version from the
    config file, not the incorrect hardcoded string "0.7.1".
    """

    def test_health_no_hardcoded_old_version(self):
        """/health does not have '0.7.1' hardcoded."""
        from core.endpoints.system import system_health
        source = inspect.getsource(system_health)
        assert '"0.7.1"' not in source, (
            "/health must not have version '0.7.1' hardcoded"
        )

    def test_health_reads_from_server_state(self):
        """/health reads the version from get_server_state().config."""
        from core.endpoints.system import system_health
        source = inspect.getsource(system_health)
        assert "get_server_state" in source
        assert ".config" in source

    def test_health_has_fallback_version(self):
        """/health falls back to __version__ (from pyproject.toml) when config is unavailable."""
        from core.endpoints.system import system_health
        source = inspect.getsource(system_health)
        # Fallback is __version__ (core.version reads pyproject.toml, SSOT), not a hardcoded literal
        assert "__version__" in source


# ═══════════════════════════════════════════════════════════════════════════
# Dead code removed from manifest.py (duplicate import and unread variable)
# ═══════════════════════════════════════════════════════════════════════════

class TestManifestDeadCodeRemoved:
    """
    Verifies that 'import logging' does not appear duplicated.
    Verifies that the _initialized variable has been removed.
    """

    def _read_routes(self) -> str:
        path = PROJECT_ROOT / "plugins" / "web_ui_module" / "api" / "routes.py"
        return path.read_text(encoding="utf-8")

    def test_no_duplicate_import_logging(self):
        """'import logging' appears exactly once in routes.py."""
        content = self._read_routes()
        count = content.count("import logging")
        assert count == 1, (
            f"'import logging' appears {count} times in routes.py (expected 1)"
        )

    def test_no_initialized_variable(self):
        """The _initialized variable has been removed (it was never used)."""
        # Check both manifest.py and routes.py
        manifest_path = PROJECT_ROOT / "plugins" / "web_ui_module" / "manifest.py"
        content = manifest_path.read_text(encoding="utf-8")
        assert "_initialized" not in content, (
            "_initialized still exists in manifest.py but is never used"
        )
