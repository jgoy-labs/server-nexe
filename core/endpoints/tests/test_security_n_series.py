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
# server.toml — debug/reload desactivats, environment=production
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

    def test_debug_is_disabled(self):
        """debug = false prevents exposing Python stack traces in HTTP responses."""
        content = self._read_toml()
        assert "debug = false" in content, "server.toml must have debug = false"
        assert "debug = true" not in content

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

    def test_status_response_no_supervisor_pid(self):
        """/status must not return supervisor_pid."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"supervisor_pid"' not in source

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

class TestMemoryAPIErrorDisclosure:
    """
    Verifies that internal exceptions in memory/api/v1.py do not expose
    the internal error (str(e)) in the HTTP response. str(e) may contain the
    internal Qdrant URL, network topology or connection messages.
    """

    def test_store_exception_no_str_e_in_http_detail(self):
        """memory_store does not include str(e) in the HTTPException detail."""
        from memory.memory.api.v1 import memory_store
        source = inspect.getsource(memory_store)
        except_section = source.split("except Exception")[1] if "except Exception" in source else ""
        assert "str(e)" not in except_section

    def test_search_exception_no_str_e_in_http_detail(self):
        """memory_search does not include str(e) in the HTTPException detail."""
        from memory.memory.api.v1 import memory_search
        source = inspect.getsource(memory_search)
        except_section = source.split("except Exception")[1] if "except Exception" in source else ""
        assert "str(e)" not in except_section

    def test_health_exception_no_str_e_in_response(self):
        """memory_health (no auth!) does not include str(e) in the JSON response."""
        from memory.memory.api.v1 import memory_health
        source = inspect.getsource(memory_health)
        except_section = source.split("except Exception")[1] if "except Exception" in source else ""
        assert "str(e)" not in except_section

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

    def test_serve_static_checks_startswith(self):
        """serve_static checks that the resulting path is inside static_dir."""
        from plugins.web_ui_module.api import routes_static
        source = inspect.getsource(routes_static)
        assert "startswith" in source

    def test_serve_static_returns_403_on_traversal(self):
        """The code returns HTTP 403 (not 404) if the path is outside the directory."""
        from plugins.web_ui_module.api import routes_static
        source = inspect.getsource(routes_static)
        assert "403" in source
        assert "forbidden" in source.lower()

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

    def test_cleanup_loop_function_exists(self):
        """_session_cleanup_loop exists in api/routes.py."""
        from plugins.web_ui_module.api import routes
        assert hasattr(routes, '_session_cleanup_loop'), (
            "_session_cleanup_loop not found in api/routes.py"
        )

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
        """The loop sleeps 3600 seconds (1 hour) between runs."""
        from plugins.web_ui_module.api.routes import _session_cleanup_loop
        source = inspect.getsource(_session_cleanup_loop)
        assert "3600" in source, "The loop must sleep 3600s (1 hour)"

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
        """lifespan.py calls start_session_cleanup_task() during startup."""
        from core import lifespan
        source = inspect.getsource(lifespan)
        assert "start_session_cleanup_task" in source


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
        """/health has a fallback version if config is not available."""
        from core.endpoints.system import system_health
        source = inspect.getsource(system_health)
        # Must have a fallback (0.9.x)
        assert "0.9" in source


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
