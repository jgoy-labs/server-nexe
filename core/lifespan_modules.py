"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_modules.py
Description: Module initialisation helpers extracted from lifespan.py.
             Handles memory modules, plugin modules, knowledge auto-ingest,
             and MemoryService v1 startup.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def load_memory_modules(app, server_state, _translate):
    """Load memory modules (Memory, RAG, Embeddings) via ModuleManager."""
    try:
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


async def initialize_plugin_modules(app, server_state):
    """Initialize plugin modules (MLX, LlamaCpp, Ollama, etc.)."""
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


async def auto_ingest_knowledge(server_state):
    """Auto-ingest knowledge/ folder on first run only."""
    try:
        nexe_env = os.getenv("NEXE_ENV", "production").lower()
        auto_ingest_enabled = os.getenv("NEXE_AUTO_INGEST_KNOWLEDGE", "true").lower() == "true"

        if nexe_env in ("test", "testing") or not auto_ingest_enabled:
            logger.debug(
                "Knowledge: Auto-ingest disabled (NEXE_ENV=%s, NEXE_AUTO_INGEST_KNOWLEDGE=%s)",
                nexe_env,
                auto_ingest_enabled,
            )
            return

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


async def start_memory_service_v1(app, server_state):
    """Initialize MemoryService v1 + DreamingCycle background task.

    NOTE: MemoryService is now primarily initialized by MemoryModule
    (memory/memory/module.py) with absolute paths. This function reuses
    that instance if available, avoiding double initialization (BUG-08).
    """
    try:
        # Try to reuse the instance already created by MemoryModule
        from memory.memory.module import get_memory_service
        existing = get_memory_service()
        if existing is not None:
            app.state.memory_service = existing
            logger.info("MemoryService v1: reusing instance from MemoryModule")
        else:
            # Fallback: create with absolute path
            from memory.memory.memory_service import MemoryService
            project_root = server_state.project_root
            if project_root:
                from pathlib import Path
                db_path = Path(project_root) / "storage" / "vectors" / "memory_v1.db"
                qdrant_path = str(Path(project_root) / "storage" / "vectors" / "qdrant_local")
                memory_service = MemoryService(db_path=db_path, qdrant_path=qdrant_path)
            else:
                memory_service = MemoryService()
            await memory_service.initialize()
            app.state.memory_service = memory_service
            logger.info("MemoryService v1 initialized (standalone, absolute path)")

        # DreamingCycle as independent background task
        ms = app.state.memory_service
        if ms:
            try:
                from memory.memory.workers.dreaming_cycle import DreamingCycle
                dreaming = DreamingCycle(
                    store=ms._store,
                    vector_index=ms._vector_index,
                )
                server_state._dreaming_task = asyncio.create_task(dreaming.run())
                server_state._dreaming_cycle = dreaming
                logger.info("DreamingCycle background task started")
            except Exception as e:
                logger.warning("DreamingCycle not started (non-fatal): %s", e)

    except Exception as e:
        logger.warning("MemoryService v1 not available (non-fatal): %s", e)
        app.state.memory_service = None
