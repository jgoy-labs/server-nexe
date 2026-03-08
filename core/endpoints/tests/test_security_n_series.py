"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/endpoints/tests/test_security_n_series.py
Description: Tests de seguretat: configuració producció, endpoints, path traversal, sessions.

www.jgoy.net
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
    Verifica que server.toml inclòs al repositori té valors segurs per
    a producció. Si s'usa sense sobreescriure, no ha d'exposar stack traces
    ni activar live-reload.
    """

    def _read_toml(self) -> str:
        toml_path = PROJECT_ROOT / "personality" / "server.toml"
        return toml_path.read_text(encoding="utf-8")

    def test_environment_is_production(self):
        """environment = 'production' (no 'development')."""
        content = self._read_toml()
        assert 'environment = "production"' in content, (
            "server.toml ha de tenir environment = \"production\""
        )
        assert 'environment = "development"' not in content

    def test_debug_is_disabled(self):
        """debug = false evita exposar stack traces Python a respostes HTTP."""
        content = self._read_toml()
        assert "debug = false" in content, "server.toml ha de tenir debug = false"
        assert "debug = true" not in content

    def test_reload_is_disabled(self):
        """reload = false evita live-reload en producció."""
        content = self._read_toml()
        assert "reload = false" in content, "server.toml ha de tenir reload = false"
        assert "reload = true" not in content


# ═══════════════════════════════════════════════════════════════════════════
# system.py — PID i comandos kill no exposats a respostes HTTP
# ═══════════════════════════════════════════════════════════════════════════

class TestSystemEndpointInfoDisclosure:
    """
    Verifica que els endpoints /admin/system/restart i /admin/system/status
    no retornen supervisor_pid, restart_command ni shutdown_command.
    Exposar el PID + el comandament exacte per aturar-lo facilita lateral
    movement si la clau API és robada.
    """

    def test_restart_response_no_supervisor_pid(self):
        """/restart no ha de retornar supervisor_pid al client."""
        from core.endpoints.system import restart_server
        source = inspect.getsource(restart_server)
        # Obtenir la secció return (after background_tasks.add_task)
        return_section = source.split('"status": "restart_initiated"')[1] if '"status": "restart_initiated"' in source else source
        assert '"supervisor_pid"' not in return_section

    def test_status_response_no_supervisor_pid(self):
        """/status no ha de retornar supervisor_pid."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"supervisor_pid"' not in source

    def test_status_response_no_restart_command(self):
        """/status no ha de retornar la comanda kill -HUP <pid>."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"restart_command"' not in source
        assert "kill -HUP" not in source

    def test_status_response_no_shutdown_command(self):
        """/status no ha de retornar la comanda kill -TERM <pid>."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"shutdown_command"' not in source
        assert "kill -TERM" not in source

    def test_status_response_keeps_supervisor_running(self):
        """/status manté supervisor_running (boolean, sense PID)."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"supervisor_running"' in source

    def test_status_response_keeps_restart_available(self):
        """/status manté restart_available (boolean)."""
        from core.endpoints.system import supervisor_status
        source = inspect.getsource(supervisor_status)
        assert '"restart_available"' in source


# ═══════════════════════════════════════════════════════════════════════════
# memory/api/v1.py — str(e) no retornat al client HTTP
# ═══════════════════════════════════════════════════════════════════════════

class TestMemoryAPIErrorDisclosure:
    """
    Verifica que les excepcions internes de memory/api/v1.py no exposen
    l'error intern (str(e)) a la resposta HTTP. str(e) pot contenir URL Qdrant
    interna, topologia de xarxa o missatges de connexió.
    """

    def test_store_exception_no_str_e_in_http_detail(self):
        """memory_store no inclou str(e) al detail de l'HTTPException."""
        from memory.memory.api.v1 import memory_store
        source = inspect.getsource(memory_store)
        except_section = source.split("except Exception")[1] if "except Exception" in source else ""
        assert "str(e)" not in except_section

    def test_search_exception_no_str_e_in_http_detail(self):
        """memory_search no inclou str(e) al detail de l'HTTPException."""
        from memory.memory.api.v1 import memory_search
        source = inspect.getsource(memory_search)
        except_section = source.split("except Exception")[1] if "except Exception" in source else ""
        assert "str(e)" not in except_section

    def test_health_exception_no_str_e_in_response(self):
        """memory_health (sense auth!) no inclou str(e) a la resposta JSON."""
        from memory.memory.api.v1 import memory_health
        source = inspect.getsource(memory_health)
        except_section = source.split("except Exception")[1] if "except Exception" in source else ""
        assert "str(e)" not in except_section

    def test_store_uses_generic_error_message(self):
        """memory_store usa un missatge genèric, no el detall de l'excepció."""
        from memory.memory.api.v1 import memory_store
        source = inspect.getsource(memory_store)
        assert "Internal error" in source

    def test_search_uses_generic_error_message(self):
        """memory_search usa un missatge genèric, no el detall de l'excepció."""
        from memory.memory.api.v1 import memory_search
        source = inspect.getsource(memory_search)
        assert "Internal error" in source

    def test_store_logs_with_exc_info(self):
        """memory_store fa logger.error amb exc_info=True per mantenir traçabilitat."""
        from memory.memory.api.v1 import memory_store
        source = inspect.getsource(memory_store)
        assert "exc_info=True" in source

    def test_search_logs_with_exc_info(self):
        """memory_search fa logger.error amb exc_info=True."""
        from memory.memory.api.v1 import memory_search
        source = inspect.getsource(memory_search)
        assert "exc_info=True" in source


