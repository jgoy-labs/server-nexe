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
from typing import Dict, Any, Optional, Callable

# ═══════════════════════════════════════════════════════════════════════════
# Environment setup — must go BEFORE any import that could transitively load
# HuggingFace/sentence-transformers. We would move it even higher but
# os/warnings are already at the top.
# ═══════════════════════════════════════════════════════════════════════════

# Force offline mode for HuggingFace — server must work without internet
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Bug 14 (2026-04-06) — silence tqdm from sentence-transformers at server runtime.
# The `Batches: 0%|...` bars mixed with server logs and created corrupt lines.
# Applied ONLY at server runtime (does not affect the initial model download,
# which is done via installer/setup_models.py).
os.environ.setdefault("TQDM_DISABLE", "1")

# Bug 6 (2026-04-06) — silence noisy warnings when loading embedders.
# `paraphrase-multilingual-mpnet-base-v2` emits UserWarning for
# `position_ids UNEXPECTED` and `Some weights of...` which add no value.
# Dev D (Consultant pass 1): moved BEFORE `from .lifespan_modules import ...`
# to ensure they apply even if a transitive import loads sentence_transformers
# at import time.
_warnings.filterwarnings("ignore", message=".*position_ids.*", category=UserWarning)
_warnings.filterwarnings("ignore", message=".*Some weights of.*", category=UserWarning)
_warnings.filterwarnings("ignore", category=UserWarning, module="fastembed")

from fastapi import FastAPI  # noqa: E402  # after warnings filter (line 44-46) so it applies to transitive imports

from personality.integration import APIIntegrator  # noqa: E402  # after warnings filter
from .config import load_config  # noqa: E402  # after warnings filter
from .lifespan_services import (  # noqa: E402  # after warnings filter
    _auto_start_services,
    _stop_process,
    OLLAMA_HEALTH_TIMEOUT,
    OLLAMA_UNLOAD_TIMEOUT,
)
from .lifespan_tokens import (  # noqa: E402  # after warnings filter
    setup_bootstrap_tokens,
    start_bootstrap_token_renewal,
    stop_bootstrap_token_renewal,
)
from .lifespan_ollama import cleanup_ollama_startup, cleanup_ollama_shutdown  # noqa: E402  # after warnings filter
from .lifespan_modules import (  # noqa: E402  # after warnings filter
    load_memory_modules,
    initialize_plugin_modules,
    auto_ingest_knowledge,
    start_memory_service_v1,
    _startup_module_discovery,
    _shutdown_memory_service,
)
from .lifespan_crypto import _startup_encryption  # noqa: E402  # after warnings filter
from .lifespan_qdrant import _startup_qdrant, _shutdown_qdrant  # noqa: E402  # after warnings filter
from .lifespan_auto_clean import _startup_auto_clean  # noqa: E402  # after warnings filter
from .lifespan_sessions import _startup_session_cleanup  # noqa: E402  # after warnings filter

logger = logging.getLogger(__name__)


from core.server.helpers import translate as _translate  # noqa: E402  # after warnings filter

# Startup phase timeout (B09). F3.3 BUG-C5: raise default from 30s to 120s and
# accept the more descriptive `NEXE_LIFESPAN_TIMEOUT` alongside the legacy name.
# Rationale: MLX/llama.cpp model warmup with a cold cache (Qwen 35B-A3B 4-bit,
# Mixtral, Qwen3.5-Coder 8-bit) routinely takes 30-90s. The previous 30s budget
# made cold boots flap with a RuntimeError. Operators who keep a hot cache and
# want fast-fail can set `NEXE_LIFESPAN_TIMEOUT=30` (or the legacy name) and
# preserve the old behaviour.
def _resolve_startup_timeout() -> float:
    """Pure resolver — testable with `monkeypatch.setenv` (no module reload)."""
    raw = os.getenv("NEXE_LIFESPAN_TIMEOUT") or os.getenv("NEXE_STARTUP_TIMEOUT", "120")
    return float(raw)


STARTUP_TIMEOUT = _resolve_startup_timeout()

# Canonical path for the PID file (B06, B10, B15).
_PID_SUBPATH = Path("storage") / "run" / "server.pid"


def _resolve_encryption_enabled(env_value: str, *, sqlcipher_available: bool) -> bool:
  """P1-D: Determine whether encryption should be enabled given the env config and availability.

  - 'auto' or '' (empty/legacy): enable if sqlcipher3 is available, otherwise OFF
  - 'true': always ON (caller checks SQLCIPHER_AVAILABLE and raises RuntimeError if needed)
  - 'false': always OFF
  - any other value: OFF (safe default behaviour)

  Pure function (no side effects) so it can be tested directly.
  Logging is done by the caller (lifespan startup).
  """
  normalized = env_value.strip().lower()
  if normalized in ('', 'auto'):
    return sqlcipher_available
  if normalized == 'true':
    return True
  if normalized == 'false':
    return False
  return False  # unknown value → OFF


