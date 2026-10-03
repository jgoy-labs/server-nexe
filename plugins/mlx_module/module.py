"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/mlx_module/module.py
Description: Nexe module for MLX (Apple Silicon). Adaptation of the original MLXChatNode.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from core.modules.protocol import ModuleMetadata, HealthResult, HealthStatus
from .core.chat import MLXChatNode
from .core.config import MLXConfig

logger = logging.getLogger(__name__)

class MLXModule:
    """
    Nexe engine for MLX.
    Implements the NexeModule Protocol for Apple Silicon.
    """

    def __init__(self) -> None:
        self._node: Optional[MLXChatNode] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._router = None
        # Lifecycle state for /status and health_check.
        # "uninitialized"  → before initialize() runs
        # "ready"          → model loaded and chat-capable
        # "not_configured" → NEXE_MLX_MODEL unset, server.toml empty, no auto-
        #                    discovered model. Plugin stays at registry so
        #                    restart_sidecar can re-activate it after
        #                    the wizard completes.
        # "no_metal"       → Metal/Apple Silicon not available (catastrophic
        #                    on the local box, plugin should be popped).
        # "error"          → unexpected exception during init.
        self._state: str = "uninitialized"

    @property
    def metadata(self) -> ModuleMetadata:
        """Return static module metadata for the MLX engine."""
        return ModuleMetadata(
            name="mlx_module",
            version="1.0.0-beta",
            description="Ultra-optimized inference engine for Apple Silicon (MLX)",
            author="Jordi Goy",
            module_type="local_llm_option",
            quadrant="core"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialize via Nexe Launcher."""
        if self._initialized:
            return True
        async with self._init_lock:
            if self._initialized:
                return True

            # Always initialize router
            self._init_router()

            if not MLXConfig.is_metal_available():
                logger.error("MLXModule: Metal is not available. Cannot initialize MLX.")
                logger.info("To use MLX: Ensure you're running on Apple Silicon with Metal support")
                self._state = "no_metal"
                return False  # catastrophic — loader will pop from registry

            try:
                mlx_config = MLXConfig.from_env()

                # Distinguish "no model configured" (recoverable
                # via restart_sidecar after wizard) from real validation failure
                # (path set but broken). Empty path is the wizard-not-done case.
                if not mlx_config.model_path:
                    logger.info(
                        "MLXModule: no model configured (NEXE_MLX_MODEL unset, "
                        "server.toml empty, auto-discover found nothing). "
                        "Plugin stays at registry with state=not_configured; "
                        "restart_sidecar will re-activate it after the wizard "
                        "completes."
                    )
                    self._state = "not_configured"
                    self._node = None  # do NOT create MLXChatNode with empty config
                    self._initialized = False
                    return True  # keep plugin at registry — see lifespan_modules.py

                if not mlx_config.validate():
                    logger.error(
                        "MLXModule: Configuration invalid for model_path=%s. "
                        "Check NEXE_MLX_MODEL.",
                        mlx_config.model_path,
                    )
                    logger.info("Expected: NEXE_MLX_MODEL should point to a valid MLX model directory")
                    self._state = "error"
                    return False  # path set but broken — loader pops

                self._node = MLXChatNode(config=mlx_config)
                self._initialized = True
                self._state = "ready"

                logger.info(
                    "MLXModule initialized successfully (model=%s)",
                    mlx_config.model_path,
                )
                return True
            except Exception as e:
                logger.error(f"Failed to initialize MLXModule: {e}")
                self._state = "error"
                return False

    def _init_router(self):
        """Create the MLX API router from api/routes.py."""
        from .api.routes import create_router
        self._router = create_router(self)

    def get_router(self) -> APIRouter:
        """Return the FastAPI router for MLX endpoints."""
        return self._router

    def get_router_prefix(self) -> str:
        """Return the URL prefix for MLX routes."""
        return "/mlx"

    async def is_model_loaded(self, model_name: str = "") -> bool:
        """Checks whether the MLX model is loaded in memory."""
        if not self._node:
            return False
        try:
            stats = self._node.get_pool_stats()
            return stats.get("model_loaded", False)
        except Exception:
            return False

    def get_context_window(self) -> "Optional[int]":
        """#965: the engine's own answer to "how many tokens fit", in tokens.

        For MLX that is `max_kv_size`, which `auto_max_kv_size()` already sizes
        from this machine's RAM AND the real weights of the loaded model — the
        most informed number any engine here can give. Recomputed on every
        model switch (`from_env()`), so it follows the model that is actually
        loaded, not the one configured at boot.

        The model's own limit is already folded in: `auto_max_kv_size()` caps
        the KV budget by `max_position_embeddings`, so every consumer — the
        prompt truncator, the prompt cache, the RAM guard and this reporter —
        sees the same number. An explicit `NEXE_MLX_MAX_KV_SIZE` bypasses that
        cap by design (the user's word wins) and is reported as set.

        Returns None when there is no node yet: the caller falls back to the
        default window rather than guessing on our behalf.
        """
        if self._node is None:
            return None
        try:
            return int(self._node.config.max_kv_size)
        except (AttributeError, TypeError, ValueError):
            return None

    def switch_model_by_path(self, local_path) -> bool:
        """F-D block 5: the module's own answer to "load this model instead".

        Same shape as get_context_window (#965): the caller names what it wants
        and the module, which owns its config, does it. The env dance that builds
        that config used to live in the web UI (_switch_mlx_model) and imported
        MLXConfig from this plugin — code the core could not take over without
        importing a plugin, which the layering gate forbids.

        runtime_state.set_override (not os.environ) so MLXConfig.from_env() sees
        the new path without mutating the process env and racing concurrent
        requests; the previous value is restored either way.

        Returns True when a swap really happened (see switch_model).
        """
        from pathlib import Path as _Path

        from core.runtime_state import get_override, set_override

        from plugins.mlx_module.core.config import MLXConfig

        # Validate BEFORE mutating any state (FD-S4, 8 GB M1 2026-07-23): the
        # models dir held a grouping folder `mlx/` with no config.json, a bare
        # .exists() let it through, the module switched its global config to the
        # ghost path, the RAM guard estimated a model that did not exist and the
        # user got a raw FileNotFoundError. A *failed* gate fell through silently
        # too: the user kept chatting with the OLD model with no signal at all.
        # ValueError with "not found" is deliberate — engine_error_to_http maps
        # it to a clean 404 instead of the engine loop swallowing it as "this
        # engine failed, try the next".
        _path = _Path(local_path)
        if not (_path / "config.json").is_file():
            raise ValueError(
                f"Model '{_path.name}' not found: no MLX model (config.json) "
                f"under the models directory"
            )

        _prev = get_override("NEXE_MLX_MODEL")
        try:
            set_override("NEXE_MLX_MODEL", str(local_path))
            new_config = MLXConfig.from_env()
        finally:
            set_override("NEXE_MLX_MODEL", _prev)

        switched = self.switch_model(new_config)
        if switched:
            logger.info("MLX model switched to: %s", local_path)
        return switched

    def switch_model(self, new_config: "MLXConfig") -> bool:
        """Hot-swap the active model to `new_config` if it differs.

        Public entry point so web_ui never reaches into the node's class-level
        singletons (_model/_config). Returns True if a swap happened, False if
        there is no node yet or the model path is unchanged (B073).
        """
        if self._node is None:
            return False
        if self._node.config.model_path == new_config.model_path:
            return False
        # Deep belt (2026-07-23): validate BEFORE mutating state. Without it a
        # caller could point config.model_path at a ghost directory and every
        # later load (and the RAM guard's estimate) would chase a model that
        # does not exist. MLXConfig.validate() existed and nobody called it
        # here.
        if hasattr(new_config, "validate") and not new_config.validate():
            logger.error(
                "MLXModule.switch_model: refusing invalid config: %s",
                new_config.model_path,
            )
            return False
        self._node.apply_config(new_config)
        logger.info("MLXModule: model switched to %s", new_config.model_path)
        return True

    def can_continue(self, model_name: Optional[str] = None) -> bool:
        """C4.6 (FD-S6): this engine can resume a truncated answer mid-sentence
        (`continue_final`), on the text path and — C4.6-a-vlm — on the VLM
        path too (`continue_final_message` through `mlx_vlm`'s template).
        `model_name` is ignored: MLX runs the one model it has loaded."""
        return bool(self._initialized and self._node is not None)

    def can_see_images(self) -> bool:
        """#1035: whether the model this engine runs can read an image.

        The same check `chat` makes to take the VLM path (the loaded model's
        config.json). Asked of a fallback, which answers with its own model: a
        text model given a turn with an image would answer as if it saw it."""
        if not (self._initialized and self._node is not None):
            return False
        from plugins.mlx_module.core import model_loader

        return bool(model_loader._detect_vlm_capability(getattr(self._node.config, "model_path", "")))

    async def chat(
        self, messages: List[Dict[str, str]], system: str = "",
        session_id: str = "default", stream_callback=None, **kwargs,
    ):
        """Main chat method using MLX."""
        if not self._initialized or not self._node:
            raise RuntimeError("MLXModule not initialized")

        inputs = {
            "system": system,
            "messages": messages,
            "session_id": session_id,
            "stream_callback": stream_callback,
            **kwargs,
        }

        return await self._node.execute(inputs)

    async def health_check(self) -> HealthResult:
        """Check MLX module health by querying the inference pool stats."""
        # Report not_configured explicitly so /status is
        # actionable (UI can show "Run wizard to install a model") instead
        # of the generic "Module not initialized".
        if self._state == "not_configured":
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="not_configured: NEXE_MLX_MODEL unset, no MLX model auto-discovered",
                details={"state": self._state},
            )
        if not self._initialized or self._node is None:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="Module not initialized",
                details={"state": self._state},
            )

        try:
            stats = self._node.get_pool_stats()
            return HealthResult(
                status=HealthStatus.HEALTHY,
                message="MLX motor active",
                details=stats
            )
        except Exception as e:
            return HealthResult(status=HealthStatus.DEGRADED, message=str(e))

    async def shutdown(self) -> None:
        """Cleanup logic"""
        if self._node:
            self._node.reset_model()
        self._initialized = False

    def get_info(self) -> Dict[str, Any]:
        """Return module metadata and current cache statistics."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "initialized": self._initialized,
            "cache_stats": self._node.get_pool_stats() if self._node else {}
        }
