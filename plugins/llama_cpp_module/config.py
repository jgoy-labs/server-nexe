# -*- coding: utf-8 -*-
"""
LlamaCppConfig - Centralized configuration for llama-cpp-python.

All options can be configured via environment variables:
- NEXE_LLAMA_CPP_MODEL: Path to the .gguf file
- NEXE_LLAMA_CPP_N_CTX: Context window (default: 8192)
- NEXE_LLAMA_CPP_N_BATCH: Batch size for generation (default: 512) - HIGHER = FASTER
- NEXE_LLAMA_CPP_GPU_LAYERS: GPU layers, -1=all (default: -1)
- NEXE_LLAMA_CPP_THREADS: CPU threads (default: 8)
- NEXE_LLAMA_CPP_MAX_SESSIONS: Max active sessions (default: 1)
- NEXE_LLAMA_CPP_CHAT_FORMAT: Chat format (default: gemma)
- NEXE_LLAMA_CPP_USE_MLOCK: Keep model in RAM (default: true)
- NEXE_LLAMA_CPP_USE_MMAP: Memory-map the model (default: true)
- NEXE_LLAMA_CPP_FLASH_ATTN: Flash attention (default: true)

Part of: PLA_OPTIMITZACIO_LLM_MODULAR v1.9 - PHASE 2
"""
import os
from dataclasses import dataclass
import logging

from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)


@dataclass
class LlamaCppConfig:
    """
    Configuration for llama-cpp-python.

    Attributes:
        model_path: Absolute path to the .gguf file
        n_ctx: Context window in tokens (conservative for 27B)
        n_batch: Batch size for generation (512-2048, higher = faster)
        n_gpu_layers: Layers to load on GPU (-1 = all, Metal)
        n_threads: CPU threads for inference
        max_sessions: Max active sessions (LRU eviction)
        chat_format: Chat template format (gemma, llama-2, chatml, mistral)
        use_mlock: Keep model in RAM (avoid swapping)
        use_mmap: Memory-map the model (more efficient)
        flash_attn: Flash attention (faster if supported)
    """

    model_path: str = ""
    n_ctx: int = 8192
    n_batch: int = 512  # IMPORTANT: higher = more tok/s
    n_gpu_layers: int = -1
    n_threads: int = 8
    max_sessions: int = 1  # Option B: conservative, scalable if needed
    chat_format: str = "gemma"
    use_mlock: bool = True
    use_mmap: bool = True
    flash_attn: bool = True

    def __post_init__(self):
        """Validate configuration after creation."""
        if not self.model_path:
            logger.warning(
                t_modular(
                    "llama_cpp_module.config.model_path_empty",
                    "LlamaCppConfig: model_path is empty. Configure NEXE_LLAMA_CPP_MODEL or pass model_path."
                )
            )
        # Expand ~ to home directory
        if self.model_path.startswith("~"):
            self.model_path = os.path.expanduser(self.model_path)
        # Resolve relative paths based on project root
        elif not os.path.isabs(self.model_path):
            from pathlib import Path
            project_root = Path(__file__).parents[2]  # From plugins/llama_cpp_module/ to project root
            self.model_path = str(project_root / self.model_path)

    @classmethod
    def from_env(cls) -> "LlamaCppConfig":
        """
        Load configuration from environment variables.

        Returns:
            LlamaCppConfig with environment values or defaults.
        """
        config = cls(
            model_path=os.getenv("NEXE_LLAMA_CPP_MODEL", ""),
            n_ctx=int(os.getenv("NEXE_LLAMA_CPP_N_CTX", "8192")),
            n_batch=int(os.getenv("NEXE_LLAMA_CPP_N_BATCH", "512")),
            n_gpu_layers=int(os.getenv("NEXE_LLAMA_CPP_GPU_LAYERS", "-1")),
            n_threads=int(os.getenv("NEXE_LLAMA_CPP_THREADS", "8")),
            max_sessions=int(os.getenv("NEXE_LLAMA_CPP_MAX_SESSIONS", "1")),
            chat_format=os.getenv("NEXE_LLAMA_CPP_CHAT_FORMAT", "gemma"),
            use_mlock=os.getenv("NEXE_LLAMA_CPP_USE_MLOCK", "true").lower() == "true",
            use_mmap=os.getenv("NEXE_LLAMA_CPP_USE_MMAP", "true").lower() == "true",
            flash_attn=os.getenv("NEXE_LLAMA_CPP_FLASH_ATTN", "true").lower() == "true",
        )

        model_short = config.model_path[-40:] if config.model_path else "(empty)"
        logger.info(
            t_modular(
                "llama_cpp_module.config.loaded",
                "LlamaCppConfig loaded: model={model}, n_ctx={n_ctx}, n_batch={n_batch}, gpu_layers={gpu_layers}, "
                "threads={threads}, mlock={mlock}, mmap={mmap}, flash_attn={flash_attn}",
                model=model_short,
                n_ctx=config.n_ctx,
                n_batch=config.n_batch,
                gpu_layers=config.n_gpu_layers,
                threads=config.n_threads,
                mlock=config.use_mlock,
                mmap=config.use_mmap,
                flash_attn=config.flash_attn,
            )
        )

        return config

    def validate(self) -> bool:
        """
        Validate that the configuration is correct.

        Returns:
            True if config is valid, False otherwise.
        """
        if not self.model_path:
            logger.error(
                t_modular(
                    "llama_cpp_module.config.model_path_required",
                    "LlamaCppConfig: model_path is required"
                )
            )
            return False

        if not os.path.exists(self.model_path):
            logger.error(
                t_modular(
                    "llama_cpp_module.config.model_path_missing",
                    "LlamaCppConfig: model_path does not exist: {path}",
                    path=self.model_path
                )
            )
            return False

        if self.n_ctx < 512:
            logger.error(
                t_modular(
                    "llama_cpp_module.config.n_ctx_min",
                    "LlamaCppConfig: n_ctx minimum is 512"
                )
            )
            return False

        if self.max_sessions < 1:
            logger.error(
                t_modular(
                    "llama_cpp_module.config.max_sessions_min",
                    "LlamaCppConfig: max_sessions minimum is 1"
                )
            )
            return False

        valid_formats = {"gemma", "llama-2", "chatml", "mistral", "alpaca"}
        if self.chat_format not in valid_formats:
            logger.warning(
                t_modular(
                    "llama_cpp_module.config.chat_format_unrecognized",
                    "LlamaCppConfig: chat_format '{chat_format}' not recognized. Valid formats: {valid_formats}",
                    chat_format=self.chat_format,
                    valid_formats=", ".join(sorted(valid_formats))
                )
            )

        return True
