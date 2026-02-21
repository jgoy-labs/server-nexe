"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/lifespan.py
Description: FastAPI lifespan management (startup/shutdown). Loads config, initializes APIIntegrator,

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import atexit
import logging
import shutil
import signal
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI
import secrets
from datetime import datetime, timedelta, timezone
import os

from personality.integration import APIIntegrator
from .config import load_config

logger = logging.getLogger(__name__)

# Configurable timeouts via environment variables
OLLAMA_HEALTH_TIMEOUT = float(os.getenv('NEXE_OLLAMA_HEALTH_TIMEOUT', '5.0'))
OLLAMA_UNLOAD_TIMEOUT = float(os.getenv('NEXE_OLLAMA_UNLOAD_TIMEOUT', '10.0'))
QDRANT_HEALTH_TIMEOUT = float(os.getenv('NEXE_QDRANT_HEALTH_TIMEOUT', '2.0'))


async def _auto_start_services(config: Dict[str, Any], project_root: Path) -> None:
  """Auto-start required services (Qdrant, Ollama) if not running."""
  import httpx
  async with httpx.AsyncClient() as client:

    # === QDRANT (local binary, no Docker!) ===
    auto_start_qdrant = os.getenv("NEXE_AUTOSTART_QDRANT", "true").lower() == "true"
    qdrant_host = os.getenv('QDRANT_HOST', 'localhost')
    qdrant_port = os.getenv('QDRANT_PORT', '6333')
    qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
    qdrant_bin = project_root / "qdrant"
    qdrant_storage = project_root / "storage" / "qdrant"
    qdrant_log_dir = project_root / "storage" / "logs"
    qdrant_log_path = qdrant_log_dir / "qdrant.log"

    try:
      await client.get(f"{qdrant_url}/health", timeout=QDRANT_HEALTH_TIMEOUT)
      logger.info(_translate(
        server_state.i18n,
        "core.lifespan.qdrant_ok",
        "Qdrant: OK (already running)"
      ))
    except Exception:
      if not auto_start_qdrant:
        logger.info(_translate(
          server_state.i18n,
          "core.lifespan.qdrant_autostart_disabled",
          "Qdrant: Auto-start disabled (NEXE_AUTOSTART_QDRANT=false)"
        ))
      elif qdrant_bin.exists():
        logger.info(_translate(
          server_state.i18n,
          "core.lifespan.qdrant_starting",
          "Qdrant: Starting from {path}...",
          path=str(qdrant_bin)
        ))
        try:
          qdrant_storage.mkdir(parents=True, exist_ok=True)
          env = os.environ.copy()
          env["QDRANT__STORAGE__STORAGE_PATH"] = str(qdrant_storage)
          env["QDRANT__SERVICE__HTTP_PORT"] = str(qdrant_port)
          env["QDRANT__SERVICE__DISABLE_TELEMETRY"] = "true"

          # Start Qdrant process
          qdrant_log_dir.mkdir(parents=True, exist_ok=True)
          qdrant_log_file = open(qdrant_log_path, "a", encoding="utf-8")
          process = subprocess.Popen(
            [str(qdrant_bin), "--disable-telemetry"],
            stdout=qdrant_log_file,
            stderr=qdrant_log_file,
            env=env
          )
          server_state.qdrant_process = process
          server_state.qdrant_pid = process.pid
          server_state.qdrant_pid_file = project_root / "storage" / "qdrant.pid"
          server_state.qdrant_log_file = qdrant_log_file
          server_state.qdrant_log_path = qdrant_log_path
          _write_pid_file(server_state.qdrant_pid_file, process.pid, server_state.i18n)
          logger.info(_translate(
            server_state.i18n,
            "core.lifespan.qdrant_log_path",
            "Qdrant logs: {path}",
            path=str(qdrant_log_path)
          ))

          # Wait for Qdrant to be ready (FIX: use asyncio.sleep to not block event loop)
          for i in range(30):  # 15 seconds max
            await asyncio.sleep(0.5)
            try:
              await client.get(f"{qdrant_url}/health", timeout=QDRANT_HEALTH_TIMEOUT)
              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.qdrant_started",
                "Qdrant: OK (started on port {port})",
                port=qdrant_port
              ))
              break
            except Exception:
              # Check if process died
              if process.poll() is not None:
                logger.error(_translate(
                  server_state.i18n,
                  "core.lifespan.qdrant_process_died",
                  "Qdrant: Process died. Run './qdrant' manually to see logs."
                ))
                logger.info(_translate(
                  server_state.i18n,
                  "core.lifespan.qdrant_log_path",
                  "Qdrant logs: {path}",
                  path=str(qdrant_log_path)
                ))
                break
          else:
            logger.warning(_translate(
              server_state.i18n,
              "core.lifespan.qdrant_start_timeout",
              "Qdrant: Failed to start (timeout 15s)"
            ))
            logger.info(_translate(
              server_state.i18n,
              "core.lifespan.qdrant_log_path",
              "Qdrant logs: {path}",
              path=str(qdrant_log_path)
            ))
        except Exception as e:
          logger.error(_translate(
            server_state.i18n,
            "core.lifespan.qdrant_start_failed",
            "Qdrant: Failed to start: {error}",
            error=str(e)
          ))
      else:
        logger.warning(_translate(
          server_state.i18n,
          "core.lifespan.qdrant_binary_not_found",
          "Qdrant: Binary not found at {path}",
          path=str(qdrant_bin)
        ))
        logger.info(_translate(
          server_state.i18n,
          "core.lifespan.qdrant_setup_hint",
          "  Run ./setup.sh to download Qdrant automatically"
        ))

    # === OLLAMA (fallback engine) ===
    auto_start_ollama = os.getenv("NEXE_AUTOSTART_OLLAMA", "true").lower() == "true"
    ollama_host = os.getenv("OLLAMA_HOST", "localhost")
    ollama_url = f"http://{ollama_host}:11434"

    # Check if Ollama is running
    ollama_running = False
    try:
      await client.get(f"{ollama_url}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
      logger.info(_translate(
        server_state.i18n,
        "core.lifespan.ollama_ok",
        "Ollama: OK (already running)"
      ))
      ollama_running = True
    except Exception as e:
      logger.debug(_translate(
        server_state.i18n,
        "core.lifespan.ollama_health_check_failed_startup",
        "Ollama health check failed during startup: {error}",
        error=str(e)
      ))

    if not ollama_running and not auto_start_ollama:
      logger.info(_translate(
        server_state.i18n,
        "core.lifespan.ollama_autostart_disabled",
        "Ollama: Auto-start disabled (NEXE_AUTOSTART_OLLAMA=false)"
      ))
    if not ollama_running and auto_start_ollama:
      # Check if Ollama is installed
      ollama_path = shutil.which("ollama")

      if not ollama_path:
        logger.warning(_translate(
          server_state.i18n,
          "core.lifespan.ollama_not_installed",
          "Ollama: Not installed. Install manually from https://ollama.com/download"
        ))
        logger.info(_translate(
          server_state.i18n,
          "core.lifespan.ollama_install_hint",
          "  Or run: curl -fsSL https://ollama.com/install.sh | sh"
        ))

      # Start Ollama if installed
      if ollama_path or shutil.which("ollama"):
        logger.info(_translate(
          server_state.i18n,
          "core.lifespan.ollama_starting",
          "Ollama: Starting..."
        ))
        try:
          process = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
          )
          server_state.ollama_process = process
          server_state.ollama_pid = process.pid
          server_state.ollama_pid_file = project_root / "storage" / "ollama.pid"
          _write_pid_file(server_state.ollama_pid_file, process.pid, server_state.i18n)
          # Wait for Ollama to be ready (FIX: use asyncio.sleep to not block event loop)
          for _ in range(30):  # 15 seconds max
            await asyncio.sleep(0.5)
            try:
              await client.get(f"{ollama_url}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.ollama_started",
                "Ollama: OK (started)"
              ))
              break
            except Exception as e:
              logger.debug(_translate(
                server_state.i18n,
                "core.lifespan.ollama_not_ready",
                "Ollama not ready yet during startup wait: {error}",
                error=str(e)
              ))
          else:
            logger.warning(_translate(
              server_state.i18n,
              "core.lifespan.ollama_start_timeout",
              "Ollama: Failed to start (timeout 15s)"
            ))
        except Exception as e:
          logger.warning(_translate(
            server_state.i18n,
            "core.lifespan.ollama_start_failed",
            "Ollama: Failed to start: {error}",
            error=str(e)
          ))

