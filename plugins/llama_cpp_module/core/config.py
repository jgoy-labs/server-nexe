# -*- coding: utf-8 -*-
"""
LlamaCppConfig - Centralised configuration for llama-cpp-python.

All options can be configured via environment variables:
- NEXE_LLAMA_CPP_MODEL: Path to the .gguf file
- NEXE_LLAMA_CPP_N_CTX: Context window (default: auto-detected from RAM, see auto_n_ctx)
- NEXE_LLAMA_CPP_N_BATCH: Batch size for generation (default: 512) - HIGHER = FASTER
- NEXE_LLAMA_CPP_GPU_LAYERS: Layers on GPU, -1=all (default: -1)
- NEXE_LLAMA_CPP_THREADS: CPU threads (default: auto = os.cpu_count(), fallback 8)
- NEXE_LLAMA_CPP_MAX_SESSIONS: Maximum active sessions (default: 1)
- NEXE_LLAMA_CPP_MAX_TOKENS: Reply ceiling in tokens (default: 2048) — mirrors
  NEXE_MLX_MAX_TOKENS. Was a literal at the two call sites with no way to raise
  it, which a reasoning model can spend entirely before answering (#982/#984).
- NEXE_LLAMA_CPP_CHAT_FORMAT: Chat format (default: chatml)
- NEXE_LLAMA_CPP_USE_MLOCK: Keep model in RAM (default: true)
- NEXE_LLAMA_CPP_USE_MMAP: Memory-map the model (default: true)
- NEXE_LLAMA_CPP_FLASH_ATTN: Flash attention (default: true)

"""
import os
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


