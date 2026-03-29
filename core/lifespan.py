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
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI

from personality.integration import APIIntegrator
from .config import load_config
from .lifespan_services import (
    _auto_start_services,
    OLLAMA_HEALTH_TIMEOUT,
    OLLAMA_UNLOAD_TIMEOUT,
    QDRANT_HEALTH_TIMEOUT,
)
from .lifespan_tokens import generate_bootstrap_token, setup_bootstrap_tokens
from .lifespan_ollama import cleanup_ollama_startup, cleanup_ollama_shutdown

# Force offline mode for HuggingFace — server must work without internet
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

logger = logging.getLogger(__name__)


from core.server.helpers import translate as _translate


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
      "Nexe 0.8 - Modular AI System")
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
      logger.warning("Encryption init failed (non-fatal): %s", e)
      server_state.crypto_provider = None

    # Auto-start services (Qdrant, Ollama) if not running
    await _auto_start_services(server_state.config, server_state.project_root, server_state)

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

    # Cleanup Ollama models from previous sessions
    await cleanup_ollama_startup(server_state, _translate, OLLAMA_HEALTH_TIMEOUT, OLLAMA_UNLOAD_TIMEOUT)

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
      if not server_state.module_manager:
        logger.warning("ModuleManager not available - skipping memory module loading")
        raise RuntimeError("ModuleManager not available")

      msg = _translate(server_state.i18n, "core.server.loading_memory",
        "Loading Memory modules (Memory, RAG, Embeddings)...")
      logger.info(msg)

      loaded = await server_state.module_manager.load_memory_modules(config=server_state.config)

      msg = _translate(server_state.i18n, "core.server.memory_loaded",
        "Memory modules loaded: {count}", count=len(loaded))
      logger.info(msg)

      for id_res, instance in loaded.items():
        logger.info("  - %s (%s)", instance.name, id_res)
        try:
          from core.metrics.registry import set_module_health
          health = instance.get_health()
          set_module_health(instance.name, health.get("status", "unhealthy"))
        except Exception as e:
          logger.debug("Module health update skipped: %s", e)

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
          logger.debug("Module registry update skipped: %s", e)

    except Exception as e:
      msg = _translate(server_state.i18n, "core.server.memory_error",
        "Error loading Memory modules: {error}", error=str(e))
      logger.error(msg, exc_info=True)

    # === INITIALIZE PLUGIN MODULES (MLX, LlamaCpp, Ollama, etc.) ===
    try:
      logger.info("Initializing plugin modules...")
      plugin_modules = getattr(app.state, 'modules', {})

      for module_name, instance in plugin_modules.items():
        # Skip memory modules (already initialized)
        if module_name in ['memory', 'rag', 'embeddings'] or module_name.startswith('{{NEXE_'):
          continue

        # Initialize if module has initialize method
        if hasattr(instance, 'initialize') and callable(instance.initialize):
          try:
            logger.info(f"Initializing plugin: {module_name}")
            context = {"config": server_state.config, "project_root": server_state.project_root}
            success = await instance.initialize(context)
            if success:
              logger.info(f"  {module_name} initialized successfully")
            else:
              logger.warning(f"  {module_name} initialization returned False")
          except Exception as e:
            logger.error(f"Failed to initialize {module_name}: {e}", exc_info=True)
    except Exception as e:
      logger.error(f"Error during plugin initialization: {e}", exc_info=True)

    # === AUTO-INGEST KNOWLEDGE FOLDER (FIRST RUN ONLY) ===
    try:
      nexe_env = os.getenv("NEXE_ENV", "production").lower()
      auto_ingest_enabled = os.getenv("NEXE_AUTO_INGEST_KNOWLEDGE", "true").lower() == "true"

      if nexe_env in ("test", "testing") or not auto_ingest_enabled:
        logger.debug(
          "Knowledge: Auto-ingest disabled (NEXE_ENV=%s, NEXE_AUTO_INGEST_KNOWLEDGE=%s)",
          nexe_env,
          auto_ingest_enabled,
        )
      else:
        knowledge_path = server_state.project_root / "knowledge"
        _nexe_lang = os.getenv("NEXE_LANG", "ca")
        lang_path = knowledge_path / _nexe_lang
        if lang_path.is_dir():
          knowledge_path = lang_path
        ingested_marker = server_state.project_root / "storage" / ".knowledge_ingested"

        if knowledge_path.exists():
          from core.ingest.ingest_knowledge import ingest_knowledge, SUPPORTED_EXTENSIONS

          files_to_ingest = []
          for ext in SUPPORTED_EXTENSIONS:
            files_to_ingest.extend(knowledge_path.glob(f"**/*{ext}"))
          files_to_ingest.extend(knowledge_path.glob("**/*.pdf"))

          files_to_ingest = [f for f in files_to_ingest if not f.name.startswith('.')]

          if files_to_ingest:
            # Only auto-ingest if never done before (no marker file)
            if ingested_marker.exists():
              logger.debug("Knowledge: Already ingested. Skipping auto-ingest.")
              logger.debug("Knowledge: To re-ingest, use: ./nexe knowledge ingest")
            else:
              # First run - auto-ingest as fallback if installer didn't do it
              logger.info("Knowledge: First run - auto-ingesting %d document(s)...", len(files_to_ingest))
              success = await ingest_knowledge(knowledge_path, quiet=True)
              if success:
                logger.info("Knowledge: Ingestion completed successfully")
                # Create marker to prevent re-ingestion on next startup
                ingested_marker.touch()
              else:
                logger.warning("Knowledge: Ingestion had some errors")
          else:
            logger.debug("Knowledge: No documents to ingest (folder empty or only README)")
    except Exception as e:
      logger.warning("Knowledge: Auto-ingest failed: %s", str(e))

    # Bootstrap tokens
    setup_bootstrap_tokens(server_state, _translate)

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

    # Session cleanup background task (N-5)
    try:
      from plugins.web_ui_module.api.routes import start_session_cleanup_task
      web_ui = app.state.modules.get("web_ui_module")
      if web_ui and hasattr(web_ui, 'session_manager'):
        start_session_cleanup_task(web_ui.session_manager)
        logger.info("Session cleanup task started (runs every hour)")
      else:
        logger.warning("web_ui_module not loaded — session cleanup task skipped")
    except Exception as e:
      logger.warning("Could not start session cleanup task: %s", e)

    # Final message: Server ready
    _srv_cfg = server_state.config.get("core", {}).get("server", {})
    _nexe_url = os.environ.get("NEXE_API_BASE_URL", f"http://{_srv_cfg.get('host', '127.0.0.1')}:{_srv_cfg.get('port', 9119)}")
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

    try:
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

      _stop_process(server_state.qdrant_process, "Qdrant")
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
