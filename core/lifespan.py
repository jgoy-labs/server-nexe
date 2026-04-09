"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan.py
Description: FastAPI lifespan management (startup/shutdown). Orchestrator — delegates to submodules.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json as _json
import logging
import os
import warnings as _warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

# ═══════════════════════════════════════════════════════════════════════════
# Environment setup — ha d'anar ABANS de qualsevol import que pogui carregar
# HuggingFace/sentence-transformers transitivament. Mouríem encara mes amunt
# pero os/warnings estan dalt de tot.
# ═══════════════════════════════════════════════════════════════════════════

# Force offline mode for HuggingFace — server must work without internet
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Bug 14 (2026-04-06) — silenciar tqdm de sentence-transformers en runtime del
# servidor. Les barres `Batches: 0%|...` es barrejaven amb els logs del servidor
# i creaven línies corruptes. Aplicat NOMÉS en runtime servidor (no afecta la
# descàrrega inicial de models, que es fa via installer/setup_models.py).
os.environ.setdefault("TQDM_DISABLE", "1")

# Bug 6 (2026-04-06) — silenciar warnings sorollosos en carregar embedders.
# `paraphrase-multilingual-mpnet-base-v2` emet warnings UserWarning per
# `position_ids UNEXPECTED` i `Some weights of...` que no aporten res.
# Dev D (Consultor passada 1): moguts ABANS dels imports `from .lifespan_modules
# import ...` per assegurar que s'apliquen encara que algun import transitiu
# carregui sentence_transformers en temps d'import.
_warnings.filterwarnings("ignore", message=".*position_ids.*", category=UserWarning)
_warnings.filterwarnings("ignore", message=".*Some weights of.*", category=UserWarning)
_warnings.filterwarnings("ignore", category=UserWarning, module="sentence_transformers")

from fastapi import FastAPI

from personality.integration import APIIntegrator
from .config import load_config
from .lifespan_services import (
    _auto_start_services,
    OLLAMA_HEALTH_TIMEOUT,
    OLLAMA_UNLOAD_TIMEOUT,
)
from .lifespan_tokens import (
    setup_bootstrap_tokens,
    start_bootstrap_token_renewal,
    stop_bootstrap_token_renewal,
)
from .lifespan_ollama import cleanup_ollama_startup, cleanup_ollama_shutdown
from .lifespan_modules import (
    load_memory_modules,
    initialize_plugin_modules,
    auto_ingest_knowledge,
    start_memory_service_v1,
)

logger = logging.getLogger(__name__)


from core.server.helpers import translate as _translate

# Timeout per fase d'arrencada (B09). Configurable via NEXE_STARTUP_TIMEOUT.
STARTUP_TIMEOUT = float(os.getenv("NEXE_STARTUP_TIMEOUT", "30"))

# Path canònic del PID file (B06, B10, B15).
_PID_SUBPATH = Path("storage") / "run" / "server.pid"