# ═══════════════════════════════════════════════════════════════════════════
# Path traversal /ui/static/{filename}
# ═══════════════════════════════════════════════════════════════════════════

class TestStaticFilePathTraversal:
    """
    Verifica que /ui/static/ és immune a path traversal.
    Sense protecció, GET /ui/static/../../etc/passwd llegiria fitxers
    del sistema fora del directori static/.
    """

    def test_route_uses_path_type_parameter(self):
        """La ruta usa {filename:path} per capturar subpaths amb '/'."""
        from plugins.web_ui_module import manifest
        source = inspect.getsource(manifest)
        assert '"/static/{filename:path}"' in source, (
            "La ruta ha de ser /static/{filename:path}, no /static/{filename}"
        )

    def test_serve_static_uses_resolve(self):
        """serve_static crida .resolve() per normalitzar el path (elimina ..)."""
        from plugins.web_ui_module.manifest import serve_static
        source = inspect.getsource(serve_static)
        assert ".resolve()" in source

    def test_serve_static_checks_startswith(self):
        """serve_static comprova que el path resultant estigui dins de static_dir."""
        from plugins.web_ui_module.manifest import serve_static
        source = inspect.getsource(serve_static)
        assert "startswith" in source

    def test_serve_static_returns_403_on_traversal(self):
        """El codi retorna HTTP 403 (no 404) si el path és fora del directori."""
        from plugins.web_ui_module.manifest import serve_static
        source = inspect.getsource(serve_static)
        assert "403" in source
        assert "Forbidden" in source

    def test_traversal_logic_rejects_dotdot(self):
        """Validació directa: path amb .. queda fora de static_dir."""
        static_dir = Path("/app/static").resolve()
        traversal = (Path("/app/static") / "../../etc/passwd").resolve()
        assert not str(traversal).startswith(str(static_dir)), (
            "Path traversal ha de ser detectat per startswith()"
        )

    def test_traversal_logic_accepts_valid_path(self):
        """Validació directa: path legítim dins de static_dir és acceptat."""
        static_dir = Path("/app/static").resolve()
        valid = (Path("/app/static") / "styles.css").resolve()
        assert str(valid).startswith(str(static_dir))

    def test_traversal_nested_path_rejected(self):
        """Path traversal amb subdir intermediari és igualment rebutjat."""
        static_dir = Path("/app/static").resolve()
        # /app/static/css/../../etc/passwd → /app/etc/passwd → fora de static/
        traversal = (Path("/app/static") / "css/../../etc/passwd").resolve()
        assert not str(traversal).startswith(str(static_dir))


