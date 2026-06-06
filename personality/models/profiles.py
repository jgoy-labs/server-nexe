"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/models/profiles.py
Description: Perfils de maquinari i models recomanats.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from enum import Enum
from pydantic import BaseModel, ConfigDict
from typing import Optional

from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL

class EngineType(str, Enum):
    """Supported LLM inference backends."""

    AUTO = "auto"
    MLX = "mlx"
    OLLAMA = "ollama"
    LLAMA_CPP = "llama_cpp"

class HardwareTier(str, Enum):
    """Hardware classification by available RAM."""

    MICRO = "micro"       # RPi, < 8GB
    CONSUMER = "consumer" # 8GB - 16GB
    PRO = "pro"          # 16GB - 32GB
    ULTRA = "ultra"       # > 32GB

class ModelProfile(BaseModel):
    """Default model configuration for a given hardware tier."""

    tier: HardwareTier
    primary_model: str
    secondary_model: str
    embedding_model: str
    preferred_engine: EngineType
    max_tokens: int
    context_window: int
    description: str
    mlx_model_id: Optional[str] = None # HuggingFace Repo ID for MLX

    model_config = ConfigDict(protected_namespaces=())

# Profile definitions.
# Aligned with the v1.0.5 installer catalog (installer/installer_catalog_data.py):
#   MICRO    -> catalog "small"  (8 GB)  : Qwen3.5 4B (the small-tier default)
#   CONSUMER -> catalog "medium" (16 GB) : Qwen3.5 9B / Mistral Nemo 12B
#   PRO      -> catalog "large"  (24 GB) : Qwen3.5 27B / Mistral Small 3.2 24B
#   ULTRA    -> catalog "xlarge" (32 GB+): Qwen3.5 35B-A3B / Mixtral 8x7B
PROFILES = {
    HardwareTier.MICRO: ModelProfile(
        tier=HardwareTier.MICRO,
        primary_model="qwen3.5:4b",       # Qwen3.5 4B — multimodal, thinking, excellent Catalan
        secondary_model="qwen3.5:4b",
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        preferred_engine=EngineType.LLAMA_CPP,
        max_tokens=1024,
        context_window=2048,
        description="Perfil lleuger per equips amb poca RAM (<8GB).",
        mlx_model_id="mlx-community/Qwen3.5-4B-MLX-4bit"
    ),
    HardwareTier.CONSUMER: ModelProfile(
        tier=HardwareTier.CONSUMER,
        primary_model="qwen3.5:9b",       # Qwen3.5 9B — thinking, vision, tool calling
        secondary_model="mistral-nemo:12b",
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        preferred_engine=EngineType.MLX,
        max_tokens=2048,
        context_window=8192,
        description="Equilibri velocitat/qualitat per ús diari (8-16GB).",
        mlx_model_id="mlx-community/Qwen3.5-9B-MLX-4bit"
    ),
    HardwareTier.PRO: ModelProfile(
        tier=HardwareTier.PRO,
        primary_model="qwen3.5:27b",      # Qwen3.5 27B — excellent thinking, vision (16-32GB)
        secondary_model="mistral-small3.2",
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        preferred_engine=EngineType.MLX,
        max_tokens=4096,
        context_window=32768,
        description="Power for developers and creatives (16-32GB).",
        mlx_model_id="mlx-community/Qwen3.5-27B-4bit"
    ),
    HardwareTier.ULTRA: ModelProfile(
        tier=HardwareTier.ULTRA,
        primary_model="qwen3.5:35b-a3b",  # Qwen3.5 35B-A3B (MoE) — 9B speed, 35B quality (>32GB)
        secondary_model="mixtral:8x7b",
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        preferred_engine=EngineType.MLX,
        max_tokens=8192,
        context_window=65536,
        description="Maximum capacity for large models (>32GB).",
        mlx_model_id="mlx-community/Qwen3.5-35B-A3B-4bit"
    )
}
