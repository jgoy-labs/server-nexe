# -*- coding: utf-8 -*-
"""
MLXConfig - Centralized configuration for mlx-lm.

All options can be configured via environment variables:
- NEXE_MLX_MODEL: LOCAL path to the MLX model (required)
- NEXE_MLX_MAX_TOKENS: Max tokens to generate (default: 2048)
- NEXE_MLX_MAX_KV_SIZE: Max KV cache size (default: 16384)
- NEXE_MLX_TEMPERATURE: Sampling temperature (default: 0.7)
- NEXE_MLX_TOP_P: Top-p sampling (default: 0.9)
- NEXE_MLX_MAX_SESSION_CACHES: Max caches per session (default: 4)

Part of: PLA_OPTIMITZACIO_LLM_MODULAR - MLX backend
"""
import os
import logging
from dataclasses import dataclass
from pathlib import Path

from personality.i18n.resolve import t_modular

# Load .env automatically when this module is imported
# (Consistency with llm_router/config.py - redundant but harmless)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parents[3] / ".env"  # root directory .env
    if not _env_path.exists():
        _env_path = Path.cwd() / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

logger = logging.getLogger(__name__)


@dataclass
class MLXConfig:
    """
    Configuration for mlx-lm.

    Attributes:
        model_path: LOCAL path to the MLX model (safetensors format)
        max_tokens: Max tokens to generate
        max_kv_size: Max KV cache size
        temperature: Sampling temperature (0.0 = deterministic)
        top_p: Top-p nucleus sampling
        max_session_caches: Max caches per session (LRU eviction)
    """

    model_path: str = ""
    max_tokens: int = 2048
    max_kv_size: int = 16384  # 128GB RAM allows a large context
    temperature: float = 0.7
    top_p: float = 0.9
    max_session_caches: int = 4  # Like ModelPool.max_sessions

    def __post_init__(self):
        """Validate configuration after creation."""
        if not self.model_path:
            logger.warning(
                t_modular(
                    "mlx_module.config.model_path_empty",
                    "MLXConfig: model_path is empty. Configure NEXE_MLX_MODEL or pass model_path."
                )
            )
        # Expand ~ to home directory
        if self.model_path.startswith("~"):
            self.model_path = os.path.expanduser(self.model_path)
        # Resolve relative paths based on project root
        elif not os.path.isabs(self.model_path):
            from pathlib import Path
            project_root = Path(__file__).parents[2]  # From plugins/mlx_module/ to project root
            self.model_path = str(project_root / self.model_path)

    @classmethod
    def from_env(cls) -> "MLXConfig":
        """
        Load configuration from environment variables or fallback to server.toml.

        Returns:
            MLXConfig with environment values or defaults.
        """
        # 1. Start with env vars
        model_path = os.getenv("NEXE_MLX_MODEL", "")
        
        # 2. Fallback to server.toml if model_path is empty
        if not model_path:
            try:
                import toml
                config_path = Path("personality/server.toml")
                if not config_path.exists():
                     # Try absolute path based on project root if relative fails
                     config_path = Path(__file__).parents[3] / "personality/server.toml"
                
                if config_path.exists():
                    server_cfg = toml.load(config_path)
                    plugins_cfg = server_cfg.get("plugins", {}).get("models", {})
                    
                    # Only use if engine is MLX
                    if plugins_cfg.get("preferred_engine") == "mlx":
                        candidate_path = plugins_cfg.get("primary", "")
                        # Validate it looks like a path (contains slashes or exists)
                        if "/" in candidate_path or "\\" in candidate_path:
                             model_path = candidate_path
            except Exception as e:
                logger.warning(
                    t_modular(
                        "mlx_module.config.read_server_toml_failed",
                        "MLXConfig: Failed to read server.toml: {error}",
                        error=e
                    )
                )

        config = cls(
            model_path=model_path,
            max_tokens=int(os.getenv("NEXE_MLX_MAX_TOKENS", "2048")),
            max_kv_size=int(os.getenv("NEXE_MLX_MAX_KV_SIZE", "16384")),
            temperature=float(os.getenv("NEXE_MLX_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("NEXE_MLX_TOP_P", "0.9")),
            max_session_caches=int(os.getenv("NEXE_MLX_MAX_SESSION_CACHES", "4")),
        )

        model_short = config.model_path[-40:] if config.model_path else "(empty)"
        logger.info(
            t_modular(
                "mlx_module.config.loaded",
                "MLXConfig loaded: model={model}, max_tokens={max_tokens}, max_kv_size={max_kv_size}, "
                "temp={temperature:.1f}, top_p={top_p:.1f}, max_caches={max_caches}",
                model=model_short,
                max_tokens=config.max_tokens,
                max_kv_size=config.max_kv_size,
                temperature=config.temperature,
                top_p=config.top_p,
                max_caches=config.max_session_caches,
            )
        )

        return config

    def validate(self) -> bool:
        """
        Validate that the configuration is correct.

        NOTE: Only supports local paths, NOT HuggingFace repo IDs.
        This is intentional to avoid network dependency in production.
        If you want HF repos, download them first with:
            huggingface-cli download <repo> --local-dir <path>

        Returns:
            True if the config is valid, False otherwise.
        """
        if not self.model_path:
            logger.error(
                t_modular(
                    "mlx_module.config.model_path_required",
                    "MLXConfig: model_path is required"
                )
            )
            return False

        # Validate local path exists (we do NOT support HF repo IDs)
        model_path = Path(self.model_path)
        if not model_path.exists():
            logger.error(
                t_modular(
                    "mlx_module.config.model_path_missing",
                    "MLXConfig: model_path does not exist: {path}",
                    path=self.model_path
                )
            )
            return False

        # Verify it is a directory (MLX models are directories)
        if not model_path.is_dir():
            logger.error(
                t_modular(
                    "mlx_module.config.model_path_not_dir",
                    "MLXConfig: model_path must be a directory: {path}",
                    path=self.model_path
                )
            )
            return False

        # Verify it contains config.json (MLX format)
        config_file = model_path / "config.json"
        if not config_file.exists():
            logger.warning(
                t_modular(
                    "mlx_module.config.config_json_missing",
                    "MLXConfig: model_path does not contain config.json: {path}",
                    path=self.model_path
                )
            )
            # Not a fatal error, may be a different format

        if self.max_tokens < 1:
            logger.error(
                t_modular(
                    "mlx_module.config.max_tokens_min",
                    "MLXConfig: max_tokens minimum is 1"
                )
            )
            return False

        if self.max_kv_size < 512:
            logger.error(
                t_modular(
                    "mlx_module.config.max_kv_size_min",
                    "MLXConfig: max_kv_size minimum is 512"
                )
            )
            return False

        if not 0.0 <= self.temperature <= 2.0:
            logger.warning(
                t_modular(
                    "mlx_module.config.temperature_out_of_range",
                    "MLXConfig: temperature {temperature:.1f} outside recommended range [0, 2]",
                    temperature=self.temperature
                )
            )

        if not 0.0 <= self.top_p <= 1.0:
            logger.error(
                t_modular(
                    "mlx_module.config.top_p_range",
                    "MLXConfig: top_p must be between 0 and 1"
                )
            )
            return False

        return True

    @staticmethod
    def is_metal_available() -> bool:
        """
        Check whether Metal (Apple Silicon) is available.

        Returns:
            True if Metal is available, False otherwise.
        """
        try:
            import mlx.core as mx
            return mx.metal.is_available()
        except ImportError:
            logger.warning(
                t_modular(
                    "mlx_module.config.mlx_not_installed",
                    "MLXConfig: mlx not installed"
                )
            )
            return False
        except Exception as e:
            logger.warning(
                t_modular(
                    "mlx_module.config.metal_check_failed",
                    "MLXConfig: error checking Metal: {error}",
                    error=e
                )
            )
            return False