def _write_pid_file(project_root: Path, port: int) -> bool:
  """Write the PID file atomically (O_CREAT|O_EXCL). B06, B07, B10.

  Returns True if acquired, False if a live server already holds it.
  Stale files (dead or corrupt PID) are removed automatically.
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
          # Empty: another process just created it with O_EXCL and is still writing.
          # Treat as locked — do NOT delete.
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
  """Remove the PID file if it exists and belongs to this process. B10.

  Safe to call in a finally block — never raises exceptions.
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
  def __init__(self) -> None:
    """Initialize all server-wide state slots to their defaults."""
    self.config: Dict[str, Any] = {}
    self.api_integrator: Optional[APIIntegrator] = None
    self.project_root: Optional[Path] = None
    self.i18n: Optional[Any] = None
    self.module_manager: Optional[Any] = None
    self.registry: Optional[Any] = None
    self.ollama_process: Optional[Any] = None
    self.qdrant_available: bool = False
    self.crypto_provider: Optional[Any] = None
    self._cleanup_task: Optional[asyncio.Task[Any]] = None
    self._prewarm_task: Optional[asyncio.Task[Any]] = None
    self._session_cleanup_task: Optional[asyncio.Task[Any]] = None
    self._knowledge_ingest_task: Optional[asyncio.Task[Any]] = None
    self.knowledge_ingest_complete: bool = False
    self.configure_modules_callback: Optional[Callable[..., None]] = None

server_state = ServerState()


async def _wrap_knowledge_ingest(state: "ServerState") -> None:
    """F2.A10: Wraps auto_ingest_knowledge for background execution.

    Sets state.knowledge_ingest_complete=True when finished so endpoints
    can know whether RAG retrieval is fully primed.
    """
    try:
        await auto_ingest_knowledge(state)
        state.knowledge_ingest_complete = True
        logger.info("Knowledge: Background ingest finished")
    except asyncio.CancelledError:
        logger.info("Knowledge: Background ingest cancelled (shutdown)")
        raise
    except Exception as exc:
        logger.warning("Knowledge: Background ingest failed: %s", exc)


async def _prewarm_fastembed() -> None:
    """B.1: Pre-warm fastembed ONNX runtime at startup (background, non-blocking).

    Obtains the MemoryAPI singleton (created or reused by get_memory_api),
    enables pre_warm on the instance and calls warmup(). Does not modify the
    global IngestConfig defaults.
    """
    import time as _time
    try:
        from memory.memory.api.v1 import get_memory_api
        memory_api = await get_memory_api()
        memory_api.ingest_config.pre_warm = True
        t0 = _time.perf_counter_ns()
        await memory_api.warmup()
        elapsed_ms = (_time.perf_counter_ns() - t0) / 1_000_000
        logger.info("MemoryAPI: fastembed pre-warm complete (%.1fms)", elapsed_ms)
    except Exception as exc:
        logger.warning("MemoryAPI: fastembed pre-warm failed (non-fatal): %s", exc)


async def _startup_init(app: FastAPI) -> None:
    """Bloc 1: log inicial, reload trigger, config, PID, encryption, qdrant."""
    logger.info("=" * 70)
    logger.info("LIFESPAN STARTUP TRIGGERED")
    logger.info("=" * 70)

    msg = _translate(server_state.i18n, "core.server.banner", "Nexe 0.9 - Modular AI System")
    logger.info(msg)

    reload_trigger = server_state.project_root / ".nexe_reload_trigger.py"  # type: ignore[operator]
    if reload_trigger.exists():
        try:
            reload_trigger.unlink()
            logger.debug("Cleaned up reload trigger: %s", reload_trigger)
        except Exception as e:
            logger.warning("Could not delete reload trigger: %s", e)

    msg = _translate(server_state.i18n, "core.server.project_root",
        "Project root: {path}", path=str(server_state.project_root))
    logger.info(msg)

    server_state.config = load_config(server_state.project_root, server_state.i18n)
    app.state.config = server_state.config

    # PID file — single-instance guard (B06, B07, B10)
    # F2.1 Sessió 3 part 2 (2026-05-16 23:50): en mode sidecar Tauri, SKIP el
    # PID file completament. Tauri gestiona el cicle de vida del procés via
    # NEXE_PARENT_PID watchdog (lifecycle.rs:graceful_quit). El single-instance
    # guard és per a standalone (CLI), on hi pot haver col·lisió usuari.
    # En mode sidecar, cada Tauri pot tenir el seu propi procés sidecar; el
    # PID file global (storage/run/server.pid, un sol fitxer) provocava
    # "Server already running" entre sessions Tauri successives — encara que
    # el procés anterior estigués correctament aturat per Tauri.
    from core.config import DEFAULT_PORT
    _srv_startup_cfg = server_state.config.get('core', {}).get('server', {})
    _startup_port = _srv_startup_cfg.get('port', DEFAULT_PORT)
    _skip_pid_file = False
    try:
        from core.sidecar_config import get_sidecar_config
        sidecar_cfg = get_sidecar_config()
        if sidecar_cfg.is_sidecar:
            _startup_port = sidecar_cfg.port  # NEXE_PORT injectat per Tauri
            _skip_pid_file = True
            logger.info("Sidecar mode: skipping PID file (Tauri manages lifecycle)")
    except Exception as exc:  # pragma: no cover — fallback comportament pre-F2.1
        logger.debug("SidecarConfig unavailable, using default PID file behavior: %s", exc)

    if not _skip_pid_file and server_state.project_root and not _write_pid_file(server_state.project_root, _startup_port):
        raise RuntimeError(
            f"Server already running on port {_startup_port}. "
            "Use './nexe stop' to stop the existing instance."
        )

    if _skip_pid_file:
        try:
            from core.server.watchdog import start_parent_watchdog
            start_parent_watchdog(poll_interval=2.0)
            logger.info("Parent watchdog: started in sidecar mode (poll 2s)")
        except Exception as exc:
            logger.warning("Parent watchdog: failed to start in sidecar mode: %s", exc)

    await _startup_encryption(server_state)
    _startup_qdrant()


