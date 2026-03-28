"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/models/registry.py
Description: Registre curat de models suportats (MLX & Ollama).
             Mapeja noms curts (e.g. "llama3") a IDs reals (HF o Ollama library).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class ModelEntry:
    short_name: str
    description: str
    size_gb: float
    ollama_tag: str
    mlx_hf_id: str

# Curated registry of models verified to work well with Nexe
MODEL_REGISTRY: Dict[str, ModelEntry] = {
    # --- Tiny / Micro Models ---
    "qwen0.5": ModelEntry(
        short_name="qwen0.5",
        description="Qwen2 0.5B - Ultra fast, for testing or RPi.",
        size_gb=0.4,
        ollama_tag="qwen2:0.5b",
        mlx_hf_id="mlx-community/Qwen2-0.5B-Instruct-4bit"
    ),
    "tinyllama": ModelEntry(
        short_name="tinyllama",
        description="TinyLlama 1.1B - Very lightweight.",
        size_gb=0.7,
        ollama_tag="tinyllama",
        mlx_hf_id="mlx-community/TinyLlama-1.1B-Chat-v1.0-4bit"
    ),
    
    # --- Small / Consumer Models (4-8GB RAM) ---
    "gemma2b": ModelEntry(
        short_name="gemma2b",
        description="Google Gemma 2 (2B) - Surprisingly smart for its size.",
        size_gb=1.5,
        ollama_tag="gemma2:2b",
        mlx_hf_id="mlx-community/gemma-2-2b-it-4bit"
    ),
    "llama3.2-3b": ModelEntry(
        short_name="llama3.2-3b",
        description="Meta Llama 3.2 (3B) - Current standard for edge devices.",
        size_gb=2.0,
        ollama_tag="llama3.2:3b",
        mlx_hf_id="mlx-community/Llama-3.2-3B-Instruct-4bit"
    ),
    "phi3.5": ModelEntry(
        short_name="phi3.5",
        description="Microsoft Phi-3.5 Mini (3.8B) - Very good at following instructions.",
        size_gb=2.3,
        ollama_tag="phi3.5",
        mlx_hf_id="mlx-community/Phi-3.5-mini-instruct-4bit"
    ),

    # --- Iberian Language Models ---
    "salamandra2b": ModelEntry(
        short_name="salamandra2b",
        description="BSC/AINA Salamandra (2B) - Optimized for Catalan, Spanish, Basque and Galician.",
        size_gb=1.5,
        ollama_tag="hdnh2006/salamandra-2b-instruct",
        mlx_hf_id=""   # No MLX support yet
    ),
    "salamandra7b": ModelEntry(
        short_name="salamandra7b",
        description="BSC/AINA Salamandra (7B) - Best model for Iberian languages.",
        size_gb=4.9,
        ollama_tag="cas/salamandra-7b-instruct",
        mlx_hf_id=""   # No MLX support yet
    ),

    # --- Medium / Pro Models (8-16GB RAM) ---
    "mistral7b": ModelEntry(
        short_name="mistral7b",
        description="Mistral AI (7B) - Excellent quality/speed balance. Multilingual.",
        size_gb=4.1,
        ollama_tag="mistral:7b",
        mlx_hf_id="mlx-community/Mistral-7B-Instruct-v0.3-4bit"
    ),
    "llama3.1-8b": ModelEntry(
        short_name="llama3.1-8b",
        description="Meta Llama 3.1 (8B) - Best in class. Recommended.",
        size_gb=4.9,
        ollama_tag="llama3.1:8b",
        mlx_hf_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    ),
    "gemma9b": ModelEntry(
        short_name="gemma9b",
        description="Google Gemma 2 (9B) - Very powerful, requires more RAM.",
        size_gb=5.5,
        ollama_tag="gemma2:9b",
        mlx_hf_id="mlx-community/gemma-2-9b-it-4bit"
    ),
    "mistral-nemo": ModelEntry(
        short_name="mistral-nemo",
        description="Mistral Nemo (12B) - Large context and reasoning.",
        size_gb=7.5,
        ollama_tag="mistral-nemo",
        mlx_hf_id="mlx-community/Mistral-Nemo-Instruct-2407-4bit"
    ),

    # --- Large / Ultra Models (>32GB RAM) ---
    "llama3.1-70b": ModelEntry(
        short_name="llama3.1-70b",
        description="Meta Llama 3.1 (70B) - Professional quality. Requires >48GB RAM.",
        size_gb=40.0,
        ollama_tag="llama3.1:70b",
        mlx_hf_id="mlx-community/Meta-Llama-3.1-70B-Instruct-4bit"
    ),
    "mixtral": ModelEntry(
        short_name="mixtral",
        description="Mistral Mixtral 8x7B (MoE) - Maximum quality, MoE architecture. Requires 32GB RAM.",
        size_gb=26.0,
        ollama_tag="mixtral:8x7b",
        mlx_hf_id="mlx-community/Mixtral-8x7B-Instruct-v0.1-4bit"
    ),
}

def get_model_entry(name: str) -> Optional[ModelEntry]:
    """Busca un model pel seu nom curt."""
    return MODEL_REGISTRY.get(name.lower())

def list_models_table() -> str:
    """Retorna una taula formatada dels models disponibles."""
    headers = ["Nom Curt", "Mida", "Descripció"]
    rows = []
    for m in MODEL_REGISTRY.values():
        rows.append(f"{m.short_name:<15} {m.size_gb:>4.1f}GB  {m.description}")
    
    return "\n".join(rows)