def auto_n_ctx() -> int:
    """Auto-detect n_ctx based on system RAM.

    Override with NEXE_LLAMA_CPP_N_CTX, which always wins.

    #965: llama.cpp was the only engine with a flat default (8192) while Ollama
    had auto_num_ctx() and MLX had auto_max_kv_size(). On a 128 GB machine that
    fixed value throws away most of the window the model can actually hold.

    The RAM tiers are deliberately IDENTICAL to
    core/endpoints/chat_engines/ollama_helpers.py::auto_num_ctx — Ollama is
    llama.cpp underneath, so the same machine has the same memory reality on
    both paths, and two different ladders would only mean the engine you picked
    silently changed how much context you got.
    """
    explicit = os.environ.get("NEXE_LLAMA_CPP_N_CTX")
    if explicit:
        try:
            value = int(explicit)
            if value > 0:
                return value
            logger.warning(
                "NEXE_LLAMA_CPP_N_CTX=%r must be positive, auto-detecting instead", explicit)
        except ValueError:
            logger.warning(
                "NEXE_LLAMA_CPP_N_CTX=%r is not a number, auto-detecting instead", explicit)
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        # ImportError, but also psutil importing and then failing: a broken RAM
        # probe must degrade to the safe rung, never raise — this runs inside
        # from_env(), i.e. at engine init and on every model hot-swap.
        return 4096
    if ram_gb >= 64:
        return 32768
    elif ram_gb >= 32:
        return 16384
    elif ram_gb >= 24:
        return 8192
    elif ram_gb >= 16:
        return 4096
    return 2048


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
        max_sessions: Maximum active sessions (LRU eviction)
        chat_format: Chat template format (gemma, llama-2, chatml, mistral)
        use_mlock: Keep model in RAM (avoids swapping)
        use_mmap: Memory-map the model (more efficient)
        flash_attn: Flash attention (faster if supported)
    """

    model_path: str = ""
    n_ctx: int = 8192
    n_batch: int = 512  # IMPORTANT: higher = more tok/s
    n_gpu_layers: int = -1
    n_threads: int = 0  # 0 = auto (llama.cpp will use all cores)
    max_sessions: int = 2  # 2 by default: allows system_hash change without reload
    max_tokens: int = 2048  # reply ceiling; the request may still override per turn
    chat_format: str = "chatml"  # chatml is compatible with Phi-3.5, Llama 3, Salamandra
    use_mlock: bool = True
    use_mmap: bool = True
    flash_attn: bool = True
    mmproj_path: str = ""  # Optional: path to the CLIP projector for VLM models (llava, etc.)

    def __post_init__(self):
        """Validate configuration after creation."""
        if not self.model_path:
            logger.warning(
                "LlamaCppConfig: model_path is empty. "
                "Set NEXE_LLAMA_CPP_MODEL or pass model_path."
            )
            # Empty path must STAY empty so callers can detect
            # the not_configured state. Without the guard, the elif below would
            # collapse "" to str(project_root), creating a fake "valid-looking"
            # path that gets sliced in logs to substrings like "ication Support/..."
            return
        # Expand ~ to home directory
        if self.model_path.startswith("~"):
            self.model_path = os.path.expanduser(self.model_path)
        # Resolve relative paths based on project root
        elif not os.path.isabs(self.model_path):
            from pathlib import Path
            project_root = Path(__file__).parents[3]  # From plugins/llama_cpp_module/core/ to project root
            self.model_path = str(project_root / self.model_path)

    @classmethod
    def from_env(cls) -> "LlamaCppConfig":
        """
        Load configuration from environment variables.

        Returns:
            LlamaCppConfig with values from the environment or defaults.
        """
        # If no explicit env var, auto-discover a GGUF dropped into
        # storage/models/ (real file or symlink). Pick the first match
        # sorted alphabetically for determinism. Enables the UX
        # "drop a .gguf, restart, it just works" — no env var needed.
        # Read from runtime_state (live override set by this module's own
        # switch_model_by_path — it was routes_chat._switch_llama_cpp_model
        # until F-D block 5 moved it here) before falling back to the env var,
        # so no os.environ mutation is needed at the call site.
        from core.runtime_state import get_with_env_fallback
        model_path = get_with_env_fallback("NEXE_LLAMA_CPP_MODEL", "")
        if not model_path:
            from core.paths.helpers import discover_first_model
            model_path = discover_first_model(
                lambda p: p.is_file() and p.suffix.lower() == ".gguf",
                "GGUF model (llama.cpp)",
            )

        config = cls(
            model_path=model_path,
            n_ctx=auto_n_ctx(),
            n_batch=int(os.getenv("NEXE_LLAMA_CPP_N_BATCH", "512")),
            n_gpu_layers=int(os.getenv("NEXE_LLAMA_CPP_GPU_LAYERS", "-1")),
            n_threads=int(os.getenv("NEXE_LLAMA_CPP_THREADS", str(os.cpu_count() or 8))),
            max_sessions=int(os.getenv("NEXE_LLAMA_CPP_MAX_SESSIONS", "2")),
            max_tokens=int(os.getenv("NEXE_LLAMA_CPP_MAX_TOKENS", "2048")),
            chat_format=os.getenv("NEXE_LLAMA_CPP_CHAT_FORMAT", "chatml"),
            use_mlock=os.getenv("NEXE_LLAMA_CPP_USE_MLOCK", "true").lower() == "true",
            use_mmap=os.getenv("NEXE_LLAMA_CPP_USE_MMAP", "true").lower() == "true",
            flash_attn=os.getenv("NEXE_LLAMA_CPP_FLASH_ATTN", "true").lower() == "true",
            mmproj_path=os.getenv("LLAMA_MMPROJ_PATH", ""),
        )

        # NEVER slice model_path with [-40:] — for a typical
        # macOS Application Support path (67 chars) it produces the literal
        # substring "ication Support/..." which looks like a path corruption
        # and was the smoking-gun symptom of the empty-path bug. Emit the full
        # path so logs are unambiguous.
        logger.info(
            "LlamaCppConfig loaded: model=%s, n_ctx=%d, n_batch=%d, gpu_layers=%d, "
            "threads=%d, mlock=%s, mmap=%s, flash_attn=%s",
            config.model_path if config.model_path else "(empty)",
            config.n_ctx,
            config.n_batch,
            config.n_gpu_layers,
            config.n_threads,
            config.use_mlock,
            config.use_mmap,
            config.flash_attn,
        )

        return config

    def validate(self) -> bool:
        """
        Validate that the configuration is correct.

        Returns:
            True if the config is valid, False otherwise.
        """
        if not self.model_path:
            logger.error("LlamaCppConfig: model_path is required")
            return False

        if not os.path.exists(self.model_path):
            logger.error(
                "LlamaCppConfig: model_path does not exist: %s",
                self.model_path
            )
            return False

        if self.n_ctx < 512:
            logger.error("LlamaCppConfig: n_ctx minimum is 512")
            return False

        if self.max_sessions < 1:
            logger.error("LlamaCppConfig: max_sessions minimum is 1")
            return False

        valid_formats = {"gemma", "llama-2", "llama-3", "chatml", "mistral", "alpaca", "phi-3"}
        if self.chat_format not in valid_formats:
            logger.warning(
                "LlamaCppConfig: chat_format '%s' not recognized. "
                "Valid formats: %s",
                self.chat_format,
                valid_formats
            )

        return True