def _translate(i18n, key: str, fallback: str, **kwargs) -> str:
  """Helper to translate with fallback (for lifespan)"""
  if not i18n:
    return fallback.format(**kwargs) if kwargs else fallback
  try:
    value = i18n.t(key, **kwargs)
    if value == key:
      return fallback.format(**kwargs) if kwargs else fallback
    return value
  except Exception:
    return fallback.format(**kwargs) if kwargs else fallback

def generate_bootstrap_token() -> str:
  """
  Generates high entropy bootstrap token.

  Format: Nexe-XXXXXXXXXXXXXXXXXXXX (24 alphanumeric chars)
  Entropy: 128 bits (computationally infeasible to brute force)

  SECURITY CHANGE (2025-11-28):
  - BEFORE: WORD-WORD-NNNNNN (28.5 bits, brute force <1h)
  - NOW: Nexe-{hex(16)} (128 bits, infeasible)

  The token remains relatively easy to copy manually
  but is now cryptographically secure.

  Returns:
    Token en format Nexe-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX (35 chars total)
  """
  random_part = secrets.token_hex(16)
  return f"Nexe-{random_part.upper()}"

class ServerState:
  """Holds server global state"""
  def __init__(self):
    self.config: Dict[str, Any] = {}
    self.api_integrator: APIIntegrator = None
    self.project_root: Path = None
    self.i18n = None
    self.module_manager = None
    self.registry = None
    self.qdrant_process = None
    self.ollama_process = None
    self.qdrant_pid = None
    self.ollama_pid = None
    self.qdrant_pid_file = None
    self.ollama_pid_file = None
    self.qdrant_log_file = None
    self.qdrant_log_path = None

