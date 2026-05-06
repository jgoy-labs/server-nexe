"""
────────────────────────────────────
Server Nexe
Location: installer/installer_catalog_data.py
Description: Model catalog data (MODEL_CATALOG).
             4 tiers: small (8 GB), medium (16 GB), large (24 GB), xlarge (32 GB).
             Revised 2026-04-16 after empirical testing of 24 models.

             2026-04-23 (F4.1 audit DoD-AUD-SX-0423 §2.7): added
             MODEL_WEIGHT_SHA256 map and get_expected_sha256() helper for
             post-download integrity verification. Kept as a separate map
             so the Swift wizard models.json contract stays unchanged and
             refresh scripts only touch a single structure.
────────────────────────────────────
"""

from __future__ import annotations

from typing import Optional, cast

# ═══════════════════════════════════════════════════════════════════════════
# MODEL CATALOG - 16 models across 4 RAM tiers
# Engines: mlx (Apple Silicon), ollama (universal), llama.cpp (GGUF)
#
# Color code from empirical testing:
#   ✅ green  = available, works
#   🟠 yellow = recommended for this tier
#   🔴 red    = do NOT offer (needs torch, unsupported arch, etc.)
#
# mlx=None means the model is NOT offered via MLX in the installer.
# ═══════════════════════════════════════════════════════════════════════════
MODEL_CATALOG = {
    # ─────────────────────────────────────────────────────────────────────────
    # SMALL MODELS - For 8 GB RAM machines (3 models)
    # Default: Gemma 3 4B (vision + thinking, works on both Ollama + MLX)
    # ─────────────────────────────────────────────────────────────────────────
    "small": [
        {
            "key": "gemma3_4b",
            "name": "Gemma 3 4B",
            "origin": "Google DeepMind",
            "year": 2025,
            "lang": {"ca": "Multilingüe (excel·lent català)", "es": "Multilingüe (excelente catalán)", "en": "Multilingual (excellent Catalan)"},
            "params": "4B",
            "disk_gb": 3.3,
            "ram_gb": 4.0,
            "description": {"ca": "👁 🧠 Visió + raonament en 4 GB. El millor default per a Macs amb 8 GB.", "es": "👁 🧠 Visión + razonamiento en 4 GB. El mejor default para Macs con 8 GB.", "en": "👁 🧠 Vision + reasoning in 4 GB. Best default for 8 GB Macs."},
            "mlx": "mlx-community/gemma-3-4b-it-4bit",
            "ollama": "gemma3:4b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "small",
            "recommended": True,
        },
        {
            "key": "qwen35_4b",
            "name": "Qwen3.5 4B",
            "origin": "Alibaba",
            "year": 2026,
            "lang": {"ca": "Multilingüe (excel·lent català)", "es": "Multilingüe (excelente catalán)", "en": "Multilingual (excellent Catalan)"},
            "params": "4B",
            "disk_gb": 3.4,
            "ram_gb": 4.0,
            "description": {"ca": "👁 🧠 Multimodal, thinking, visió. Ollama recomanat (MLX requereix torch).", "es": "👁 🧠 Multimodal, thinking, visión. Ollama recomendado (MLX requiere torch).", "en": "👁 🧠 Multimodal, thinking, vision. Ollama recommended (MLX requires torch)."},
            "mlx": None,
            "ollama": "qwen3.5:4b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "small",
            "recommended": True,
        },
        {
            "key": "qwen3_4b",
            "name": "Qwen3 4B",
            "origin": "Alibaba",
            "year": 2025,
            "lang": {"ca": "Multilingüe +100 idiomes", "es": "Multilingüe +100 idiomas", "en": "Multilingual +100 languages"},
            "params": "4B",
            "disk_gb": 2.5,
            "ram_gb": 4.0,
            "description": {"ca": "Model de text lleuger i ràpid. Apache 2.0.", "es": "Modelo de texto ligero y rápido. Apache 2.0.", "en": "Lightweight fast text model. Apache 2.0."},
            "mlx": "mlx-community/Qwen3-4B-4bit",
            "ollama": "qwen3:4b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "small",
        },
        {
            "key": "qwen3_vl_4b",
            "name": "Qwen3-VL 4B",
            "origin": "Alibaba",
            "year": 2026,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "4B",
            "disk_gb": 3.1,
            "ram_gb": 4.5,
            "description": {"ca": "👁 🧠 VLM natiu Qwen3 — visió, thinking, text. MLX Apple Silicon.", "es": "👁 🧠 VLM nativo Qwen3 — visión, thinking, texto. MLX Apple Silicon.", "en": "👁 🧠 Qwen3 native VLM — vision, thinking, text. MLX Apple Silicon."},
            "mlx": "mlx-community/Qwen3-VL-4B-Instruct-4bit",
            "ollama": "qwen3-vl:4b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
    ],
    # ─────────────────────────────────────────────────────────────────────────
    # MEDIUM MODELS - For 16 GB RAM machines (4 models)
    # Recommended MLX: Gemma 4 E4B, Gemma 3 12B
    # ─────────────────────────────────────────────────────────────────────────
    "medium": [
        {
            "key": "gemma4_e4b",
            "name": "Gemma 4 E4B",
            "origin": "Google",
            "year": 2026,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "8B totals / ~4-8B efectius (MoE)",
            "disk_gb": 4.5,
            "ram_gb": 6.0,
            "description": {"ca": "👁 🧠 Visió, thinking, àudio. MLX recomanat.", "es": "👁 🧠 Visión, thinking, audio. MLX recomendado.", "en": "👁 🧠 Vision, thinking, audio. MLX recommended."},
            "mlx": "mlx-community/gemma-4-e4b-it-4bit",
            "ollama": "gemma4:e4b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
            "recommended": True,
        },
        {
            "key": "salamandra7b",
            "name": "Salamandra 7B",
            "origin": "BSC/AINA (Catalunya)",
            "year": 2025,
            "lang": {"ca": "Català, Castellà, Euskera, Gallec", "es": "Catalán, Castellano, Euskera, Gallego", "en": "Catalan, Spanish, Basque, Galician"},
            "params": "7B",
            "disk_gb": 4.9,
            "ram_gb": 6.0,
            "description": {"ca": "El millor per català i llengües ibèriques. Entrenat al MareNostrum 5.", "es": "El mejor para catalán y lenguas ibéricas. Entrenado en MareNostrum 5.", "en": "Best for Catalan and Iberian languages. Trained on MareNostrum 5."},
            "mlx": None,
            "ollama": "hdnh2006/salamandra-7b-instruct:q4_K_M",
            "gguf": "https://huggingface.co/hdnh2006/BSC-LT-salamandra-7b-instruct-gguf/resolve/main/salamandra-7b-instruct-Q4_K_M.gguf",
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
        {
            "key": "qwen35_9b",
            "name": "Qwen3.5 9B",
            "origin": "Alibaba",
            "year": 2026,
            "lang": {"ca": "Multilingüe (excel·lent català)", "es": "Multilingüe (excelente catalán)", "en": "Multilingual (excellent Catalan)"},
            "params": "9B",
            "disk_gb": 6.6,
            "ram_gb": 8.0,
            "description": {"ca": "👁 🧠 Thinking, visió, tool calling. Ollama recomanat (MLX requereix torch).", "es": "👁 🧠 Thinking, visión, tool calling. Ollama recomendado (MLX requiere torch).", "en": "👁 🧠 Thinking, vision, tool calling. Ollama recommended (MLX requires torch)."},
            "mlx": None,
            "ollama": "qwen3.5:9b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
            "recommended": True,
        },
        {
            "key": "gemma3_12b",
            "name": "Gemma 3 12B",
            "origin": "Google DeepMind",
            "year": 2025,
            "lang": {"ca": "Multilingüe (excel·lent català)", "es": "Multilingüe (excelente catalán)", "en": "Multilingual (excellent Catalan)"},
            "params": "12B",
            "disk_gb": 7.0,
            "ram_gb": 9.0,
            "description": {"ca": "👁 🧠 Visió, raonament, excel·lent RAG i català.", "es": "👁 🧠 Visión, razonamiento, excelente RAG y catalán.", "en": "👁 🧠 Vision, reasoning, excellent RAG and Catalan."},
            "mlx": "mlx-community/gemma-3-12b-it-4bit",
            "ollama": "gemma3:12b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
        {
            "key": "qwen3_vl_8b",
            "name": "Qwen3-VL 8B",
            "origin": "Alibaba",
            "year": 2026,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "8B",
            "disk_gb": 5.8,
            "ram_gb": 8.0,
            "description": {"ca": "👁 🧠 VLM Qwen3 — visió nativa, thinking, context 128K. MLX Apple Silicon.", "es": "👁 🧠 VLM Qwen3 — visión nativa, thinking, contexto 128K. MLX Apple Silicon.", "en": "👁 🧠 Qwen3 VLM — native vision, thinking, 128K context. MLX Apple Silicon."},
            "mlx": "mlx-community/Qwen3-VL-8B-Instruct-4bit",
            "ollama": "qwen3-vl:8b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
    ],
    # ─────────────────────────────────────────────────────────────────────────
    # LARGE MODELS - For 24 GB RAM machines (3 models)
    # ─────────────────────────────────────────────────────────────────────────
    "large": [
        {
            "key": "gemma4_31b",
            "name": "Gemma 4 31B",
            "origin": "Google",
            "year": 2026,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "31B (dense)",
            "disk_gb": 18.5,
            "ram_gb": 10.0,
            "description": {"ca": "👁 🧠 Raonament potent, visió, context 256K.", "es": "👁 🧠 Razonamiento potente, visión, contexto 256K.", "en": "👁 🧠 Powerful reasoning, vision, 256K context."},
            "mlx": "mlx-community/gemma-4-31b-it-8bit",
            "ollama": "gemma4:31b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
            "recommended": True,
        },
        {
            "key": "qwen3_14b",
            "name": "Qwen3 14B",
            "origin": "Alibaba",
            "year": 2025,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "14B",
            "disk_gb": 9.3,
            "ram_gb": 11.0,
            "description": {"ca": "🧠 Thinking, codi, raonament. Molt bon equilibri per a 24 GB.", "es": "🧠 Thinking, código, razonamiento. Muy buen equilibrio para 24 GB.", "en": "🧠 Thinking, code, reasoning. Great balance for 24 GB."},
            "mlx": "mlx-community/Qwen3-14B-MLX-4bit",
            "ollama": "qwen3:14b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
            "recommended": True,
        },
        {
            "key": "gpt_oss_20b",
            "name": "GPT-OSS 20B",
            "origin": "OpenAI (Open Source)",
            "year": 2025,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "21B (MoE, 3.6B actius)",
            "disk_gb": 22.2,
            "ram_gb": 16.0,
            "description": {"ca": "🧠 Model obert d'OpenAI, MoE eficient. Thinking. Apache 2.0.", "es": "🧠 Modelo abierto de OpenAI, MoE eficiente. Thinking. Apache 2.0.", "en": "🧠 OpenAI open model, efficient MoE. Thinking. Apache 2.0."},
            "mlx": "lmstudio-community/gpt-oss-20b-MLX-8bit",
            "ollama": "gpt-oss:20b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
    ],
    # ─────────────────────────────────────────────────────────────────────────
    # XLARGE MODELS - For 32 GB+ RAM machines (6 models)
    # Recommended MLX: Gemma 4 31B. Recommended Ollama: ALIA-40B (ibèric)
    # ─────────────────────────────────────────────────────────────────────────
    "xlarge": [
        {
            "key": "qwen35_27b",
            "name": "Qwen3.5 27B",
            "origin": "Alibaba",
            "year": 2026,
            "lang": {"ca": "Multilingüe (excel·lent català)", "es": "Multilingüe (excelente catalán)", "en": "Multilingual (excellent Catalan)"},
            "params": "27B",
            "disk_gb": 17.0,
            "ram_gb": 20.0,
            "description": {"ca": "👁 🧠 Thinking excel·lent, visió, tool calling. Ollama recomanat (MLX requereix torch).", "es": "👁 🧠 Thinking excelente, visión, tool calling. Ollama recomendado (MLX requiere torch).", "en": "👁 🧠 Excellent thinking, vision, tool calling. Ollama recommended (MLX requires torch)."},
            "mlx": None,
            "ollama": "qwen3.5:27b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
        {
            "key": "gemma3_27b",
            "name": "Gemma 3 27B",
            "origin": "Google DeepMind",
            "year": 2025,
            "lang": {"ca": "Multilingüe (excel·lent català)", "es": "Multilingüe (excelente catalán)", "en": "Multilingual (excellent Catalan)"},
            "params": "27B",
            "disk_gb": 16.2,
            "ram_gb": 20.0,
            "description": {"ca": "👁 🧠 Visió, raonament, excel·lent memòria RAG i català.", "es": "👁 🧠 Visión, razonamiento, excelente memoria RAG y catalán.", "en": "👁 🧠 Vision, reasoning, excellent RAG memory and Catalan."},
            "mlx": "mlx-community/gemma-3-27b-it-qat-4bit",
            "ollama": None,
            "gguf": "https://huggingface.co/bartowski/gemma-3-27b-it-GGUF/resolve/main/gemma-3-27b-it-Q4_K_M.gguf",
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
        {
            "key": "deepseek_r1_distill_32b",
            "name": "DeepSeek R1 Distill 32B",
            "origin": "DeepSeek AI (Xina)",
            "year": 2025,
            "lang": {"ca": "Multilingüe (raonament avançat)", "es": "Multilingüe (razonamiento avanzado)", "en": "Multilingual (advanced reasoning)"},
            "params": "32B (Distill Qwen)",
            "disk_gb": 19.0,
            "ram_gb": 22.0,
            "description": {"ca": "🧠 Raonament pas a pas estil o1. Ideal per anàlisi i documents.", "es": "🧠 Razonamiento paso a paso estilo o1. Ideal para análisis y documentos.", "en": "🧠 Step-by-step o1-style reasoning. Ideal for analysis and documents."},
            "mlx": None,
            "ollama": "deepseek-r1:32b",
            "gguf": "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf",
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
        {
            "key": "gemma4_31b",
            "name": "Gemma 4 31B",
            "origin": "Google",
            "year": 2026,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "31B (dense)",
            "disk_gb": 18.5,
            "ram_gb": 22.0,
            "description": {"ca": "👁 🧠 Raonament, visió, context 256K. MLX recomanat amb 32 GB.", "es": "👁 🧠 Razonamiento, visión, contexto 256K. MLX recomendado con 32 GB.", "en": "👁 🧠 Reasoning, vision, 256K context. MLX recommended with 32 GB."},
            "mlx": "mlx-community/gemma-4-31b-it-8bit",
            "ollama": "gemma4:31b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
            "recommended": True,
        },
        {
            "key": "qwen35_35b_moe",
            "name": "Qwen3.5 35B-A3B",
            "origin": "Alibaba",
            "year": 2026,
            "lang": {"ca": "Multilingüe (excel·lent català)", "es": "Multilingüe (excelente catalán)", "en": "Multilingual (excellent Catalan)"},
            "params": "35B totals / 3B actius (MoE)",
            "disk_gb": 21.0,
            "ram_gb": 23.0,
            "description": {"ca": "👁 🧠 Velocitat de 9B amb qualitat de 35B. Apache 2.0.", "es": "👁 🧠 Velocidad de 9B con calidad de 35B. Apache 2.0.", "en": "👁 🧠 9B speed with 35B quality. Apache 2.0."},
            "mlx": None,
            "ollama": "qwen3.5:35b-a3b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
        {
            "key": "qwen3_vl_30b_a3b",
            "name": "Qwen3-VL 30B-A3B",
            "origin": "Alibaba",
            "year": 2026,
            "lang": {"ca": "Multilingüe", "es": "Multilingüe", "en": "Multilingual"},
            "params": "30B totals / 3B actius (MoE)",
            "disk_gb": 18.3,
            "ram_gb": 20.0,
            "description": {"ca": "👁 🧠 VLM MoE Qwen3 — visió, thinking, velocitat 3B amb qualitat 30B.", "es": "👁 🧠 VLM MoE Qwen3 — visión, thinking, velocidad 3B con calidad 30B.", "en": "👁 🧠 Qwen3 MoE VLM — vision, thinking, 3B speed with 30B quality."},
            "mlx": "mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit",
            "ollama": "qwen3-vl:30b-a3b",
            "gguf": None,
            "chat_format": "chatml",
            "prompt_tier": "full",
        },
        {
            "key": "alia_40b",
            "name": "ALIA-40B Instruct",
            "origin": "BSC (Catalunya)",
            "year": 2026,
            "lang": {"ca": "Llengües ibèriques (9 idiomes)", "es": "Lenguas ibéricas (9 idiomas)", "en": "Iberian languages (9)"},
            "params": "40B",
            "disk_gb": 42.0,
            "ram_gb": 24.0,
            "description": {"ca": "Model públic multilingüe avançat fet a Europa. 9 idiomes ibèrics.", "es": "Modelo público multilingüe avanzado hecho en Europa. 9 idiomas ibéricos.", "en": "Advanced public multilingual model made in Europe. 9 Iberian languages."},
            "mlx": None,
            "ollama": "csala/ALIA-40B:Q8_0",
            "gguf": "https://huggingface.co/BSC-LT/ALIA-40b-instruct-2601-GGUF/resolve/main/ALIA-40b-instruct-2601-Q8_0.gguf",
            "chat_format": "chatml",
            "prompt_tier": "full",
            "recommended": True,
        },
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRITY — SHA256 pins for downloaded model weights (F4.1 audit DoD-AUD-SX-0423)
# ═══════════════════════════════════════════════════════════════════════════
# Map: (engine, model_id) → sha256 expected hex digest (64 chars) or None.
#
#   - engine: "mlx" | "ollama" | "gguf"
#   - model_id: the exact string stored in MODEL_CATALOG[_]["mlx"/"ollama"/"gguf"]
#
# A ``None`` entry means the hash has not been pinned yet. The installer
# logs a visible warning and proceeds (legacy mode). When a concrete
# digest is present the installer aborts hard on mismatch — see
# :func:`core.integrity.hashing.verify_sha256`.
#
# Hash formats by engine:
#   - "mlx":    sha256 of the local snapshot_download directory, computed
#               with ``core.integrity.hashing.sha256_of_dir`` (dotfile
#               filter applied to skip HF cache .lock / .no_exist noise).
#   - "ollama": sha256 reported by ``ollama show <model> --json`` under
#               ``details.digest`` (hex, 64 lowercase chars).
#   - "gguf":   sha256 of the downloaded .gguf file, single-shot
#               ``core.integrity.hashing.sha256_of_file``.
#
# Keep this map in sync with MODEL_CATALOG: any new entry there MUST
# ship an entry here (value may be None). The smoke test in
# ``tests/test_installer_sha256_catalog.py`` enforces this.
#
# Refresh the values with ``scripts/refresh_model_hashes.py`` (optional
# F4.1.b tool — regenerates from HF Hub API + local ollama daemon).
#
# ───────────────────────────────────────────────────────────────────────────
# STATUS v1.0.4-beta (C19, 2026-05-06): Ollama config digests + Salamandra GGUF
# poblats. MLX dir-hashes poblats per als models disponibles a Wintermute.
# Valors None restants: models no descarregats localment en el moment del pin.
# ───────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
MODEL_WEIGHT_SHA256: dict[tuple[str, str], Optional[str]] = {
    # ── MLX snapshots (dir hash) ──────────────────────────────────────────
    ("mlx", "mlx-community/gemma-3-4b-it-4bit"): None,
    ("mlx", "mlx-community/Qwen3-4B-4bit"): None,
    ("mlx", "mlx-community/gemma-4-e4b-it-4bit"): "950d9dea946fb1e85a4e99fd25bdd1fbf0cbc6cfc83298f69bb20190aa9aad72",
    ("mlx", "mlx-community/gemma-3-12b-it-4bit"): "7bd7a65af1fe3b1b2e1f67c6ac7131c8e3fae2bc038100a11762a16ed330076f",
    ("mlx", "mlx-community/gemma-4-31b-it-8bit"): "d4cc8cfd30ce9169e9ae6367deff2f8cb93ae28f4991f72e4e2e58f03c6eb0bd",
    ("mlx", "mlx-community/Qwen3-14B-MLX-4bit"): "c557fee4d7cde6e905b497dc534808ed308bb927ef27f067aeabb32340d77b41",
    ("mlx", "lmstudio-community/gpt-oss-20b-MLX-8bit"): "b9c812af1572191e123c19cd0ad3bf726867e5a86dd09ee2fab62e6efdc4ef0f",
    ("mlx", "mlx-community/gemma-3-27b-it-qat-4bit"): "50cd9ec15dc6c57888d0df6442e645d726dd7857f1fb2aaf9653fc1f585c7d99",
    ("mlx", "mlx-community/Qwen3-VL-4B-Instruct-4bit"): None,
    ("mlx", "mlx-community/Qwen3-VL-8B-Instruct-4bit"): None,
    ("mlx", "mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit"): None,
    ("ollama", "qwen3-vl:4b"): None,
    ("ollama", "qwen3-vl:8b"): None,
    ("ollama", "qwen3-vl:30b-a3b"): None,
    # ── Ollama manifest digests (config digest, verified 2026-05-06) ────────
    ("ollama", "gemma3:4b"): "b6ae5839783f2ba248e65e4b960ab15f9c4b7118db285827dba6cba9754759e2",
    ("ollama", "qwen3.5:4b"): "de9fed2251b37295b763727a59ca35cf5cfe5c7379bc3e2104b2ce3c145aa887",
    ("ollama", "qwen3:4b"): "e18a783aae5525fd2852fc94c985541a77e791e034abc2d3056474d59de336fc",
    ("ollama", "gemma4:e4b"): "f0988ff50a2458c598ff6b1b87b94d0f5c44d73061c2795391878b00b2285e11",
    ("ollama", "hdnh2006/salamandra-7b-instruct:q4_K_M"): "b7c01a6aaa23015739006a60492f84ae5931712c32e42638c4022b5c5a175d73",
    ("ollama", "qwen3.5:9b"): "be595b49fe22012bd1f5605ec14c7ffa58331783a88a4fd8c22e5fc8ec42cf9f",
    ("ollama", "gemma3:12b"): None,
    ("ollama", "gemma4:31b"): "0940386273ff9ddd5ede7c5ddaa0e925b50154e198ea977fb64aa1ca94a3a137",
    ("ollama", "qwen3:14b"): "78b3b822087d5199783c8203553a5a92ce5eb7b683a5a81003f8efea9b399d74",
    ("ollama", "gpt-oss:20b"): None,
    ("ollama", "qwen3.5:27b"): "ba0915cbf15878a68d300f640d3d575f5805cac42dd8f83746eb31a0e8afec22",
    ("ollama", "deepseek-r1:32b"): None,
    ("ollama", "qwen3.5:35b-a3b"): "606ad9f1ecbcd0d400a89572f49d9a8e80b11a346be74883245e24ecbbc3ac81",
    ("ollama", "csala/ALIA-40B:Q8_0"): None,
    # ── GGUF direct downloads (single-file hash) ──────────────────────────
    (
        "gguf",
        "https://huggingface.co/hdnh2006/BSC-LT-salamandra-7b-instruct-gguf/resolve/main/salamandra-7b-instruct-Q4_K_M.gguf",
    ): "da90a4badcb493ddf7a213b6775732c775f75347a0560f8e1c586ba6ed07596c",
    (
        "gguf",
        "https://huggingface.co/bartowski/gemma-3-27b-it-GGUF/resolve/main/gemma-3-27b-it-Q4_K_M.gguf",
    ): None,
    (
        "gguf",
        "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf",
    ): None,
    (
        "gguf",
        "https://huggingface.co/BSC-LT/ALIA-40b-instruct-2601-GGUF/resolve/main/ALIA-40b-instruct-2601-Q8_0.gguf",
    ): None,
}

# Canonical engines recognised by ``get_expected_sha256``. Extending the
# installer with a new engine (e.g. MLX-VLM) requires adding it here and
# seeding MODEL_WEIGHT_SHA256 with the relevant ids.
VALID_SHA256_ENGINES: frozenset[str] = frozenset({"mlx", "ollama", "gguf"})


def get_expected_sha256(engine: str, model_id: str) -> Optional[str]:
    """Return the pinned SHA256 for ``(engine, model_id)``.

    Returns ``None`` when:
    * the ``(engine, model_id)`` pair exists in MODEL_WEIGHT_SHA256 but
      is still unpinned (legacy mode), or
    * the pair is absent altogether — e.g. a local dev tag the user added
      to Ollama. The installer treats "absent" and "pinned as None"
      identically: a warning plus continue.

    Raises
    ------
    ValueError
        ``engine`` is not one of ``VALID_SHA256_ENGINES``. Callers that
        introduce a new engine must update both the catalog and this
        helper together, so an unknown engine is a coding bug, not a
        legacy condition to swallow.
    """
    if engine not in VALID_SHA256_ENGINES:
        raise ValueError(
            f"Unknown engine {engine!r} for SHA256 lookup. "
            f"Expected one of: {sorted(VALID_SHA256_ENGINES)}"
        )
    return MODEL_WEIGHT_SHA256.get((engine, model_id))


def iter_catalog_model_ids() -> list[tuple[str, str]]:
    """List every ``(engine, model_id)`` pair referenced by MODEL_CATALOG.

    Used by the smoke test to enforce that every downloadable artefact in
    the catalog has an entry in ``MODEL_WEIGHT_SHA256`` (value may be
    ``None``). New models without an entry would otherwise silently bypass
    the integrity check.
    """
    pairs: list[tuple[str, str]] = []
    for category in MODEL_CATALOG.values():
        for model in category:
            for engine_key in ("mlx", "ollama", "gguf"):
                value = model.get(engine_key)
                if value:
                    pairs.append((engine_key, cast(str, value)))
    return pairs
