"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/models/profiles.py
Description: Hardware profiles and recommended models.

www.jgoy.net
────────────────────────────────────
"""
from enum import Enum
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

from personality.i18n.resolve import t_modular

class EngineType(str, Enum):
    AUTO = "auto"
    MLX = "mlx"
    OLLAMA = "ollama"
    LLAMA_CPP = "llama_cpp"

class HardwareTier(str, Enum):
    MICRO = "micro"       # RPi, < 8GB
    CONSUMER = "consumer" # 8GB - 16GB
    PRO = "pro"          # 16GB - 32GB
    ULTRA = "ultra"       # > 32GB

class ModelProfile(BaseModel):
    tier: HardwareTier
    primary_model: str
    secondary_model: str
    embedding_model: str
    preferred_engine: EngineType
    max_tokens: int
    context_window: int
    description: str
    mlx_model_id: Optional[str] = None # HuggingFace Repo ID per MLX

    model_config = ConfigDict(protected_namespaces=())

# Profile definitions
PROFILES = {
    HardwareTier.MICRO: ModelProfile(
        tier=HardwareTier.MICRO,
        primary_model="qwen2:0.5b",
        secondary_model="tinyllama",
        embedding_model="all-MiniLM-L6-v2",
        preferred_engine=EngineType.LLAMA_CPP,
        max_tokens=1024,
        context_window=2048,
        description=t_modular(
            "models.profiles.micro_desc",
            "Lightweight profile for low-RAM devices (<8GB)."
        ),
        mlx_model_id="mlx-community/Qwen2-0.5B-Instruct-4bit"
    ),
    HardwareTier.CONSUMER: ModelProfile(
        tier=HardwareTier.CONSUMER,
        primary_model="gemma2:2b", # 2B is very efficient
        secondary_model="phi3:3.8b",
        embedding_model="all-MiniLM-L6-v2",
        preferred_engine=EngineType.MLX, # Assume Mac by default for CONSUMER, selector may adjust
        max_tokens=2048,
        context_window=8192,
        description=t_modular(
            "models.profiles.consumer_desc",
            "Balanced speed/quality for daily use (8-16GB)."
        ),
        mlx_model_id="mlx-community/gemma-2-2b-it-4bit" 
    ),
    HardwareTier.PRO: ModelProfile(
        tier=HardwareTier.PRO,
        primary_model="llama3.2:3b",
        secondary_model="gemma2:9b",
        embedding_model="nomic-embed-text",
        preferred_engine=EngineType.MLX,
        max_tokens=4096,
        context_window=16384,
        description=t_modular(
            "models.profiles.pro_desc",
            "Power for developers and creators (16-32GB)."
        ),
        mlx_model_id="mlx-community/Llama-3.2-3B-Instruct-4bit"
    ),
    HardwareTier.ULTRA: ModelProfile(
        tier=HardwareTier.ULTRA,
        primary_model="llama3.1:8b", 
        secondary_model="mistral-nemo:12b",
        embedding_model="mxbai-embed-large",
        preferred_engine=EngineType.MLX,
        max_tokens=8192,
        context_window=32768,
        description=t_modular(
            "models.profiles.ultra_desc",
            "Maximum capacity for large models (>32GB)."
        ),
        mlx_model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    )
}