server_state = ServerState()

_cleanup_registered = False
_cleanup_running = False
_cleanup_lock = threading.Lock()
_previous_signal_handlers = {}


def _stop_process(process, name: str, i18n=None) -> None:
  if not process:
    return
  if process.poll() is not None:
    return
  try:
    logger.info(_translate(
      i18n,
      "core.lifespan.process_stopping",
      "Stopping {name} process...",
      name=name
    ))
    process.terminate()
    process.wait(timeout=5)
  except Exception:
    try:
      process.kill()
    except Exception:
      logger.debug(_translate(
        i18n,
        "core.lifespan.process_force_stop_failed",
        "Failed to force-stop {name} process",
        name=name
      ))


def _cleanup_child_processes(i18n=None) -> None:
  global _cleanup_running
  with _cleanup_lock:
    if _cleanup_running:
      return
    _cleanup_running = True

  try:
    _stop_process(server_state.qdrant_process, "Qdrant", i18n)
    _stop_process(server_state.ollama_process, "Ollama", i18n)
    _cleanup_pid_file(server_state.qdrant_pid_file)
    _cleanup_pid_file(server_state.ollama_pid_file)
    if server_state.qdrant_log_file:
      try:
        server_state.qdrant_log_file.flush()
        server_state.qdrant_log_file.close()
        server_state.qdrant_log_file = None
      except Exception:
        pass
  finally:
    with _cleanup_lock:
      _cleanup_running = False


def _write_pid_file(pid_path: Path, pid: int, i18n=None) -> None:
  try:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(pid))
  except Exception as e:
    logger.debug(_translate(
      i18n,
      "core.lifespan.pid_write_failed",
      "Failed to write pid file {path}: {error}",
      path=str(pid_path),
      error=str(e)
    ))


def _cleanup_pid_file(pid_path: Path) -> None:
  if not pid_path:
    return
  try:
    if pid_path.exists():
      pid_path.unlink()
  except Exception:
    pass