def _write_pid_file(project_root: Path, port: int) -> bool:
  """Escriu el PID file de forma atòmica (O_CREAT|O_EXCL). B06, B07, B10.

  Retorna True si l'ha adquirit, False si un servidor viu ja el té.
  Fitxers estantis (PID mort o corrupte) s'eliminen automàticament.
  """
  pid_path = project_root / _PID_SUBPATH
  pid_path.parent.mkdir(parents=True, exist_ok=True)
  content = _json.dumps({
    "pid": os.getpid(),
    "port": port,
    "started": datetime.now(timezone.utc).isoformat(),
  }).encode()

  for _attempt in range(2):
    try:
      fd = os.open(str(pid_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
      try:
        os.write(fd, content)
      finally:
        os.close(fd)
      logger.debug("PID file written: %s (PID %s)", pid_path, os.getpid())
      return True
    except FileExistsError:
      try:
        raw = pid_path.read_text()
        if not raw.strip():
          # Buit: un altre procés acaba de crear-lo amb O_EXCL i encara escriu.
          # Tractem com a locked — NO eliminem.
          logger.debug("PID file exists but empty — another process is acquiring it.")
          return False
        data = _json.loads(raw)
        existing_pid = int(data["pid"])
        existing_port = data.get("port", "?")
        try:
          os.kill(existing_pid, 0)  # liveness probe
          logger.error(
            "Server already running. PID: %s on port %s. "
            "Use './nexe stop' to stop it.",
            existing_pid, existing_port,
          )
          return False
        except (ProcessLookupError, OSError):
          logger.warning("Stale PID file (PID %s dead), removing.", existing_pid)
          try:
            pid_path.unlink()
          except OSError:
            pass
      except (ValueError, KeyError, OSError, Exception) as exc:
        logger.warning("Corrupt PID file (%s), removing.", exc)
        try:
          pid_path.unlink()
        except OSError:
          pass

  logger.error("Could not acquire PID file after retries: %s", pid_path)
  return False


def _remove_pid_file(project_root: Path) -> None:
  """Elimina el PID file si existeix i pertany a aquest procés. B10.

  Segur de cridar sempre al finally — mai llança excepcions.
  """
  if project_root is None:
    return
  pid_path = project_root / _PID_SUBPATH
  try:
    if not pid_path.exists():
      return
    try:
      data = _json.loads(pid_path.read_text())
      existing_pid = int(data["pid"])
    except Exception:
      existing_pid = None
    if existing_pid is None or existing_pid == os.getpid():
      pid_path.unlink()
      logger.debug("PID file removed: %s", pid_path)
  except OSError as exc:
    logger.debug("Could not remove PID file %s: %s", pid_path, exc)


class ServerState:
  """Holds server global state"""
  def __init__(self):
    self.config: Dict[str, Any] = {}
    self.api_integrator: APIIntegrator = None
    self.project_root: Path = None
    self.i18n = None
    self.module_manager = None
    self.registry = None
    self.ollama_process = None
    self.qdrant_available: bool = False
    self.crypto_provider = None

server_state = ServerState()

@asynccontextmanager
async def lifespan(app: FastAPI):
  """
  Application lifespan management

  Handles:
  - Configuration loading
  - APIIntegrator initialization
  - Graceful shutdown
  """
  try:
    logger.info("=" * 70)
    logger.info("LIFESPAN STARTUP TRIGGERED")
    logger.info("=" * 70)

    msg = _translate(server_state.i18n, "core.server.banner",
      "Nexe 0.9 - Modular AI System")
    logger.info(msg)

    reload_trigger = server_state.project_root / ".nexe_reload_trigger.py"
    if reload_trigger.exists():
      try:
        reload_trigger.unlink()
        logger.debug("Cleaned up reload trigger: %s", reload_trigger)
      except Exception as e:
        logger.warning("Could not delete reload trigger: %s", e)

    msg = _translate(server_state.i18n, "core.server.project_root",
      "Project root: {path}",
      path=str(server_state.project_root))
    logger.info(msg)

    server_state.config = load_config(server_state.project_root, server_state.i18n)
    app.state.config = server_state.config  # Sync: elimina el desync entre server_state i app.state

    # === PID FILE (B06, B07, B10) ===
    # Escriu el PID de forma atòmica al startup. Avorta si un servidor viu
    # ja el té (single-instance guard). El finally sempre el neteja (B10).
    from core.config import DEFAULT_HOST, DEFAULT_PORT
    _srv_startup_cfg = server_state.config.get('core', {}).get('server', {})
    _startup_port = _srv_startup_cfg.get('port', DEFAULT_PORT)
    if server_state.project_root and not _write_pid_file(server_state.project_root, _startup_port):
      raise RuntimeError(
        f"Server already running on port {_startup_port}. "
        "Use './nexe stop' to stop the existing instance."
      )

    # === ENCRYPTION AT REST (opt-in) ===
    try:
      from core.crypto import CryptoProvider, check_encryption_status

      encryption_config = server_state.config.get('security', {}).get('encryption', {})
      crypto_enabled = encryption_config.get('enabled', False)

      # Env var override (NEXE_ENCRYPTION_ENABLED=true)
      env_crypto = os.environ.get('NEXE_ENCRYPTION_ENABLED', '').lower()
      if env_crypto == 'true':
        crypto_enabled = True
      elif env_crypto == 'false':
        crypto_enabled = False

      if crypto_enabled:
        from memory.memory.engines.persistence import SQLCIPHER_AVAILABLE
        if not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                "Encryption at rest requested (NEXE_ENCRYPTION_ENABLED=true) "
                "but sqlcipher3 is not installed. The server will NOT start to avoid "
                "a false sense of security. Either:\n"
                "  (1) Install sqlcipher3: pip install sqlcipher3-binary\n"
                "  (2) Disable encryption: NEXE_ENCRYPTION_ENABLED=false"
            )
        server_state.crypto_provider = CryptoProvider()
        logger.info("Encryption at rest: ENABLED (AES-256-GCM)")
      else:
        logger.info("Encryption at rest: disabled")

      # Always check for unencrypted data
      warn_unencrypted = encryption_config.get('warn_unencrypted', True)
      if warn_unencrypted:
        storage_path = server_state.project_root / "storage" if server_state.project_root else None
        check_encryption_status(storage_path)

    except Exception as e:
      if isinstance(e, RuntimeError):
          raise  # Fail-closed: SQLCIPHER_AVAILABLE check must propagate, not be swallowed
      logger.warning("Encryption init failed (non-fatal): %s", e)
      server_state.crypto_provider = None

    # Init Qdrant singleton pool
    from core.qdrant_pool import get_qdrant_client, close_qdrant_client
    qdrant_url = os.environ.get("NEXE_QDRANT_URL")
    qdrant_path = os.environ.get("NEXE_QDRANT_PATH", "storage/vectors")
    get_qdrant_client(url=qdrant_url, path=qdrant_path if not qdrant_url else None)

    # Auto-start services (Qdrant, Ollama) if not running
    # B09: timeout per evitar penjades indefinides si Qdrant/Ollama no arranquen
    try:
      await asyncio.wait_for(
        _auto_start_services(server_state.config, server_state.project_root, server_state),
        timeout=STARTUP_TIMEOUT,
      )
    except asyncio.TimeoutError:
      logger.error(
        "Services startup timed out after %ss (NEXE_STARTUP_TIMEOUT). "
        "Check Qdrant and Ollama availability.",
        STARTUP_TIMEOUT,
      )
      raise RuntimeError(f"Services startup timed out after {STARTUP_TIMEOUT}s")

    server_config = server_state.config.get('core', {}).get('server', {})
    host = server_config.get('host', DEFAULT_HOST)
    port = server_config.get('port', DEFAULT_PORT)

    msg = _translate(server_state.i18n, "core.server.binding_server",
      "Server ready at {host}:{port}",
      host=host, port=port)
    logger.info(msg)

    msg = _translate(server_state.i18n, "core.server.all_systems_go",
      "All systems operational - Nexe 0.9 ready!")
    logger.info(msg)

    server_state.api_integrator = APIIntegrator(app, server_state.i18n)

    msg = _translate(server_state.i18n, "core.server.api_integrator_ready",
      "API Integrator ready")
    logger.info(msg)

    # Cleanup Ollama models from previous sessions
    await cleanup_ollama_startup(server_state, _translate, OLLAMA_HEALTH_TIMEOUT, OLLAMA_UNLOAD_TIMEOUT)

    try:
      if server_state.module_manager:
        server_state.registry = server_state.module_manager.registry
        msg = _translate(server_state.i18n, "core.server.module_manager_ready", "ModuleManager already initialized")
        logger.info(msg)

        discovered = await server_state.module_manager.discover_modules()
        total_modules = list(server_state.module_manager._modules.keys())

        # Bug 20 fix — startup summary: si el discover ha detectat cicles
        # de dependencies, els mostrem amb prefix [WARN] perque no quedin
        # amagats (abans els modules s'inhabilitaven en silenci).
        try:
          cycle_warnings = server_state.module_manager.get_cycle_warnings()
        except Exception:
          cycle_warnings = []
        for cycle_chain in cycle_warnings:
          logger.warning(
            "[WARN] Module dependency cycle: %s", cycle_chain
          )

        if total_modules:
          msg = _translate(server_state.i18n, "core.server.modules_loaded",
            "Modules loaded: {count} ({modules})",
            count=len(total_modules), modules=', '.join(total_modules))
          logger.info(msg)
        else:
          msg = _translate(server_state.i18n, "core.server.no_modules_loaded", "No modules loaded")
          logger.warning(msg)

        if discovered:
          msg = _translate(server_state.i18n, "core.server.new_modules_discovered",
            "Discovered {count} new modules: {modules}",
            count=len(discovered), modules=', '.join(discovered))
          logger.info(msg)
        else:
          msg = _translate(server_state.i18n, "core.server.no_new_modules",
            "No new modules discovered in this cycle")
          logger.debug(msg)

      else:
        msg = _translate(server_state.i18n, "core.server.module_manager_unavailable", "ModuleManager not available")
        logger.warning(msg)

    except Exception as e:
      msg = _translate(server_state.i18n, "core.server.module_manager_error",
        "Error with ModuleManager: {error}", error=str(e))
      logger.warning(msg)

    msg = _translate(server_state.i18n, "core.server.application_ready",
      "Application started and ready to receive requests")
    logger.info(msg)

    # Load memory modules, plugins, knowledge, and MemoryService v1
    # (extracted to lifespan_modules.py for maintainability)
    # B09: timeout per evitar penjades indefinides en cada fase d'inicialització
    _startup_phases = [
      ("memory modules", load_memory_modules(app, server_state, _translate)),
      ("plugin modules", initialize_plugin_modules(app, server_state)),
      ("knowledge ingest", auto_ingest_knowledge(server_state)),
      ("MemoryService v1", start_memory_service_v1(app, server_state)),
    ]
    for _phase_name, _phase_coro in _startup_phases:
      try:
        await asyncio.wait_for(_phase_coro, timeout=STARTUP_TIMEOUT)
      except asyncio.TimeoutError:
        logger.error(
          "Startup phase '%s' timed out after %ss (NEXE_STARTUP_TIMEOUT). "
          "Server may be degraded.",
          _phase_name, STARTUP_TIMEOUT,
        )
        raise RuntimeError(f"Startup phase '{_phase_name}' timed out after {STARTUP_TIMEOUT}s")

    # Bootstrap tokens
    setup_bootstrap_tokens(server_state, _translate)

    # Bug 11: auto-renovacio del bootstrap token. Sense aixo, en sessions
    # llargues l'usuari ha de reiniciar el servidor quan el token expira.
    try:
      bootstrap_ttl = int(os.getenv('NEXE_BOOTSTRAP_TTL', os.getenv('BOOTSTRAP_TTL', '30')))
      auto_renew = os.getenv('NEXE_BOOTSTRAP_AUTO_RENEW', 'true').lower() == 'true'
      if auto_renew:
        start_bootstrap_token_renewal(ttl_minutes=bootstrap_ttl)
    except Exception as e:
      logger.warning("Could not start bootstrap token auto-renewal: %s", e)

    if hasattr(app.state, 'start_rate_limit_cleanup'):
      server_state._cleanup_task = asyncio.create_task(app.state.start_rate_limit_cleanup())
      msg = _translate(server_state.i18n, "core.server.rate_limit_cleanup_started",
        "Rate limit cleanup task started")
      logger.info(msg)

    auto_clean_enabled = os.getenv('NEXE_AUTO_CLEAN_ENABLED', os.getenv('AUTO_CLEAN_ENABLED', 'false')).lower() == 'true'
    if auto_clean_enabled:
      try:
        from personality.auto_clean.core.auto_clean import run_auto_clean

        msg = _translate(server_state.i18n, "core.server.auto_clean_start",
          "Auto-Clean: Running automatic cleanup...")
        logger.info(msg)

        dry_run = os.getenv('NEXE_AUTO_CLEAN_DRY_RUN', os.getenv('AUTO_CLEAN_DRY_RUN', 'true')).lower() == 'true'
        result = await run_auto_clean(
          core_root=server_state.project_root,
          dry_run=dry_run
        )

        if result.get("files_cleaned", 0) > 0 or result.get("would_clean", 0) > 0:
          action = "would clean" if dry_run else "cleaned"
          count = result.get("would_clean", 0) if dry_run else result.get("files_cleaned", 0)
          msg = _translate(server_state.i18n, "core.server.auto_clean_done",
            "Auto-Clean: {count} files {action}", count=count, action=action)
          logger.info(msg)
        else:
          msg = _translate(server_state.i18n, "core.server.auto_clean_nothing",
            "Auto-Clean: Nothing to clean")
          logger.debug(msg)

      except ImportError:
        logger.debug("Auto-Clean not available")
      except Exception as e:
        msg = _translate(server_state.i18n, "core.server.auto_clean_error",
          "Auto-Clean error: {error}", error=str(e))
        logger.warning(msg)

    if hasattr(server_state, 'configure_modules_callback'):
      server_state.configure_modules_callback(server_state.api_integrator, server_state.i18n)

    # Session cleanup background task (N-5 / N04)
    # Guarda la referència per poder cancel·lar-la al shutdown (N04).
    try:
      from plugins.web_ui_module.api.routes import start_session_cleanup_task
      web_ui = app.state.modules.get("web_ui_module")
      if web_ui and hasattr(web_ui, 'session_manager'):
        server_state._session_cleanup_task = start_session_cleanup_task(web_ui.session_manager)
        logger.info("Session cleanup task started (runs every hour)")
      else:
        logger.warning("web_ui_module not loaded — session cleanup task skipped")
    except Exception as e:
      logger.warning("Could not start session cleanup task: %s", e)

    # Final message: Server ready
    _srv_cfg = server_state.config.get("core", {}).get("server", {})
    _nexe_url = os.environ.get(
        "NEXE_API_BASE_URL",
        f"http://{_srv_cfg.get('host', DEFAULT_HOST)}:{_srv_cfg.get('port', DEFAULT_PORT)}",
    )
    _api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    _lang = os.environ.get("NEXE_LANG", "ca")

    _crypto_status = "ENABLED" if server_state.crypto_provider else "disabled"

    logger.info("=" * 70)
    logger.info("  SERVER.NEXE READY - Listening on %s", _nexe_url)
    logger.info("  Web UI: %s/ui/", _nexe_url)
    logger.info("  API Key: %s", (_api_key[:4] + "..." if _api_key and len(_api_key) > 4 else "(set)" if _api_key else "(not set)"))
    logger.info("  Encryption: %s", _crypto_status)
    logger.info("=" * 70)

    yield

  except Exception as e:
    msg = _translate(server_state.i18n, "core.server.critical_error",
      "Critical system error: {error}", error=str(e))
    logger.error(msg)
    logger.exception("Critical startup error", exc_info=True)
    raise

  finally:
    msg = _translate(server_state.i18n, "core.server.shutdown_initiated",
      "System shutdown initiated...")
    logger.info(msg)

    # === PID FILE CLEANUP (B10) — sempre, fins i tot si startup ha fallat ===
    _remove_pid_file(server_state.project_root)

    try:
      # Bug 11: stop bootstrap token auto-renewal task net
      try:
        await stop_bootstrap_token_renewal()
      except Exception as e:
        logger.debug("Error stopping bootstrap token renewal: %s", e)

      # Cleanup Ollama models on shutdown
      await cleanup_ollama_shutdown(OLLAMA_HEALTH_TIMEOUT, OLLAMA_UNLOAD_TIMEOUT)

      def _stop_process(process, name: str):
        if not process:
          return
        if process.poll() is not None:
          return
        try:
          import signal
          logger.info("Stopping %s process...", name)
          process.send_signal(signal.SIGINT)
          process.wait(timeout=10)
        except Exception as e:
          logger.debug("SIGINT failed for %s: %s", name, e)
          try:
            process.terminate()
            process.wait(timeout=3)
          except Exception as e:
            logger.debug("Terminate failed for %s: %s", name, e)
            try:
              process.kill()
            except Exception:
              logger.debug("Failed to force-stop %s process", name)

      # Close Qdrant singleton pool
      try:
        from core.qdrant_pool import close_qdrant_client
        close_qdrant_client()
        logger.info("Qdrant pool closed")
      except Exception as e:
        logger.debug("Qdrant pool close failed: %s", e)

      # Graceful shutdown MemoryService v1
      try:
        if hasattr(server_state, '_dreaming_task') and server_state._dreaming_task:
          if hasattr(server_state, '_dreaming_cycle') and server_state._dreaming_cycle:
            server_state._dreaming_cycle.stop()
          server_state._dreaming_task.cancel()
          try:
            await server_state._dreaming_task
          except (asyncio.CancelledError, Exception):
            pass
          logger.info("DreamingCycle stopped")
        if hasattr(app.state, 'memory_service') and app.state.memory_service:
          await app.state.memory_service.shutdown()
          logger.info("MemoryService shut down")
      except Exception as e:
        logger.warning("MemoryService shutdown error (non-fatal): %s", e)

      _stop_process(server_state.ollama_process, "Ollama")

      if server_state.api_integrator:
        logger.debug("Closing APIIntegrator...")
        server_state.api_integrator = None

      # NOTE: Do NOT set module_manager or registry to None here.
      # They are stateless in-memory registries and must persist between
      # TestClient contexts (multiple lifespan cycles in the same process).
      # Setting them to None causes "ModuleManager not available" on next startup.
      if server_state.module_manager:
        logger.debug("ModuleManager kept alive (stateless registry)")

      # Cancel·la cleanup tasks en background (N04)
      for _task_attr in ('_cleanup_task', '_session_cleanup_task'):
        _task = getattr(server_state, _task_attr, None)
        if _task is not None and not _task.done():
          _task.cancel()
          try:
            await _task
          except (asyncio.CancelledError, Exception):
            pass
          logger.debug("Background task '%s' cancelled", _task_attr)

      # Reinicia circuit breakers a CLOSED per al proper reinici (N03)
      try:
        from core.resilience import reset_all_circuit_breakers
        reset_all_circuit_breakers()
        logger.debug("Circuit breakers reset to CLOSED")
      except Exception as exc:
        logger.debug("Circuit breaker reset failed (non-fatal): %s", exc)

    except Exception as e:
      msg = _translate(server_state.i18n, "core.server.cleanup_error",
        "Error during cleanup: {error}", error=str(e))
      logger.error(msg)

    msg = _translate(server_state.i18n, "core.server.shutdown_goodbye",
      "Nexe 0.9 stopped successfully. See you soon!")
    logger.info(msg)

def get_server_state() -> ServerState:
  """Get the global server state"""
  return server_state
