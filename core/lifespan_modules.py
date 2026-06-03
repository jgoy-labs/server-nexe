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
from pathlib import Path

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

        for module_name, instance in list(plugin_modules.items()):
            # Skip memory modules (already initialized)
            if module_name in ['memory', 'rag', 'embeddings'] or module_name.startswith('{{NEXE_'):
                continue

            # Initialize if module has initialize method
            if hasattr(instance, 'initialize') and callable(instance.initialize):
                try:
                    logger.info(f"Initializing plugin: {module_name}")
                    context = {"config": server_state.config, "project_root": server_state.project_root}
                    success = await instance.initialize(context)  # pyright: ignore[reportGeneralTypeIssues]  # plugin protocol: initialize() is awaitable (duck-typed)
                    if success:
                        logger.info(f"  {module_name} initialized successfully")
                    else:
                        logger.warning(
                            f"  {module_name} initialization returned False — "
                            "removing from loaded modules"
                        )
                        plugin_modules.pop(module_name, None)
                        # Note: plugin_modules is a reference to app.state.modules,
                        # so this also cleans up app.state.modules automatically
                except Exception as e:
                    logger.error(f"Failed to initialize {module_name}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error during plugin initialization: {e}", exc_info=True)


def _auto_ingest_is_disabled(nexe_env: str, auto_ingest_enabled: bool) -> bool:
    """Return True if auto-ingest should be skipped (test env or disabled via env var)."""
    return nexe_env in ("test", "testing") or not auto_ingest_enabled


def _resolve_knowledge_path_for_auto_ingest(project_root) -> Path:
    """Resolve the effective knowledge path, applying lang subdirectory if present."""
    knowledge_path = project_root / "knowledge"
    _nexe_lang = os.getenv("NEXE_LANG", "en")
    lang_path = knowledge_path / _nexe_lang
    if lang_path.is_dir():
        knowledge_path = lang_path
    return knowledge_path


def _collect_files_to_ingest(knowledge_path) -> list:
    """Collect all supported document files under knowledge_path."""
    from core.ingest.ingest_knowledge import SUPPORTED_EXTENSIONS
    files_to_ingest: list = []
    for ext in SUPPORTED_EXTENSIONS:
        files_to_ingest.extend(knowledge_path.glob(f"**/*{ext}"))
    files_to_ingest.extend(knowledge_path.glob("**/*.pdf"))
    return [f for f in files_to_ingest if not f.name.startswith('.')]


async def _check_needs_reingest(ingested_marker) -> bool:
    """Return True if re-ingest is needed despite marker existing (BUG #20).

    Verifies Qdrant has sufficient content; clears the marker if re-ingest is needed.
    """
    try:
        from memory.memory.api.v1 import get_memory_api as _get_v1_api
        _api = await _get_v1_api()
        if await _api.collection_exists("nexe_documentation"):
            doc_count = await _api.count("nexe_documentation")
            if doc_count >= 10:
                logger.debug("Knowledge: Already ingested (%d docs). Skipping.", doc_count)
                return False
            logger.warning("Knowledge: Marker exists but only %d docs in Qdrant — re-ingesting", doc_count)
        else:
            logger.warning("Knowledge: Marker exists but collection missing — re-ingesting")
    except Exception as e:
        logger.warning("Knowledge: Could not verify Qdrant state (%s) — re-ingesting", e)

    ingested_marker.unlink(missing_ok=True)
    return True