def _register_process_cleanup(i18n=None) -> None:
  global _cleanup_registered
  if _cleanup_registered:
    return
  _cleanup_registered = True

  atexit.register(_cleanup_child_processes, i18n)

  def _signal_handler(signum, frame):
    _cleanup_child_processes(i18n)
    prev = _previous_signal_handlers.get(signum)
    if callable(prev):
      try:
        prev(signum, frame)
      except Exception:
        pass
    elif prev == signal.SIG_DFL:
      raise SystemExit(0)

  for sig in (signal.SIGTERM, signal.SIGINT):
    try:
      prev = signal.getsignal(sig)
      _previous_signal_handlers[sig] = prev
      if prev != _signal_handler:
        signal.signal(sig, _signal_handler)
    except ValueError:
      # Signal handling only allowed in main thread
      continue

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
    logger.info(_translate(
      server_state.i18n,
      "core.lifespan.startup_triggered",
      "LIFESPAN STARTUP TRIGGERED"
    ))
    logger.info("=" * 70)

    msg = _translate(server_state.i18n, "core.server.banner",
      "Nexe 0.8 - Modular AI System")
    logger.info(msg)

    reload_trigger = server_state.project_root / ".nexe_reload_trigger.py"
    if reload_trigger.exists():
      try:
        reload_trigger.unlink()
        logger.debug(_translate(
          server_state.i18n,
          "core.lifespan.reload_trigger_cleaned",
          "Cleaned up reload trigger: {path}",
          path=str(reload_trigger)
        ))
      except Exception as e:
        logger.warning(_translate(
          server_state.i18n,
          "core.lifespan.reload_trigger_delete_failed",
          "Could not delete reload trigger: {error}",
          error=str(e)
        ))

    msg = _translate(server_state.i18n, "core.server.project_root",
      "Project root: {path}",
      path=str(server_state.project_root))
    logger.info(msg)

    _register_process_cleanup(server_state.i18n)

    server_state.config = load_config(server_state.project_root, server_state.i18n)

    # Auto-start services (Qdrant, Ollama) if not running
    await _auto_start_services(server_state.config, server_state.project_root)

    server_config = server_state.config.get('core', {}).get('server', {})
    host = server_config.get('host', '127.0.0.1')
    port = server_config.get('port', 9119)

    msg = _translate(server_state.i18n, "core.server.binding_server",
      "Server ready at {host}:{port}",
      host=host, port=port)
    logger.info(msg)

    msg = _translate(server_state.i18n, "core.server.all_systems_go",
      "All systems operational - Nexe 0.8 ready!")
    logger.info(msg)

    server_state.api_integrator = APIIntegrator(app, server_state.i18n)

    msg = _translate(server_state.i18n, "core.server.api_integrator_ready",
      "API Integrator ready")
    logger.info(msg)

    try:
      import httpx
      ollama_url = "http://localhost:11434"

      async with httpx.AsyncClient() as client:
        try:
          health_response = await client.get(f"{ollama_url}/api/ps", timeout=OLLAMA_HEALTH_TIMEOUT)
          if health_response.status_code == 200:
            loaded_models = health_response.json().get("models", [])

            if loaded_models:
              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.ollama_cleaning",
                "Cleaning Ollama: {count} model(s) loaded from previous sessions...",
                count=len(loaded_models)
              ))

              for model_info in loaded_models:
                model_name = model_info.get("name") or model_info.get("model")
                if model_name:
                  try:
                    await client.post(
                      f"{ollama_url}/api/generate",
                      json={"model": model_name, "keep_alive": 0},
                      timeout=OLLAMA_UNLOAD_TIMEOUT
                    )
                    logger.debug(_translate(
                      server_state.i18n,
                      "core.lifespan.ollama_unloaded",
                      "  - Unloaded: {model}",
                      model=model_name
                    ))
                  except Exception as e:
                    msg = _translate(server_state.i18n, "core.server.ollama_unload_error",
                      "Error unloading {model}: {error}",
                      model=model_name, error=str(e))
                    logger.warning(msg)

              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.ollama_clean_success",
                "Ollama cleaned successfully"
              ))
            else:
              logger.debug(_translate(
                server_state.i18n,
                "core.lifespan.ollama_clean_none",
                "Ollama is clean (no models loaded)"
              ))
          else:
            msg = _translate(server_state.i18n, "core.server.ollama_health_check_failed",
              "Ollama health check failed: HTTP {status_code}",
              status_code=health_response.status_code)
            logger.warning(msg)

        except httpx.ConnectError:
          msg = _translate(server_state.i18n, "core.server.ollama_not_available",
            "Ollama not available (localhost:11434). If using Ollama, start it manually.")
          logger.warning(msg)
        except httpx.TimeoutException:
          msg = _translate(server_state.i18n, "core.server.ollama_timeout",
            "Ollama timeout. May be busy.")
          logger.warning(msg)

    except Exception as e:
      msg = _translate(server_state.i18n, "core.server.ollama_cleanup_error",
        "Error checking/cleaning Ollama: {error}", error=str(e))
      logger.warning(msg)

    try:
      if server_state.module_manager:
        server_state.registry = server_state.module_manager.registry
        msg = _translate(server_state.i18n, "core.server.module_manager_ready", "ModuleManager already initialized")
        logger.info(msg)

        discovered = await server_state.module_manager.discover_modules()
        total_modules = list(server_state.module_manager._modules.keys())

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

    try:
      # Use ModuleManager directly (SINGLE SOURCE OF TRUTH)
      msg = _translate(server_state.i18n, "core.server.loading_memory",
        "Loading Memory modules (Memory, RAG, Embeddings)...")
      logger.info(msg)

      loaded = await server_state.module_manager.load_memory_modules(config=server_state.config)

      msg = _translate(server_state.i18n, "core.server.memory_loaded",
        "Memory modules loaded: {count}", count=len(loaded))
      logger.info(msg)

      for id_res, instance in loaded.items():
        logger.info(_translate(
          server_state.i18n,
          "core.lifespan.module_loaded_item",
          "  - {name} ({id})",
          name=getattr(instance, "name", id_res),
          id=id_res
        ))
        try:
          from core.metrics.registry import set_module_health
          health = instance.get_health()
          set_module_health(instance.name, health.get("status", "unhealthy"))
        except Exception as e:
          logger.debug(_translate(
            server_state.i18n,
            "core.lifespan.module_health_skipped",
            "Module health update skipped: {error}",
            error=str(e)
          ))

      if not hasattr(app.state, 'modules'):
        app.state.modules = {}
      for module_id, instance in loaded.items():
        app.state.modules.setdefault(module_id, instance)
        if getattr(instance, "name", None):
          app.state.modules.setdefault(instance.name, instance)
        try:
          capabilities = []
          if hasattr(instance, "manifest"):
            capabilities = list(instance.manifest.get("capabilities", []))
          if hasattr(app.state, "module_registry"):
            app.state.module_registry.register(
              name=getattr(instance, "name", module_id),
              instance=instance,
              module_id=module_id,
              capabilities=capabilities,
              priority=10,
            )
        except Exception as e:
          logger.debug(_translate(
            server_state.i18n,
            "core.lifespan.module_registry_skipped",
            "Module registry update skipped: {error}",
            error=str(e)
          ))

    except Exception as e:
      msg = _translate(server_state.i18n, "core.server.memory_error",
        "Error loading Memory modules: {error}", error=str(e))
      logger.error(msg, exc_info=True)

    # === INITIALIZE PLUGIN MODULES (MLX, LlamaCpp, Ollama, etc.) ===
    try:
      logger.info(_translate(
        server_state.i18n,
        "core.lifespan.plugin_init_start",
        "Initializing plugin modules..."
      ))
      plugin_modules = getattr(app.state, 'modules', {})

      for module_name, instance in plugin_modules.items():
        # Skip memory modules (already initialized)
        if module_name in ['memory', 'rag', 'embeddings'] or module_name.startswith('{{NEXE_'):
          continue

        # Initialize if module has initialize method
        if hasattr(instance, 'initialize') and callable(instance.initialize):
          try:
            logger.info(_translate(
              server_state.i18n,
              "core.lifespan.plugin_init_item",
              "Initializing plugin: {module}",
              module=module_name
            ))
            context = {"config": server_state.config, "project_root": server_state.project_root}
            success = await instance.initialize(context)
            if success:
              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.plugin_init_success",
                "✅ {module} initialized successfully",
                module=module_name
              ))
            else:
              logger.warning(_translate(
                server_state.i18n,
                "core.lifespan.plugin_init_false",
                "⚠️  {module} initialization returned False",
                module=module_name
              ))
          except Exception as e:
            logger.error(_translate(
              server_state.i18n,
              "core.lifespan.plugin_init_failed",
              "Failed to initialize {module}: {error}",
              module=module_name,
              error=str(e)
            ), exc_info=True)
    except Exception as e:
      logger.error(_translate(
        server_state.i18n,
        "core.lifespan.plugin_init_error",
        "Error during plugin initialization: {error}",
        error=str(e)
      ), exc_info=True)

    # === AUTO-INGEST KNOWLEDGE FOLDER (FIRST RUN ONLY) ===
    # Auto-ingest happens in two scenarios:
    # 1. During installation (install_nexe.py) - preferred method
    # 2. First server startup if installation failed - fallback only
    #
    # After first ingestion, the marker file prevents re-ingestion on every startup.
    # To manually re-ingest: ./nexe knowledge ingest
    try:
      knowledge_path = server_state.project_root / "knowledge"
      ingested_marker = server_state.project_root / "storage" / ".knowledge_ingested"

      if knowledge_path.exists():
        from core.ingest.ingest_knowledge import ingest_knowledge, SUPPORTED_EXTENSIONS

        files_to_ingest = []
        for ext in SUPPORTED_EXTENSIONS:
          files_to_ingest.extend(knowledge_path.glob(f"**/*{ext}"))
        files_to_ingest.extend(knowledge_path.glob("**/*.pdf"))

        files_to_ingest = [f for f in files_to_ingest if not f.name.startswith('.') and f.name != 'README.md']

        if files_to_ingest:
          # Only auto-ingest if never done before (no marker file)
          if ingested_marker.exists():
            logger.debug(_translate(
              server_state.i18n,
              "core.lifespan.knowledge_already_ingested",
              "Knowledge: Already ingested. Skipping auto-ingest."
            ))
            logger.debug(_translate(
              server_state.i18n,
              "core.lifespan.knowledge_reingest_hint",
              "Knowledge: To re-ingest, use: ./nexe knowledge ingest"
            ))
          else:
            # First run - auto-ingest as fallback if installer didn't do it
            logger.info(_translate(
              server_state.i18n,
              "core.lifespan.knowledge_first_run",
              "Knowledge: First run - auto-ingesting {count} document(s)...",
              count=len(files_to_ingest)
            ))
            success = await ingest_knowledge(knowledge_path, quiet=True)
            if success:
              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.knowledge_ingest_success",
                "Knowledge: Ingestion completed successfully"
              ))
              # Create marker to prevent re-ingestion on next startup
              ingested_marker.touch()
            else:
              logger.warning(_translate(
                server_state.i18n,
                "core.lifespan.knowledge_ingest_errors",
                "Knowledge: Ingestion had some errors"
              ))
        else:
          logger.debug(_translate(
            server_state.i18n,
            "core.lifespan.knowledge_no_docs",
            "Knowledge: No documents to ingest (folder empty or only README)"
          ))
    except Exception as e:
      logger.warning(_translate(
        server_state.i18n,
        "core.lifespan.knowledge_auto_ingest_failed",
        "Knowledge: Auto-ingest failed: {error}",
        error=str(e)
      ))

    bootstrap_ttl = int(os.getenv('BOOTSTRAP_TTL', '30'))
    
    # FIX: Manage bootstrap token via persistent DB (BootstrapTokenManager)
    # Prevent each worker from overwriting the token if a valid one already exists in the DB.
    from core.bootstrap_tokens import set_bootstrap_token, get_bootstrap_token
    
    existing_bootstrap = get_bootstrap_token()
    token_to_display = None
    
    # If it doesn't exist or has expired, generate a new one
    # FIX: Use UTC timestamps to match DB storage
    if not existing_bootstrap or (datetime.now(timezone.utc).timestamp() > existing_bootstrap["expires"]):
      token_to_display = generate_bootstrap_token()
      set_bootstrap_token(token_to_display, ttl_minutes=bootstrap_ttl)
      logger.info(_translate(
        server_state.i18n,
        "core.lifespan.bootstrap_new_token",
        "New master bootstrap token generated and persisted"
      ))
    else:
      token_to_display = existing_bootstrap["token"]
      logger.info(_translate(
        server_state.i18n,
        "core.lifespan.bootstrap_existing_token",
        "Using existing master bootstrap token from DB"
      ))

    nexe_env = os.getenv('NEXE_ENV', 'production').lower()
    # Bootstrap logic is only relevant in development mode
    bootstrap_display = os.getenv('NEXE_BOOTSTRAP_DISPLAY', 'true').lower() == 'true'

    if nexe_env == "development" and bootstrap_display:
      title = _translate(server_state.i18n, "core.server.bootstrap_token_title",
        "NEXE FRAMEWORK INITIALIZATION CODE")
      url_msg = _translate(server_state.i18n, "core.server.bootstrap_token_url",
        "URL: {url}", url="http://localhost:9119")
      expiry_msg = _translate(server_state.i18n, "core.server.bootstrap_token_expiry",
        "Expires in: {minutes} minutes", minutes=bootstrap_ttl)
      copy_msg = _translate(server_state.i18n, "core.server.bootstrap_token_copy_instruction",
        "COPY this code to the browser when prompted")
      single_use_msg = _translate(server_state.i18n, "core.server.bootstrap_token_single_use",
        "This code only works ONCE")

      # FIX: Display token_to_display (persistent)
      print(f"""
+==================================================================+
|                                  |
| {title:<62}|
|                                  |
|   {token_to_display:<58}|
|                                  |
| {expiry_msg:<62}|
| {url_msg:<62}|
|                                  |
| {copy_msg:<62}|
| {single_use_msg:<62}|
|                                  |
+==================================================================+
    """)

    msg = _translate(server_state.i18n, "core.server.bootstrap_token_generated",
      "Bootstrap token persisted to DB (expires in {minutes} min)", minutes=bootstrap_ttl)
    logger.info(msg)

    if hasattr(app.state, 'start_rate_limit_cleanup'):
      import asyncio
      asyncio.create_task(app.state.start_rate_limit_cleanup())
      msg = _translate(server_state.i18n, "core.server.rate_limit_cleanup_started",
        "Phase 3.1: Rate limit cleanup task started")
      logger.info(msg)

    auto_clean_enabled = os.getenv('AUTO_CLEAN_ENABLED', 'false').lower() == 'true'
    if auto_clean_enabled:
      try:
        from personality.auto_clean.core.auto_clean import run_auto_clean

        msg = _translate(server_state.i18n, "core.server.auto_clean_start",
          "Auto-Clean: Running automatic cleanup...")
        logger.info(msg)

        dry_run = os.getenv('AUTO_CLEAN_DRY_RUN', 'true').lower() == 'true'
        result = await run_auto_clean(
          core_root=server_state.project_root,
          dry_run=dry_run
        )

        if result.get("files_cleaned", 0) > 0 or result.get("would_clean", 0) > 0:
          action_key = "core.server.auto_clean_action_would" if dry_run else "core.server.auto_clean_action_cleaned"
          action = _translate(
            server_state.i18n,
            action_key,
            "would clean" if dry_run else "cleaned"
          )
          count = result.get("would_clean", 0) if dry_run else result.get("files_cleaned", 0)
          msg = _translate(server_state.i18n, "core.server.auto_clean_done",
            "Auto-Clean: {count} files {action}", count=count, action=action)
          logger.info(msg)
        else:
          msg = _translate(server_state.i18n, "core.server.auto_clean_nothing",
            "Auto-Clean: Nothing to clean")
          logger.debug(msg)

      except ImportError:
        logger.debug(_translate(
          server_state.i18n,
          "core.lifespan.auto_clean_not_available",
          "Auto-Clean not available"
        ))
      except Exception as e:
        msg = _translate(server_state.i18n, "core.server.auto_clean_error",
          "Auto-Clean error: {error}", error=str(e))
        logger.warning(msg)

    if hasattr(server_state, 'configure_modules_callback'):
      server_state.configure_modules_callback(server_state.api_integrator, server_state.i18n)

    # Final message: Server ready
    logger.info("=" * 70)
    logger.info(_translate(
      server_state.i18n,
      "core.lifespan.server_ready",
      "✅  SERVER.NEXE READY · Listening on http://localhost:9119"
    ))
    logger.info(_translate(
      server_state.i18n,
      "core.lifespan.web_ui_ready",
      "📱 Web UI: http://localhost:9119/ui/"
    ))
    logger.info("=" * 70)

    yield

  except Exception as e:
    msg = _translate(server_state.i18n, "core.server.critical_error",
      "Critical system error: {error}", error=str(e))
    logger.error(msg)
    logger.exception(_translate(
      server_state.i18n,
      "core.lifespan.critical_startup_error",
      "Critical startup error"
    ), exc_info=True)
    raise

  finally:
    msg = _translate(server_state.i18n, "core.server.shutdown_initiated",
      "System shutdown initiated...")
    logger.info(msg)

    try:
      try:
        import httpx
        ollama_url = "http://localhost:11434"

        async with httpx.AsyncClient() as client:
          ps_response = await client.get(f"{ollama_url}/api/ps", timeout=OLLAMA_HEALTH_TIMEOUT)
          if ps_response.status_code == 200:
            loaded_models = ps_response.json().get("models", [])

            if loaded_models:
              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.ollama_unload_start",
                "Unloading {count} Ollama model(s) from RAM...",
                count=len(loaded_models)
              ))

              for model_info in loaded_models:
                model_name = model_info.get("name") or model_info.get("model")
                if model_name:
                  await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model_name, "keep_alive": 0},
                    timeout=OLLAMA_UNLOAD_TIMEOUT
                  )
                  logger.debug(_translate(
                    server_state.i18n,
                    "core.lifespan.ollama_unloaded",
                    "  - Unloaded: {model}",
                    model=model_name
                  ))

              logger.info(_translate(
                server_state.i18n,
                "core.lifespan.ollama_unload_success",
                "Ollama models unloaded successfully"
              ))
            else:
              logger.debug(_translate(
                server_state.i18n,
                "core.lifespan.ollama_unload_none",
                "No Ollama models loaded"
              ))
      except Exception as e:
        logger.debug(_translate(
          server_state.i18n,
          "core.lifespan.ollama_unload_failed",
          "Could not unload Ollama models: {error}",
          error=str(e)
        ))

      _cleanup_child_processes(server_state.i18n)

      if server_state.api_integrator:
        logger.debug(_translate(
          server_state.i18n,
          "core.lifespan.closing_api_integrator",
          "Closing APIIntegrator..."
        ))
        server_state.api_integrator = None

      if server_state.module_manager:
        logger.debug(_translate(
          server_state.i18n,
          "core.lifespan.closing_module_manager",
          "Closing ModuleManager..."
        ))
        server_state.module_manager = None

      if server_state.registry:
        logger.debug(_translate(
          server_state.i18n,
          "core.lifespan.cleaning_registry",
          "Cleaning Registry..."
        ))
        server_state.registry = None

    except Exception as e:
      msg = _translate(server_state.i18n, "core.server.cleanup_error",
        "Error during cleanup: {error}", error=str(e))
      logger.error(msg)

    msg = _translate(server_state.i18n, "core.server.shutdown_goodbye",
      "Nexe 0.8 stopped successfully. See you soon!")
    logger.info(msg)

def get_server_state() -> ServerState:
  """Get the global server state"""
  return server_state
