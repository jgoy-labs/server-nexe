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
from typing import Optional

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
            data = json.load(f)
    except (OSError, ValueError):
        return None
    # A top-level non-object ([], "x", 42, true) is valid JSON but not a config:
    # letting it through hands every reader an AttributeError on .get().
    return data if isinstance(data, dict) else None


def _model_text_config(cfg: dict) -> dict:
    """The nested ``text_config`` when it is a real dict, else the config itself.

    VLM configs nest the text model's params; a malformed config can carry a
    truthy non-dict there, and ``.get()`` on it raised an AttributeError that
    reached the chat request on a hot-swap. One guard, shared by every reader.
    """
    tc = cfg.get("text_config")
    return tc if isinstance(tc, dict) and tc else cfg


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
    tc = _model_text_config(cfg)
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


def model_max_positions(model_path: str) -> Optional[int]:
    """The model's own context limit (``max_position_embeddings``), or None.

    #965: `max_kv_size` answers "how many tokens fit in RAM", which is not the
    same question as "how many tokens does this model accept". On a big machine
    with a small model the first is far larger than the second, and planning the
    conversation around it means the engine rotates its cache and drops the start
    of the chat with nobody told. The usable window is the smaller of the two.
    """
    cfg = _read_model_config_json(model_path)
    if cfg is None:
        return None
    tc = _model_text_config(cfg)
    value = tc.get("max_position_embeddings")
    if isinstance(value, bool):
        return None  # JSON true/false: isinstance(True, int) holds, min(x, True) == 1
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # some configs publish 65536.0 — the cap must not silently vanish
    return value if isinstance(value, int) and value > 0 else None


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