async def auto_ingest_knowledge(server_state):
    """Auto-ingest knowledge/ folder on first run only."""
    try:
        # prefer SidecarConfig.is_production over direct NEXE_ENV,
        # fallback a os.getenv per backward-compat. Reconstruim la string `nexe_env`
        # només per al log (vegeu _auto_ingest_is_disabled).
        # in sidecar mode use SidecarConfig.auto_ingest_knowledge
        auto_ingest_enabled = os.getenv("NEXE_AUTO_INGEST_KNOWLEDGE", "true").lower() == "true"
        try:
            from core.sidecar_config import get_sidecar_config
            cfg = get_sidecar_config()
            nexe_env = "production" if cfg.is_production else "development"
            if cfg.is_sidecar:
                auto_ingest_enabled = cfg.auto_ingest_knowledge
        except Exception as exc:
            logger.debug(
                "F2.3 part 2: SidecarConfig unavailable in auto_ingest_knowledge, "
                "falling back to NEXE_ENV: %s",
                exc,
            )
            nexe_env = os.getenv("NEXE_ENV", "production").lower()

        if _auto_ingest_is_disabled(nexe_env, auto_ingest_enabled):
            logger.debug(
                "Knowledge: Auto-ingest disabled (NEXE_ENV=%s, NEXE_AUTO_INGEST_KNOWLEDGE=%s)",
                nexe_env,
                auto_ingest_enabled,
            )
            return

        knowledge_path = _resolve_knowledge_path_for_auto_ingest(server_state.project_root)
        ingested_marker = server_state.project_root / "storage" / ".knowledge_ingested"

        if not knowledge_path.exists():
            return

        from core.ingest.ingest_knowledge import ingest_knowledge
        files_to_ingest = _collect_files_to_ingest(knowledge_path)

        if not files_to_ingest:
            logger.debug("Knowledge: No documents to ingest (folder empty or only README)")
            return

        # BUG #20: Check marker AND verify Qdrant has content.
        if ingested_marker.exists():
            needs_reingest = await _check_needs_reingest(ingested_marker)
            if not needs_reingest:
                return

        # First run or re-ingest needed — ingest knowledge
        logger.info("Knowledge: Auto-ingesting %d document(s)...", len(files_to_ingest))
        # F7: explicit target_collection — auto-ingest at startup
        # writes corporate know-how to nexe_documentation, never
        # to the user_knowledge collection.
        success = await ingest_knowledge(
            knowledge_path,
            quiet=True,
            target_collection="nexe_documentation",
        )
        if success:
            logger.info("Knowledge: Ingestion completed successfully")
            ingested_marker.touch()
        else:
            logger.warning("Knowledge: Ingestion had some errors")
    except Exception as e:
        logger.warning("Knowledge: Auto-ingest failed: %s", str(e))


async def _shutdown_memory_service(app, server_state) -> None:
    """Graceful shutdown of MemoryService v1 and DreamingCycle."""
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


async def _startup_module_discovery(app, server_state, _translate) -> None:
    """Discover modules via ModuleManager and populate server_state.registry."""
    try:
        if not server_state.module_manager:
            msg = _translate(server_state.i18n, "core.server.module_manager_unavailable", "ModuleManager not available")
            logger.warning(msg)
            return

        server_state.registry = server_state.module_manager.registry
        msg = _translate(server_state.i18n, "core.server.module_manager_ready", "ModuleManager already initialized")
        logger.info(msg)

        discovered = await server_state.module_manager.discover_modules()
        total_modules = list(server_state.module_manager._modules.keys())

        try:
            cycle_warnings = server_state.module_manager.get_cycle_warnings()
        except Exception:
            # AP-G01: log diagnòstic sense canviar el fallback (cap warning de cicle)
            logger.debug("Could not read module cycle warnings", exc_info=True)
            cycle_warnings = []
        for cycle_chain in cycle_warnings:
            logger.warning("[WARN] Module dependency cycle: %s", cycle_chain)

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

    except Exception as e:
        msg = _translate(server_state.i18n, "core.server.module_manager_error",
            "Error with ModuleManager: {error}", error=str(e))
        logger.warning(msg)


