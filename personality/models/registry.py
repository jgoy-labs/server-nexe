"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/models/registry.py
Description: Curated registry of supported models (MLX & Ollama).
             Maps short names (e.g. "llama3") to real IDs (HF or Ollama library).

www.jgoy.net
────────────────────────────────────
"""

from typing import Dict, Optional
from dataclasses import dataclass

from personality.i18n.resolve import t_modular

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
        description=t_modular(
            "models.registry.qwen0_5_desc",
            "Qwen2 0.5B - Ultra fast, for testing or Raspberry Pi."
        ),
        size_gb=0.4,
        ollama_tag="qwen2:0.5b",
        mlx_hf_id="mlx-community/Qwen2-0.5B-Instruct-4bit"
    ),
    "tinyllama": ModelEntry(
        short_name="tinyllama",
        description=t_modular(
            "models.registry.tinyllama_desc",
            "TinyLlama 1.1B - Very lightweight."
        ),
        size_gb=0.7,
        ollama_tag="tinyllama",
        mlx_hf_id="mlx-community/TinyLlama-1.1B-Chat-v1.0-4bit"
    ),
    
    # --- Small / Consumer Models (4-8GB RAM) ---
    "gemma2b": ModelEntry(
        short_name="gemma2b",
        description=t_modular(
            "models.registry.gemma2b_desc",
            "Google Gemma 2 (2B) - Surprisingly smart for its size."
        ),
        size_gb=1.5,
        ollama_tag="gemma2:2b",
        mlx_hf_id="mlx-community/gemma-2-2b-it-4bit"
    ),
    "llama3.2-3b": ModelEntry(
        short_name="llama3.2-3b",
        description=t_modular(
            "models.registry.llama3_2_3b_desc",
            "Meta Llama 3.2 (3B) - Current standard for edge devices."
        ),
        size_gb=2.0,
        ollama_tag="llama3.2:3b",
        mlx_hf_id="mlx-community/Llama-3.2-3B-Instruct-4bit"
    ),
    "phi3.5": ModelEntry(
        short_name="phi3.5",
        description=t_modular(
            "models.registry.phi3_5_desc",
            "Microsoft Phi-3.5 Mini (3.8B) - Very good at following instructions."
        ),
        size_gb=2.3,
        ollama_tag="phi3.5",
        mlx_hf_id="mlx-community/Phi-3.5-mini-instruct-4bit"
    ),

    # --- Medium / Pro Models (8-16GB RAM) ---
    "llama3.1-8b": ModelEntry(
        short_name="llama3.1-8b",
        description=t_modular(
            "models.registry.llama3_1_8b_desc",
            "Meta Llama 3.1 (8B) - Best in its class. Recommended."
        ),
        size_gb=4.9,
        ollama_tag="llama3.1:8b",
        mlx_hf_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit"
    ),
    "gemma9b": ModelEntry(
        short_name="gemma9b",
        description=t_modular(
            "models.registry.gemma9b_desc",
            "Google Gemma 2 (9B) - Very powerful, requires more RAM."
        ),
        size_gb=5.5,
        ollama_tag="gemma2:9b",
        mlx_hf_id="mlx-community/gemma-2-9b-it-4bit"
    ),
    "mistral-nemo": ModelEntry(
        short_name="mistral-nemo",
        description=t_modular(
            "models.registry.mistral_nemo_desc",
            "Mistral Nemo (12B) - Large context and strong reasoning."
        ),
        size_gb=7.5,
        ollama_tag="mistral-nemo",
        mlx_hf_id="mlx-community/Mistral-Nemo-Instruct-2407-4bit"
    ),
}

def get_model_entry(name: str) -> Optional[ModelEntry]:
    """Look up a model by its short name."""
    return MODEL_REGISTRY.get(name.lower())

def list_models_table() -> str:
    """Return a formatted table of available models."""
    headers = [
        t_modular("models.registry.header_short_name", "Short Name"),
        t_modular("models.registry.header_size", "Size"),
        t_modular("models.registry.header_description", "Description"),
    ]
    rows = []
    for m in MODEL_REGISTRY.values():
        rows.append(f"{m.short_name:<15} {m.size_gb:>4.1f}GB  {m.description}")
    
    return "\n".join(rows)
