"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/models/registry.py
Description: Curated registry of supported models (MLX & Ollama).
             Maps short names (e.g. "qwen3.5") to real IDs (HF or Ollama library).

             Kept in sync with the canonical v1.0.5 catalog shipped by the
             installer (installer/installer_catalog_data.py :: MODEL_CATALOG):
             4 RAM tiers, models verified empirically (Qwen3.5, Gemma 4,
             Mistral Small 3.2 / Nemo, GPT-OSS, DeepSeek R1, Mixtral, ALIA-40B,
             Salamandra). Short names here are the user-facing `nexe model
             install <name>` handles.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class ModelEntry:
    """Registry entry mapping a short model name to its engine IDs and metadata."""
    short_name: str
    description: str
    size_gb: float
    ollama_tag: str
    mlx_hf_id: str

# Curated registry of models verified to work well with Nexe.
# Aligned with the v1.0.5 installer catalog. `size_gb` is the on-disk size.
# `mlx_hf_id` is empty ("") when the model is not offered via MLX.
MODEL_REGISTRY: Dict[str, ModelEntry] = {
    # --- Small tier (8 GB RAM) ---
    "qwen3.5:4b": ModelEntry(
        short_name="qwen3.5:4b",
        description="Qwen3.5 4B - Multimodal, thinking, vision. Excellent Catalan. Default for 8GB.",
        size_gb=2.9,
        ollama_tag="qwen3.5:4b",
        mlx_hf_id="mlx-community/Qwen3.5-4B-MLX-4bit",
    ),

    # --- Medium tier (16 GB RAM) ---
    "qwen3.5:4b-8bit": ModelEntry(
        short_name="qwen3.5:4b-8bit",
        description="Qwen3.5 4B (8-bit) - Multimodal, thinking, vision. Higher precision.",
        size_gb=3.4,
        ollama_tag="",   # MLX-only (8-bit); Ollama library only ships the 4-bit qwen3.5:4b
        mlx_hf_id="mlx-community/Qwen3.5-4B-MLX-8bit",
    ),
    "qwen3.5:9b": ModelEntry(
        short_name="qwen3.5:9b",
        description="Qwen3.5 9B - Thinking, vision, tool calling. MLX Apple Silicon.",
        size_gb=6.6,
        ollama_tag="qwen3.5:9b",
        mlx_hf_id="mlx-community/Qwen3.5-9B-MLX-4bit",
    ),
    "gemma4:e4b": ModelEntry(
        short_name="gemma4:e4b",
        description="Google Gemma 4 E4B - Vision, thinking, audio (MoE). MLX recommended.",
        size_gb=4.5,
        ollama_tag="gemma4:e4b",
        mlx_hf_id="mlx-community/gemma-4-e4b-it-4bit",
    ),
    "mistral-nemo:12b": ModelEntry(
        short_name="mistral-nemo:12b",
        description="Mistral Nemo 12B - 128K context, Apache 2.0. European multilingual, code.",
        size_gb=7.1,
        ollama_tag="mistral-nemo:12b",
        mlx_hf_id="mlx-community/Mistral-Nemo-Instruct-2407-4bit",
    ),
    "salamandra7b": ModelEntry(
        short_name="salamandra7b",
        description="BSC/AINA Salamandra 7B - Best for Catalan and Iberian languages (MareNostrum 5).",
        size_gb=4.9,
        ollama_tag="hdnh2006/salamandra-7b-instruct:q4_K_M",
        mlx_hf_id="",   # No MLX support (GGUF/Ollama only)
    ),

    # --- Large tier (24 GB RAM) ---
    "qwen3.5:27b": ModelEntry(
        short_name="qwen3.5:27b",
        description="Qwen3.5 27B - Excellent thinking, vision, tool calling. MLX Apple Silicon.",
        size_gb=17.0,
        ollama_tag="qwen3.5:27b",
        mlx_hf_id="mlx-community/Qwen3.5-27B-4bit",
    ),
    "gemma4:31b": ModelEntry(
        short_name="gemma4:31b",
        description="Google Gemma 4 31B - Powerful reasoning, vision, 256K context.",
        size_gb=18.5,
        ollama_tag="gemma4:31b",
        mlx_hf_id="mlx-community/gemma-4-31b-it-8bit",
    ),
    "mistral-small3.2": ModelEntry(
        short_name="mistral-small3.2",
        description="Mistral Small 3.2 24B - Vision, thinking, Apache 2.0. European multilingual.",
        size_gb=14.0,
        ollama_tag="mistral-small3.2",
        mlx_hf_id="lmstudio-community/Mistral-Small-3.2-24B-Instruct-2506-MLX-4bit",
    ),
    "gpt-oss:20b": ModelEntry(
        short_name="gpt-oss:20b",
        description="OpenAI GPT-OSS 20B - Efficient MoE, thinking. Apache 2.0.",
        size_gb=22.2,
        ollama_tag="gpt-oss:20b",
        mlx_hf_id="lmstudio-community/gpt-oss-20b-MLX-8bit",
    ),

    # --- XLarge tier (32 GB+ RAM) ---
    "qwen3.5:35b-a3b": ModelEntry(
        short_name="qwen3.5:35b-a3b",
        description="Qwen3.5 35B-A3B (MoE) - 9B speed with 35B quality. Apache 2.0. MLX Apple Silicon.",
        size_gb=21.0,
        ollama_tag="qwen3.5:35b-a3b",
        mlx_hf_id="mlx-community/Qwen3.5-35B-A3B-4bit",
    ),
    "mixtral:8x7b": ModelEntry(
        short_name="mixtral:8x7b",
        description="Mistral Mixtral 8x7B (MoE) - Efficient, 32K context. Apache 2.0. Robust classic.",
        size_gb=26.0,
        ollama_tag="mixtral:8x7b",
        mlx_hf_id="mlx-community/Mixtral-8x7B-Instruct-v0.1",
    ),
    "deepseek-r1:32b": ModelEntry(
        short_name="deepseek-r1:32b",
        description="DeepSeek R1 Distill 32B - Step-by-step o1-style reasoning. Analysis and documents.",
        size_gb=19.0,
        ollama_tag="deepseek-r1:32b",
        mlx_hf_id="",   # GGUF/Ollama only
    ),
    "alia-40b": ModelEntry(
        short_name="alia-40b",
        description="BSC ALIA-40B Instruct - Advanced public multilingual model (9 Iberian languages).",
        size_gb=42.0,
        ollama_tag="csala/ALIA-40B:Q8_0",
        mlx_hf_id="",   # GGUF/Ollama only
    ),
}

def get_model_entry(name: str) -> Optional[ModelEntry]:
    """Look up a model by its short name."""
    return MODEL_REGISTRY.get(name.lower())

def list_models_table() -> str:
    """Return a formatted table of available models."""
    rows = []
    for m in MODEL_REGISTRY.values():
        rows.append(f"{m.short_name:<18} {m.size_gb:>5.1f}GB  {m.description}")

    return "\n".join(rows)
