# -*- coding: utf-8 -*-
"""
MLXConfig - Centralized configuration for mlx-lm.

All options can be configured via environment variables:
- NEXE_MLX_MODEL: LOCAL path to the MLX model (required)
- NEXE_MLX_MAX_TOKENS: Maximum tokens to generate (default: 2048)
- NEXE_MLX_MAX_KV_SIZE: Maximum KV cache size (default: auto based on available RAM)
- NEXE_MLX_TEMPERATURE: Sampling temperature (default: 0.7)
- NEXE_MLX_TOP_P: Top-p sampling (default: 0.9)
- NEXE_MLX_MAX_SESSION_CACHES: Maximum caches per session (default: 4)

"""
import os
import logging
from dataclasses import dataclass
from pathlib import Path

# Load .env automatically when this module is imported
# (Consistency with llm_router/config.py - redundant but harmless)
try:
    from dotenv import load_dotenv
    # Use path relative to this file (NOT cwd) — cwd is unsafe and can change
    # at runtime. Removes Path.cwd() fallback that was a latent bug.
    _env_path = Path(__file__).parents[3] / ".env"  # project root .env
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

logger = logging.getLogger(__name__)


def _auto_max_kv_size() -> int:
    """
    Calculates optimal max_kv_size based on available RAM.

    Qwen3-32B KV cache: 64 layers × 2 (k+v) × 8 heads × 128 dims × 2 bytes = 256KB/token
    Reserve 20GB for model + system, the rest for KV cache.
    Cap at 131072 for safety (Qwen3 supports up to 131072 natively).
    """
    try:
        import psutil
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        available_for_kv_gb = max(0, total_gb - 20)  # Reserve 20GB for model+system
        kv_bytes_per_token = 256 * 1024  # 256KB/token (Qwen3-32B)
        max_tokens = int((available_for_kv_gb * 1024 ** 3) / kv_bytes_per_token)
        # Round to nearest multiple of 1024 and cap at 131072
        max_tokens = min(65536, (max_tokens // 1024) * 1024)
        max_tokens = max(16384, max_tokens)  # Minimum 16K
        logger.info(f"MLXConfig: auto max_kv_size={max_tokens} (RAM={total_gb:.0f}GB)")
        return max_tokens
    except Exception:
        return 65536  # Conservative fallback


def detect_hardware_tier() -> str:
    """Returns 'low' (<16 GB), 'mid' (16-32 GB), 'high' (32-64 GB), 'ultra' (64+ GB)."""
    try:
        import psutil
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        if total_gb < 16:
            return "low"
        elif total_gb < 32:
            return "mid"
        elif total_gb < 64:
            return "high"
        return "ultra"
    except Exception:
        return "low"


@dataclass
class MLXConfig:
    """
    Configuration for mlx-lm.

    Attributes:
        model_path: LOCAL path to the MLX model (safetensors format)
        max_tokens: Maximum tokens to generate
        max_kv_size: Maximum KV cache size
        temperature: Sampling temperature (0.0 = deterministic)
        top_p: Top-p nucleus sampling
        max_session_caches: Maximum caches per session (LRU eviction)
    """

    model_path: str = ""
    max_tokens: int = 2048
    max_kv_size: int = 65536  # Override via NEXE_MLX_MAX_KV_SIZE; auto-calculated by RAM in from_env()
    temperature: float = 0.7
    top_p: float = 0.9
    max_session_caches: int = 4  # Same as ModelPool.max_sessions

    def __post_init__(self):
        """Validate configuration after creation."""
        if not self.model_path:
            logger.warning(
                "MLXConfig: model_path is empty. "
                "Set NEXE_MLX_MODEL or pass model_path."
            )
        # Expand ~ to home directory
        if self.model_path.startswith("~"):
            self.model_path = os.path.expanduser(self.model_path)
        # Resolve relative paths based on project root
        elif not os.path.isabs(self.model_path):
            from pathlib import Path
            project_root = Path(__file__).parents[3]  # From plugins/mlx_module/core/ to project root
            self.model_path = str(project_root / self.model_path)

    @staticmethod
    def _model_path_from_toml() -> str:
        """Try to read model path from personality/server.toml (step 2 fallback)."""
        try:
            import tomllib
            config_path = Path("personality/server.toml")
            if not config_path.exists():
                config_path = Path(__file__).parents[3] / "personality/server.toml"
            if not config_path.exists():
                return ""
            with open(config_path, "rb") as f:
                server_cfg = tomllib.load(f)
            plugins_cfg = server_cfg.get("plugins", {}).get("models", {})
            if plugins_cfg.get("preferred_engine") == "mlx":
                candidate = plugins_cfg.get("primary", "")
                if "/" in candidate or "\\" in candidate:
                    return candidate
        except Exception as e:
            logger.warning(f"MLXConfig: Failed to read server.toml: {e}")
        return ""

    @staticmethod
    def _model_path_autodiscover() -> str:
        """Auto-discover first valid MLX model in models_dir (step 3 fallback).

        F5.6 BUG-NEW-6: use centralized get_models_dir() which honours
        NEXE_STORAGE_PATH (sidecar override) → NEXE_DATA_DIR/models → cwd → repo.
        """
        try:
            from core.paths.helpers import get_models_dir
            models_dir = get_models_dir()
            if models_dir.exists():
                candidates = sorted(
                    p for p in models_dir.iterdir()
                    if p.is_dir() and (p / "config.json").exists()
                )
                if candidates:
                    path = str(candidates[0].resolve())
                    logger.info(f"MLXConfig: auto-discovered MLX model at {path}")
                    return path
        except Exception as e:
            logger.debug(f"MLXConfig: auto-discover scan failed: {e}")
        return ""

    @classmethod
    def from_env(cls) -> "MLXConfig":
        """
        Loads configuration from environment variables or falls back to server.toml.

        Returns:
            MLXConfig with values from the environment or defaults.
        """
        # F5.6 BUG-NC-18 part 2 — get_with_env_fallback consults the
        # runtime override singleton first (live UI selections), then the
        # env var (boot-time configuration). Avoids the previous
        # os.environ mutation pattern at the call sites.
        from core.runtime_state import get_with_env_fallback
        model_path = (
            get_with_env_fallback("NEXE_MLX_MODEL", "")
            or cls._model_path_from_toml()
            or cls._model_path_autodiscover()
        )

        config = cls(
            model_path=model_path,
            max_tokens=int(os.getenv("NEXE_MLX_MAX_TOKENS", "2048")),
            max_kv_size=int(os.getenv("NEXE_MLX_MAX_KV_SIZE", str(_auto_max_kv_size()))),
            temperature=float(os.getenv("NEXE_MLX_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("NEXE_MLX_TOP_P", "0.9")),
            max_session_caches=int(os.getenv("NEXE_MLX_MAX_SESSION_CACHES", "4")),
        )

        logger.info(
            "MLXConfig loaded: model=%s, max_tokens=%d, max_kv_size=%d, "
            "temp=%.1f, top_p=%.1f, max_caches=%d",
            config.model_path if config.model_path else "(empty)",
            config.max_tokens,
            config.max_kv_size,
            config.temperature,
            config.top_p,
            config.max_session_caches,
        )

        return config

    def validate(self) -> bool:
        """
        Validates that the configuration is correct.

        NOTE: Only local paths are supported, NOT HuggingFace repo IDs.
        This is intentional to avoid network dependency in production.
        If you want HF repos, download them first with:
            huggingface-cli download <repo> --local-dir <path>

        Returns:
            True if the config is valid, False otherwise.
        """
        if not self.model_path:
            logger.error("MLXConfig: model_path is required")
            return False

        # Validate that the local path exists (HF repo IDs are NOT supported)
        model_path = Path(self.model_path)
        if not model_path.exists():
            logger.error(
                "MLXConfig: model_path does not exist: %s",
                self.model_path
            )
            return False

        # Verify it is a directory (MLX models are directories)
        if not model_path.is_dir():
            logger.error(
                "MLXConfig: model_path must be a directory: %s",
                self.model_path
            )
            return False

        # Verify it contains config.json (required by mlx-lm)
        config_file = model_path / "config.json"
        if not config_file.exists():
            logger.error(
                "MLXConfig: model_path does not contain config.json (required by mlx-lm): %s",
                self.model_path
            )
            return False

        if self.max_tokens < 1:
            logger.error("MLXConfig: max_tokens minimum is 1")
            return False

        if self.max_kv_size < 512:
            logger.error("MLXConfig: max_kv_size minimum is 512")
            return False

        if not 0.0 <= self.temperature <= 2.0:
            logger.warning(
                "MLXConfig: temperature %.1f outside recommended range [0, 2]",
                self.temperature
            )

        if not 0.0 <= self.top_p <= 1.0:
            logger.error("MLXConfig: top_p must be between 0 and 1")
            return False

        return True

    @staticmethod
    def is_metal_available() -> bool:
        """
        Verifies whether Metal (Apple Silicon) is available.

        Returns:
            True if Metal is available, False otherwise.
        """
        try:
            import mlx.core as mx
            return mx.metal.is_available()
        except ImportError:
            logger.warning("MLXConfig: mlx not installed")
            return False
        except Exception as e:
            logger.warning("MLXConfig: error verifying Metal: %s", e)
            return False
