# -*- coding: utf-8 -*-
"""
MLXConfig - Configuració centralitzada per mlx-lm.

Totes les opcions es poden configurar via variables d'entorn:
- NEXE_MLX_MODEL: Ruta LOCAL al model MLX (obligatori)
- NEXE_MLX_MAX_TOKENS: Màxim tokens a generar (default: 2048)
- NEXE_MLX_MAX_KV_SIZE: Mida màxima KV cache (default: 16384)
- NEXE_MLX_TEMPERATURE: Temperatura de sampling (default: 0.7)
- NEXE_MLX_TOP_P: Top-p sampling (default: 0.9)
- NEXE_MLX_MAX_SESSION_CACHES: Màxim caches per sessió (default: 4)

"""
import os
import logging
from dataclasses import dataclass
from pathlib import Path

# Carregar .env automàticament quan s'importa aquest mòdul
# (Consistència amb llm_router/config.py - redundant però harmless)
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
    Configuració per mlx-lm.

    Attributes:
        model_path: Ruta LOCAL al model MLX (safetensors format)
        max_tokens: Màxim tokens a generar
        max_kv_size: Mida màxima del KV cache
        temperature: Temperatura de sampling (0.0 = determinístic)
        top_p: Top-p nucleus sampling
        max_session_caches: Màxim de caches per sessió (LRU eviction)
    """

    model_path: str = ""
    max_tokens: int = 2048
    max_kv_size: int = 16384  # 128GB RAM permet context gran
    temperature: float = 0.7
    top_p: float = 0.9
    max_session_caches: int = 4  # Com ModelPool.max_sessions

    def __post_init__(self):
        """Valida la configuració després de crear-la."""
        if not self.model_path:
            logger.warning(
                "MLXConfig: model_path buit. "
                "Configura NEXE_MLX_MODEL o passa model_path."
            )
        # Expandir ~ a home directory
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
        Carrega configuració de variables d'entorn o fallback a server.toml.

        Returns:
            MLXConfig amb valors de l'entorn o defaults.
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
                logger.warning(f"MLXConfig: Failed to read server.toml: {e}")

        config = cls(
            model_path=model_path,
            max_tokens=int(os.getenv("NEXE_MLX_MAX_TOKENS", "2048")),
            max_kv_size=int(os.getenv("NEXE_MLX_MAX_KV_SIZE", "16384")),
            temperature=float(os.getenv("NEXE_MLX_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("NEXE_MLX_TOP_P", "0.9")),
            max_session_caches=int(os.getenv("NEXE_MLX_MAX_SESSION_CACHES", "4")),
        )

        logger.info(
            "MLXConfig loaded: model=%s, max_tokens=%d, max_kv_size=%d, "
            "temp=%.1f, top_p=%.1f, max_caches=%d",
            config.model_path[-40:] if config.model_path else "(empty)",
            config.max_tokens,
            config.max_kv_size,
            config.temperature,
            config.top_p,
            config.max_session_caches,
        )

        return config

    def validate(self) -> bool:
        """
        Valida que la configuració és correcta.

        NOTA: Només suporta paths locals, NO HuggingFace repo IDs.
        Això és volgut per evitar dependència de xarxa en producció.
        Si voleu HF repos, descarregueu prèviament amb:
            huggingface-cli download <repo> --local-dir <path>

        Returns:
            True si la config és vàlida, False si no.
        """
        if not self.model_path:
            logger.error("MLXConfig: model_path is required")
            return False

        # Validar que path local existeix (NO suportem HF repo IDs)
        model_path = Path(self.model_path)
        if not model_path.exists():
            logger.error(
                "MLXConfig: model_path no existeix: %s",
                self.model_path
            )
            return False

        # Verificar que és un directori (models MLX són directoris)
        if not model_path.is_dir():
            logger.error(
                "MLXConfig: model_path ha de ser un directori: %s",
                self.model_path
            )
            return False

        # Verificar que conté config.json (format MLX)
        config_file = model_path / "config.json"
        if not config_file.exists():
            logger.warning(
                "MLXConfig: model_path no conté config.json: %s",
                self.model_path
            )
            # No és error fatal, potser és format diferent

        if self.max_tokens < 1:
            logger.error("MLXConfig: max_tokens minimum is 1")
            return False

        if self.max_kv_size < 512:
            logger.error("MLXConfig: max_kv_size minimum is 512")
            return False

        if not 0.0 <= self.temperature <= 2.0:
            logger.warning(
                "MLXConfig: temperature %.1f fora de rang recomanat [0, 2]",
                self.temperature
            )

        if not 0.0 <= self.top_p <= 1.0:
            logger.error("MLXConfig: top_p ha d'estar entre 0 i 1")
            return False

        return True

    @staticmethod
    def is_metal_available() -> bool:
        """
        Verifica si Metal (Apple Silicon) està disponible.

        Returns:
            True si Metal està disponible, False si no.
        """
        try:
            import mlx.core as mx
            return mx.metal.is_available()
        except ImportError:
            logger.warning("MLXConfig: mlx no instal·lat")
            return False
        except Exception as e:
            logger.warning("MLXConfig: error verificant Metal: %s", e)
            return False