# ═══════════════════════════════════════════════════════════════════════════
# Session cleanup automàtic (tasca asyncio periòdica)
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionCleanupTask:
    """
    Verifica que el cleanup de sessions inactives té una tasca asyncio
    que s'executa automàticament cada hora. Sense això, les sessions
    s'acumulen en RAM i disc indefinidament.
    """

    def test_cleanup_loop_function_exists(self):
        """_session_cleanup_loop existeix a manifest.py."""
        from plugins.web_ui_module import manifest
        assert hasattr(manifest, '_session_cleanup_loop'), (
            "_session_cleanup_loop no trobat a manifest.py"
        )

    def test_cleanup_loop_is_coroutine(self):
        """_session_cleanup_loop és una coroutine (async def)."""
        import asyncio
        from plugins.web_ui_module.manifest import _session_cleanup_loop
        assert asyncio.iscoroutinefunction(_session_cleanup_loop)

    def test_start_cleanup_task_function_exists(self):
        """start_session_cleanup_task() existeix i és callable."""
        from plugins.web_ui_module.manifest import start_session_cleanup_task
        assert callable(start_session_cleanup_task)

    def test_cleanup_loop_uses_hourly_interval(self):
        """El loop duerme 3600 segons (1 hora) entre execucions."""
        from plugins.web_ui_module.manifest import _session_cleanup_loop
        source = inspect.getsource(_session_cleanup_loop)
        assert "3600" in source, "El loop ha de dormir 3600s (1 hora)"

    def test_cleanup_loop_calls_cleanup_inactive(self):
        """El loop crida cleanup_inactive() del session_manager."""
        from plugins.web_ui_module.manifest import _session_cleanup_loop
        source = inspect.getsource(_session_cleanup_loop)
        assert "cleanup_inactive" in source

    def test_cleanup_loop_has_max_age_hours(self):
        """cleanup_inactive es crida amb max_age_hours (TTL sessions)."""
        from plugins.web_ui_module.manifest import _session_cleanup_loop
        source = inspect.getsource(_session_cleanup_loop)
        assert "max_age_hours" in source

    def test_lifespan_imports_and_calls_cleanup_task(self):
        """lifespan.py crida start_session_cleanup_task() durant el startup."""
        from core import lifespan
        source = inspect.getsource(lifespan)
        assert "start_session_cleanup_task" in source


# ═══════════════════════════════════════════════════════════════════════════
# Versió llegida de config (no hardcoded)
# ═══════════════════════════════════════════════════════════════════════════

class TestSystemHealthVersion:
    """
    Verifica que /admin/system/health retorna la versió real del
    fitxer de config, no la cadena hardcoded "0.7.1" incorrecta.
    """

    def test_health_no_hardcoded_old_version(self):
        """/health no té '0.7.1' hardcoded."""
        from core.endpoints.system import system_health
        source = inspect.getsource(system_health)
        assert '"0.7.1"' not in source, (
            "/health no ha de tenir la versió '0.7.1' hardcoded"
        )

    def test_health_reads_from_server_state(self):
        """/health llegeix la versió de get_server_state().config."""
        from core.endpoints.system import system_health
        source = inspect.getsource(system_health)
        assert "get_server_state" in source
        assert ".config" in source

    def test_health_has_fallback_version(self):
        """/health té una versió de fallback si config no disponible."""
        from core.endpoints.system import system_health
        source = inspect.getsource(system_health)
        # Ha de tenir un fallback (0.8.x)
        assert "0.8" in source


# ═══════════════════════════════════════════════════════════════════════════
# Dead code eliminat de manifest.py (import duplicat i variable no llegida)
# ═══════════════════════════════════════════════════════════════════════════

class TestManifestDeadCodeRemoved:
    """
    Verifica que 'import logging' no apareix duplicat.
    Verifica que la variable _initialized ha estat eliminada.
    """

    def _read_manifest(self) -> str:
        path = PROJECT_ROOT / "plugins" / "web_ui_module" / "manifest.py"
        return path.read_text(encoding="utf-8")

    def test_no_duplicate_import_logging(self):
        """'import logging' apareix exactament una vegada."""
        content = self._read_manifest()
        count = content.count("import logging")
        assert count == 1, (
            f"'import logging' apareix {count} vegades a manifest.py (s'espera 1)"
        )

    def test_no_initialized_variable(self):
        """La variable _initialized ha estat eliminada (mai s'usava)."""
        content = self._read_manifest()
        assert "_initialized" not in content, (
            "_initialized encara existeix a manifest.py però mai s'usa"
        )
