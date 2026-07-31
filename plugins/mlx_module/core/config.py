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


# B004 — per-model KV budget. The old formula reserved a flat 20 GB (zero on
# any machine under 20 GB → always the floor) and hardcoded the 32B model's
# 256 KB/token even when loading the 4B (real cost: 128 KB/token). Field
# measurement (M1 8 GB, 2026-07-23): footprint = weights + max_kv_size ×
# kv_bytes_per_token + ~1.15 GB runtime, flat during generation.

DEFAULT_KV_BYTES_PER_TOKEN = 256 * 1024  # old assumption, kept as the fallback
_RUNTIME_GB = 1.15   # measured runtime baseline (Python + Metal, 2026-07-23)
_OS_RESERVE_GB = 1.5


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive int from the env; anything unusable falls back.

    A typo must not disable a cache (0) or crash the engine at import time —
    the same tolerance the other MLX knobs already apply.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer — using %d", name, raw, default)
        return default
    if value < 1:
        logger.warning("%s=%d is below 1 — using %d", name, value, default)
        return default
    return value


def _read_model_config_json(model_path: str):
    """Return the model's config.json as a dict, or None if unreadable."""
    if not model_path:
        return None
    try:
        import json
        with open(Path(model_path) / "config.json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def model_kv_bytes_per_token(model_path: str, *, effective: bool = False) -> int:
    """KV-cache bytes per token of THIS model: 2 (k+v) × layers × kv_heads ×
    head_dim × 2 bytes (f16 — weight quantization does not touch the KV).

    Default is the NAIVE figure (every layer counted): it is what a
    RotatingKVCache would store and deliberately over-reserves on models with
    linear-attention/sliding-window layers. ``effective=True`` counts only the
    ``full_attention`` entries of ``layer_types`` (realistic growth) — used by
    the RAM guard so it never over-refuses (gemma-4-31b: 960 KB/token naive
    vs ~160 real). Falls back to DEFAULT_KV_BYTES_PER_TOKEN when the config
    is unreadable or malformed.
    """
    cfg = _read_model_config_json(model_path)
    if cfg is None:
        return DEFAULT_KV_BYTES_PER_TOKEN
    tc = cfg.get("text_config") or cfg  # VLMs nest the text model's params
    layers = tc.get("num_hidden_layers")
    kv_heads = tc.get("num_key_value_heads") or tc.get("num_attention_heads")
    head_dim = tc.get("head_dim")
    if not head_dim:
        hs, nah = tc.get("hidden_size"), tc.get("num_attention_heads")
        head_dim = hs // nah if (hs and nah) else None
    if not all(isinstance(x, int) and x > 0 for x in (layers, kv_heads, head_dim)):
        return DEFAULT_KV_BYTES_PER_TOKEN
    if effective:
        lt = tc.get("layer_types")
        if isinstance(lt, list) and lt:
            layers = sum(1 for t in lt if t == "full_attention") or layers
    bytes_per_token = 2 * layers * kv_heads * head_dim * 2
    if not (8 * 1024 <= bytes_per_token <= 4 * 1024 * 1024):  # sanity clamp
        return DEFAULT_KV_BYTES_PER_TOKEN
    return bytes_per_token


def model_weights_gb(model_path: str):
    """Sum of the model's ``*.safetensors`` in GB, or None if not measurable."""
    if not model_path:
        return None
    try:
        p = Path(model_path)
        if not p.is_dir():
            return None
        total = sum(f.stat().st_size for f in p.glob("*.safetensors"))
        return total / (1024 ** 3) if total > 0 else None
    except OSError:
        return None


def auto_max_kv_size(model_path: str, total_gb=None) -> int:
    """KV window budgeted from the REAL model and the machine's RAM.

    budget = total − OS reserve − runtime − weights; tokens = budget / cost
    per token, rounded down to 4096. Floor 8192 (4096 is PROVEN too small for
    normal conversations); per-tier caps encode "conservative where not
    measured": <12 GB → 16384 (the measured point), <24 GB → 32768, else
    65536. NEXE_MLX_MAX_KV_SIZE overrides all of this in from_env().
    """
    if total_gb is None:
        try:
            import psutil
            total_gb = psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            return 16384  # safe fallback (the old 65536 was NOT conservative)
    weights = model_weights_gb(model_path)
    weights_gb = weights if weights is not None else 3.5
    budget_gb = total_gb - _OS_RESERVE_GB - _RUNTIME_GB - weights_gb
    tokens = int(max(0.0, budget_gb) * (1024 ** 3) / model_kv_bytes_per_token(model_path))
    tokens = (tokens // 4096) * 4096
    cap = 16384 if total_gb < 12 else (32768 if total_gb < 24 else 65536)
    result = max(8192, min(cap, tokens))
    logger.info(
        "MLXConfig: auto max_kv_size=%d (RAM=%.0fGB, weights=%s, kv/tok=%dKB)",
        result, total_gb,
        f"{weights_gb:.2f}GB" if weights is not None else "unknown→3.5GB",
        model_kv_bytes_per_token(model_path) // 1024,
    )
    return result


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
    # VLM KV caches are far heavier than the text ones, and #843 is an 8 GB
    # machine: this gets its own knob and its own default of 1, so raising
    # NEXE_MLX_MAX_SESSION_CACHES for the text path cannot quietly multiply
    # the VLM memory too.
    max_vlm_session_caches: int = 1  # NEXE_MLX_VLM_MAX_SESSION_CACHES

    def __post_init__(self):
        """Validate configuration after creation."""
        if not self.model_path:
            logger.warning(
                "MLXConfig: model_path is empty. "
                "Set NEXE_MLX_MODEL or pass model_path."
            )
            # Empty path must STAY empty so the module's
            # initialize() can detect the not_configured state. Without the
            # guard, the elif below would collapse "" to str(project_root),
            # producing a NEXE_HOME path that triggered the "config.json not
            # found" cascade in the empirical G10 log.
            return
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

        Use centralized get_models_dir() which honours
        NEXE_STORAGE_PATH (sidecar override) → NEXE_DATA_DIR/models → cwd → repo.
        """
        from core.paths.helpers import discover_first_model
        return discover_first_model(
            lambda p: p.is_dir() and (p / "config.json").exists(),
            "MLX model",
        )

    @classmethod
    def from_env(cls) -> "MLXConfig":
        """
        Loads configuration from environment variables or falls back to server.toml.

        Returns:
            MLXConfig with values from the environment or defaults.
        """
        # get_with_env_fallback consults the
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
            temperature=float(os.getenv("NEXE_MLX_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("NEXE_MLX_TOP_P", "0.9")),
            max_session_caches=int(os.getenv("NEXE_MLX_MAX_SESSION_CACHES", "4")),
            max_vlm_session_caches=_positive_int_env("NEXE_MLX_VLM_MAX_SESSION_CACHES", 1),
        )
        # B004: max_kv_size AFTER construction (__post_init__ has normalised
        # ~/relative paths) and derived from the model actually being loaded.
        # The env var short-circuits everything — and is only evaluated when
        # set (the old default-arg pattern computed the auto value even when
        # the env var was defined). Hot-swap recalculates for free: every
        # model switch goes through from_env() again.
        _raw_kv = os.getenv("NEXE_MLX_MAX_KV_SIZE")
        config.max_kv_size = (
            int(_raw_kv) if _raw_kv else auto_max_kv_size(config.model_path)
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