async def _startup_services(app: FastAPI) -> None:
    """Bloc 2: serveis externs (timeout), APIIntegrator, Ollama cleanup, module discovery."""
    try:
        await asyncio.wait_for(
            _auto_start_services(server_state.config, server_state.project_root, server_state),  # type: ignore[arg-type]
            timeout=STARTUP_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Services startup timed out after %ss (NEXE_STARTUP_TIMEOUT). "
            "Check Qdrant and Ollama availability.",
            STARTUP_TIMEOUT,
        )
        raise RuntimeError(f"Services startup timed out after {STARTUP_TIMEOUT}s")

    from core.config import DEFAULT_HOST, DEFAULT_PORT
    server_config = server_state.config.get('core', {}).get('server', {})
    host = server_config.get('host', DEFAULT_HOST)
    port = server_config.get('port', DEFAULT_PORT)
    msg = _translate(server_state.i18n, "core.server.binding_server",
        "Server ready at {host}:{port}", host=host, port=port)
    logger.info(msg)
    msg = _translate(server_state.i18n, "core.server.all_systems_go", "All systems operational - Nexe 0.9 ready!")
    logger.info(msg)

    server_state.api_integrator = APIIntegrator(app, server_state.i18n)
    msg = _translate(server_state.i18n, "core.server.api_integrator_ready", "API Integrator ready")
    logger.info(msg)

    await cleanup_ollama_startup(server_state, _translate, OLLAMA_HEALTH_TIMEOUT, OLLAMA_UNLOAD_TIMEOUT)
    await _startup_module_discovery(app, server_state, _translate)

    msg = _translate(server_state.i18n, "core.server.application_ready",
        "Application started and ready to receive requests")
    logger.info(msg)