async def start_memory_service_v1(app, server_state) -> None:
    """Initialize MemoryService v1 + DreamingCycle background task.

    NOTE: MemoryService is now primarily initialized by MemoryModule
    (memory/memory/module.py) with absolute paths. This function reuses
    that instance if available, avoiding double initialization.
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
            # Defensive init so the logger.info below can reference qdrant_path
            # safely when project_root is falsy (pyright reportPossiblyUnbound).
            qdrant_path: str = "default"
            if project_root:
                from pathlib import Path
                # in sidecar mode derive BOTH db_path and
                # qdrant_path from the canonical sidecar vectors_dir so
                # MemoryService, MemoryModule, and MemoryAPI share the same
                # on-disk location. The previous hardcoded
                # `project_root / storage / vectors` resolved to
                # /sidecar/app/storage/vectors while MemoryAPI used
                # data_dir/vectors (= /sidecar/vectors) — splitting qdrant
                # collections silently and breaking RAG.
                #
                # Guarded with is_sidecar because get_sidecar_config()
                # returns a defaulted config in dev/test (pointing at
                # ~/.nexe/data) which is wrong when project_root is a
                # tmp_path test fixture.
                try:
                    from core.sidecar_config import get_sidecar_config
                    _sc = get_sidecar_config()
                    if getattr(_sc, "is_sidecar", False):
                        vectors_dir = Path(_sc.vectors_dir)
                    else:
                        vectors_dir = Path(project_root) / "storage" / "vectors"
                except Exception:
                    # AP-G01: log diagnòstic sense canviar el fallback al path per defecte
                    logger.debug("SidecarConfig unavailable resolving vectors_dir", exc_info=True)
                    vectors_dir = Path(project_root) / "storage" / "vectors"
                vectors_dir.mkdir(parents=True, exist_ok=True)
                db_path = vectors_dir / "memory_v1.db"
                qdrant_path = str(vectors_dir)
                memory_service = MemoryService(db_path=db_path, qdrant_path=qdrant_path)
            else:
                memory_service = MemoryService()
            await memory_service.initialize()
            app.state.memory_service = memory_service
            logger.info(
                "MemoryService v1 initialized (standalone, qdrant=%s)",
                qdrant_path if project_root else "default",
            )

        # DreamingCycle as independent background task
        ms = app.state.memory_service
        if ms:
            try:
                from memory.memory.workers.dreaming_cycle import DreamingCycle
                # Embedder is required for _sync_vector_index — without one
                # DreamingCycle runs but episodic entries never reach Qdrant.
                # SimpleEmbedder is a singleton, so this reuses any instance
                # that might already have been warmed up elsewhere.
                # Load in a thread: first-use TextEmbedding download + ONNX
                # init can block the event loop 5-30 s on slow networks /
                # cold caches, which would stall the lifespan startup.
                embedder = None
                try:
                    from memory.embeddings.simple_embedder import get_embedder
                    from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL
                    embedder = await asyncio.to_thread(
                        get_embedder, DEFAULT_EMBEDDING_MODEL
                    )
                except Exception as e:
                    logger.warning(
                        "DreamingCycle embedder unavailable — vector sync "
                        "will be skipped (non-fatal): %s", e,
                    )
                # do NOT start DreamingCycle without an embedder.
                # The previous code instantiated and ran the cycle anyway, which
                # ingested memory entries to SQLite but never to Qdrant —
                # silently breaking semantic search (RAG returned 0 results).
                # When the user completes the wizard and the embedder is
                # downloaded, restart_sidecar will start a new lifespan with
                # embedder loaded and DreamingCycle will run normally.
                if embedder is None:
                    logger.warning(
                        "DreamingCycle NOT started (embedder=missing). "
                        "Semantic search disabled until the fastembed model "
                        "is downloaded via the installer wizard (F5.4 Bug A). "
                        "Restart the app after the wizard completes to enable "
                        "DreamingCycle and vector sync."
                    )
                else:
                    dreaming = DreamingCycle(
                        store=ms._store,
                        vector_index=ms._vector_index,
                        embedder=embedder,
                    )
                    server_state._dreaming_task = asyncio.create_task(dreaming.run())
                    server_state._dreaming_cycle = dreaming
                    logger.info("DreamingCycle background task started (embedder=ready)")
            except Exception as e:
                logger.warning("DreamingCycle not started (non-fatal): %s", e)

    except Exception as e:
        logger.warning("MemoryService v1 not available (non-fatal): %s", e)
        app.state.memory_service = None
