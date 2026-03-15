"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/models/profiles.py
Description: Perfils de maquinari i models recomanats.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from enum import Enum
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

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

# Definició de perfils
PROFILES = {
    HardwareTier.MICRO: ModelProfile(
        tier=HardwareTier.MICRO,
        primary_model="qwen2:0.5b",
        secondary_model="tinyllama",
        embedding_model="paraphrase-multilingual-mpnet-base-v2",
        preferred_engine=EngineType.LLAMA_CPP,
        max_tokens=1024,
        context_window=2048,
        description="Perfil lleuger per equips amb poca RAM (<8GB).",
        mlx_model_id="mlx-community/Qwen2-0.5B-Instruct-4bit"
    ),
    HardwareTier.CONSUMER: ModelProfile(
        tier=HardwareTier.CONSUMER,
        primary_model="phi3.5",         # Phi-3.5 Mini 3.8B — ràpid, bo seguint instruccions
        secondary_model="llama3.2:3b",
        embedding_model="paraphrase-multilingual-mpnet-base-v2",
        preferred_engine=EngineType.MLX,
        max_tokens=2048,
        context_window=8192,
        description="Equilibri velocitat/qualitat per ús diari (8-16GB).",
        mlx_model_id="mlx-community/Phi-3.5-mini-instruct-4bit"
    ),
    HardwareTier.PRO: ModelProfile(
        tier=HardwareTier.PRO,
        primary_model="llama3.1:8b",    # Llama 3.1 8B — millor qualitat per 16-32GB
        secondary_model="mistral:7b",
        embedding_model="paraphrase-multilingual-mpnet-base-v2",
        preferred_engine=EngineType.MLX,
        max_tokens=4096,
        context_window=32768,
        description="Potència per desenvolupadors i creatius (16-32GB).",
        mlx_model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    ),
    HardwareTier.ULTRA: ModelProfile(
        tier=HardwareTier.ULTRA,
        primary_model="llama3.1:70b",   # Llama 3.1 70B — qualitat màxima per >32GB
        secondary_model="mixtral:8x7b",
        embedding_model="paraphrase-multilingual-mpnet-base-v2",
        preferred_engine=EngineType.MLX,
        max_tokens=8192,
        context_window=65536,
        description="Màxima capacitat per models grans (>32GB).",
        mlx_model_id="mlx-community/Meta-Llama-3.1-70B-Instruct-4bit"
    )
}