async def _startup_phases_and_tokens(app: FastAPI) -> None:
    """Bloc 3: phases startup (timeout each), tokens bootstrap, tasques segon pla, callbacks."""
    _startup_phases = [
        ("memory modules", load_memory_modules(app, server_state, _translate)),
        ("plugin modules", initialize_plugin_modules(app, server_state)),
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

    server_state._knowledge_ingest_task = asyncio.create_task(
        _wrap_knowledge_ingest(server_state)
    )
    logger.info("Knowledge: Auto-ingest scheduled in background (non-blocking)")

    setup_bootstrap_tokens(server_state, _translate)
    try:
        bootstrap_ttl = int(os.getenv('NEXE_BOOTSTRAP_TTL', os.getenv('BOOTSTRAP_TTL', '30')))
        auto_renew = os.getenv('NEXE_BOOTSTRAP_AUTO_RENEW', 'true').lower() == 'true'
        if auto_renew:
            start_bootstrap_token_renewal(ttl_minutes=bootstrap_ttl)
    except Exception as e:
        logger.warning("Could not start bootstrap token auto-renewal: %s", e)  # nosemgrep: python-logger-credential-disclosure

    if hasattr(app.state, 'start_rate_limit_cleanup'):
        server_state._cleanup_task = asyncio.create_task(app.state.start_rate_limit_cleanup())
        msg = _translate(server_state.i18n, "core.server.rate_limit_cleanup_started",
            "Rate limit cleanup task started")
        logger.info(msg)

    # B.1 — pre-warm fastembed ONNX runtime (background, non-blocking)
    server_state._prewarm_task = asyncio.create_task(_prewarm_fastembed())
    logger.info("MemoryAPI: fastembed pre-warm task scheduled")

    await _startup_auto_clean(server_state, _translate)

    if hasattr(server_state, 'configure_modules_callback') and server_state.configure_modules_callback is not None:
        server_state.configure_modules_callback(server_state.api_integrator, server_state.i18n)

    await _startup_session_cleanup(app, server_state)


def _startup_final_banner() -> None:
    """Bloc 4: banner final amb URL, API key i estat encryption."""
    from core.config import DEFAULT_HOST, DEFAULT_PORT
    _srv_cfg = server_state.config.get("core", {}).get("server", {})
    _nexe_url = os.environ.get(
        "NEXE_API_BASE_URL",
        f"http://{_srv_cfg.get('host', DEFAULT_HOST)}:{_srv_cfg.get('port', DEFAULT_PORT)}",
    )
    _api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    _crypto_status = "ENABLED" if server_state.crypto_provider else "disabled"

    logger.info("=" * 70)
    logger.info("  SERVER.NEXE READY - Listening on %s", _nexe_url)
    logger.info("  Web UI: %s/ui/", _nexe_url)
    logger.info("  API Key: %s", "(configured)" if _api_key else "(not set)")  # nosemgrep: python-logger-credential-disclosure — value is always "(configured)" or "(not set)", never the key itself
    logger.info("  Encryption: %s", _crypto_status)
    logger.info("=" * 70)


async def _startup(app: FastAPI) -> None:
    """Startup orchestrator: delegates each phase to its helper."""
    await _startup_init(app)
    await _startup_services(app)
    await _startup_phases_and_tokens(app)
    _startup_final_banner()


async def _cancel_background_tasks() -> None:
    """Cancels active background tasks (N04)."""
    for _task_attr in ('_cleanup_task', '_session_cleanup_task', '_prewarm_task', '_knowledge_ingest_task'):
        _task = getattr(server_state, _task_attr, None)
        if _task is not None and not _task.done():
            _task.cancel()
            try:
                await _task
            except (asyncio.CancelledError, Exception):
                pass
            logger.debug("Background task '%s' cancelled", _task_attr)


def _reset_circuit_breakers() -> None:
    """Resets circuit breakers to CLOSED for the next restart (N03)."""
    try:
        from core.resilience import reset_all_circuit_breakers
        reset_all_circuit_breakers()
        logger.debug("Circuit breakers reset to CLOSED")
    except Exception as exc:
        logger.debug("Circuit breaker reset failed (non-fatal): %s", exc)


async def _shutdown(app: FastAPI) -> None:
    """Shutdown orchestrator: orderly cleanup of all services."""
    msg = _translate(server_state.i18n, "core.server.shutdown_initiated", "System shutdown initiated...")
    logger.info(msg)

    # PID file cleanup — always, even if startup failed (B10)
    _remove_pid_file(server_state.project_root)  # type: ignore[arg-type]

    try:
        try:
            await stop_bootstrap_token_renewal()
        except Exception as e:
            logger.debug("Error stopping bootstrap token renewal: %s", e)  # nosemgrep: python-logger-credential-disclosure

        await cleanup_ollama_shutdown(OLLAMA_HEALTH_TIMEOUT, OLLAMA_UNLOAD_TIMEOUT)
        _shutdown_qdrant()
        await _shutdown_memory_service(app, server_state)
        _stop_process(server_state.ollama_process, "Ollama")

        if server_state.api_integrator:
            logger.debug("Closing APIIntegrator...")
            server_state.api_integrator = None

        # NOTE: Do NOT set module_manager or registry to None here.
        # They are stateless in-memory registries and must persist between
        # TestClient contexts (multiple lifespan cycles in the same process).
        if server_state.module_manager:
            logger.debug("ModuleManager kept alive (stateless registry)")

        await _cancel_background_tasks()
        _reset_circuit_breakers()

    except Exception as e:
        msg = _translate(server_state.i18n, "core.server.cleanup_error",
            "Error during cleanup: {error}", error=str(e))
        logger.error(msg)

    msg = _translate(server_state.i18n, "core.server.shutdown_goodbye",
        "Nexe 0.9 stopped successfully. See you soon!")
    logger.info(msg)


@asynccontextmanager
async def lifespan(app: FastAPI):
  """
  Application lifespan — façade that delegates each startup/shutdown phase
  to dedicated submodule helpers.
  """
  try:
    await _startup(app)
    yield
  except Exception as e:
    msg = _translate(server_state.i18n, "core.server.critical_error",
      "Critical system error: {error}", error=str(e))
    logger.error(msg)
    logger.exception("Critical startup error", exc_info=True)
    raise
  finally:
    await _shutdown(app)

def get_server_state() -> ServerState:
  """Get the global server state"""
  return server_state