def _total_ram_gb():
    """Total RAM in GB, or None — the one reader both auto-sizers use (#1137)."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return None


def auto_max_kv_size(model_path: str, total_gb=None) -> int:
    """KV window budgeted from the REAL model and the machine's RAM.

    budget = total − OS reserve − runtime − weights; tokens = budget / cost
    per token, rounded down to 4096. Floor 8192 (4096 is PROVEN too small for
    normal conversations); per-tier caps encode "conservative where not
    measured": <12 GB → 16384 (the measured point), <24 GB → 32768, else
    65536. #965: the result is additionally capped by the model's own
    max_position_embeddings — but NEVER below the 8192 floor: with the default
    reply budget (max_tokens=2048) plus the truncation margin, anything under
    ~2304 makes truncate_messages_to_budget keep only the last message, so a
    2048-position model capped literally would turn every conversation into
    single-turn amnesia. Such models keep the floor and the pre-#965 behaviour
    (the cache rotates on overflow) instead. NEXE_MLX_MAX_KV_SIZE overrides all
    of this in from_env().
    """
    if total_gb is None:
        total_gb = _total_ram_gb()  # None falls through: the model cap below must still apply
    if total_gb is None:
        result = 16384  # safe fallback (the old 65536 was NOT conservative)
    else:
        weights = model_weights_gb(model_path)
        weights_gb = weights if weights is not None else 3.5
        budget_gb = total_gb - _OS_RESERVE_GB - _RUNTIME_GB - weights_gb
        tokens = int(max(0.0, budget_gb) * (1024 ** 3) / model_kv_bytes_per_token(model_path))
        tokens = (tokens // 4096) * 4096
        cap = 16384 if total_gb < 12 else (32768 if total_gb < 24 else 65536)
        result = max(8192, min(cap, tokens))
    # #965: max_kv_size answers "how many tokens fit in RAM" — the model's own
    # max_position_embeddings answers "how many tokens does it accept". Capping
    # HERE (not in whoever reports the window) means every consumer inherits it:
    # the prompt truncator, the prompt cache and the RAM guard stop planning for
    # positions the model does not have, and the RAM guard stops over-reserving.
    # The floor wins over the cap (see docstring): a sub-8192 model limit would
    # zero the truncator's prompt budget and silently amputate the history.
    model_limit = model_max_positions(model_path)
    if model_limit:
        capped = min(result, max(8192, model_limit))
        if model_limit < 8192:
            # The one path where we knowingly plan past the model: the floor
            # wins to avoid single-turn amnesia, so the cache WILL rotate.
            # Warned UNCONDITIONALLY — on a small machine RAM alone already
            # left `result` at the floor, `capped == result`, and gating this
            # on `capped < result` silenced the warning exactly on the 8 GB
            # boxes where the rotation bites hardest.
            logger.warning(
                "MLXConfig: model limit %d is below the 8192 floor — max_kv_size stays "
                "at %d and the cache will rotate on overflow",
                model_limit, capped,
            )
        elif capped < result:
            logger.info(
                "MLXConfig: auto max_kv_size capped by the model itself: %d -> %d (max_position_embeddings=%d)",
                result, capped, model_limit,
            )
        result = capped
    logger.info(
        "MLXConfig: auto max_kv_size=%d (RAM=%s, weights=%s, kv/tok=%dKB)",
        result,
        f"{total_gb:.0f}GB" if total_gb is not None else "unknown",
        f"{weights_gb:.2f}GB" if total_gb is not None and weights is not None else "unknown→3.5GB",
        model_kv_bytes_per_token(model_path) // 1024,
    )
    return result


#: The text path's default (max_session_caches / ModelPool.max_sessions): the
#: VLM count never goes above it, however much RAM there is.
_VLM_SESSION_CACHES_CAP = 4


def auto_vlm_session_caches(model_path: str, max_kv_size: int, total_gb=None) -> int:
    """How many conversations keep their VLM prompt cache, from the RAM (#1137).

    The fixed 1 was sized for #843's 8 GB machine; on 128 GB it meant going
    back to an earlier conversation re-read it whole (live 03/10: every new
    conversation evicted the last). Same budget as auto_max_kv_size (total −
    OS reserve − runtime − weights), divided by one full KV window per
    conversation — the most a cached conversation can hold — and kept between
    1 and the text path's 4. RAM unknown → 1. NEXE_MLX_VLM_MAX_SESSION_CACHES
    overrides it in from_env().
    """
    if total_gb is None:
        total_gb = _total_ram_gb()
    if total_gb is None or not max_kv_size or max_kv_size <= 0:
        return 1
    weights = model_weights_gb(model_path)
    budget_gb = total_gb - _OS_RESERVE_GB - _RUNTIME_GB - (weights if weights is not None else 3.5)
    window_gb = max_kv_size * model_kv_bytes_per_token(model_path) / (1024 ** 3)
    return max(1, min(_VLM_SESSION_CACHES_CAP, int(max(0.0, budget_gb) // window_gb)))


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
    # machine: this gets its own knob, so raising NEXE_MLX_MAX_SESSION_CACHES
    # for the text path cannot quietly multiply the VLM memory too. 1 here;
    # from_env() sizes it from the RAM (auto_vlm_session_caches, #1137).
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
        )
        # B004: max_kv_size AFTER construction (__post_init__ has normalised
        # ~/relative paths) and derived from the model actually being loaded.
        # The env var short-circuits everything — and is only evaluated when
        # set (the old default-arg pattern computed the auto value even when
        # the env var was defined). Hot-swap recalculates for free: every
        # model switch goes through from_env() again.
        _raw_kv = os.getenv("NEXE_MLX_MAX_KV_SIZE")
        _kv_override = None
        if _raw_kv:
            try:
                _kv_override = int(_raw_kv)
                if _kv_override <= 0:
                    logger.warning(
                        "NEXE_MLX_MAX_KV_SIZE=%r must be positive, auto-sizing instead", _raw_kv
                    )
                    _kv_override = None
            except ValueError:
                logger.warning(
                    "NEXE_MLX_MAX_KV_SIZE=%r is not a number, auto-sizing instead", _raw_kv
                )
        config.max_kv_size = (
            _kv_override if _kv_override is not None else auto_max_kv_size(config.model_path)
        )
        # #1137: after max_kv_size — one conversation's cache is one KV window.
        # Like NEXE_MLX_MAX_KV_SIZE above, the env var short-circuits the auto
        # value (only computed when it is absent); an unusable one keeps 1.
        config.max_vlm_session_caches = (
            auto_vlm_session_caches(config.model_path, config.max_kv_size)
            if os.getenv("NEXE_MLX_VLM_MAX_SESSION_CACHES") is None
            else _positive_int_env("NEXE_MLX_VLM_MAX_SESSION_CACHES", 1)
        )

        logger.info(
            "MLXConfig loaded: model=%s, max_tokens=%d, max_kv_size=%d, "
            "temp=%.1f, top_p=%.1f, max_caches=%d, vlm_caches=%d",
            config.model_path if config.model_path else "(empty)",
            config.max_tokens,
            config.max_kv_size,
            config.temperature,
            config.top_p,
            config.max_session_caches,
            config.max_vlm_session_caches,
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
