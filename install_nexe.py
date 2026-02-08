#!/usr/bin/env python3
"""
────────────────────────────────────
Server Nexe
Version: 0.8.0
Author: Jordi Goy
Location: install_nexe.py
Description: Universal Interactive Installer for Nexe 0.8.
Adaptive for Apple Silicon, RPi, and x86_64.
Multi-language support: CA/ES/EN
LLM model selection with MLX/GGUF support.

www.jgoy.net
────────────────────────────────────
"""

import os
import sys
import subprocess
import platform
import re
import shutil
import time
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
# UI CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
CYAN = "\033[1;36m"
MAGENTA = "\033[1;35m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

APP_LOGO = f"""{RED}
      _
     / /  ___  ___ _ ____   _____ _ __    _ __   _____  __  ___
    / /  / __|/ _ \\ '__\\ \\ / / _ \\ '__|  | '_ \\ / _ \\ \\ \\/ / _ \\
   / /   \\__ \\  __/ |   \\ V /  __/ |  _  | | | |  __/>  <  __/
  /_/    |___/\\___|_|    \\_/ \\___|_| (_) |_| |_|\\___/_/\\_\\___|
{RESET}
                     {BOLD}NEXE{RESET}

      {DIM}Personal project by Jordi Goy learning by doing
           assisted by IA · www.jgoy.net{RESET}
"""

# ═══════════════════════════════════════════════════════════════════════════
# MODEL CATALOG - Multiple options per category, including Catalan models
# Engines: mlx (Apple Silicon), ollama (universal)
# ═══════════════════════════════════════════════════════════════════════════
MODEL_CATALOG = {
    # ─────────────────────────────────────────────────────────────────────────
    # SMALL MODELS - For 8GB RAM machines
    # ─────────────────────────────────────────────────────────────────────────
    "small": [
        {
            "key": "phi35",
            "name": "Phi-3.5 Mini",
            "origin": "Microsoft",
            "lang": "Multilingüe (Anglès principal)",
            "params": "3.8B",
            "disk_gb": 2.4,   # Disk space
            "ram_gb": 3.5,    # RAM needed when running
            "description": "Molt ràpid, bo per tasques generals",
            "mlx": "mlx-community/Phi-3.5-mini-instruct-4bit",
            "ollama": "phi3:mini",
            "gguf": "https://huggingface.co/microsoft/Phi-3.5-mini-instruct-gguf/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf",
        },
        {
            "key": "salamandra2b",
            "name": "Salamandra 2B",
            "origin": "BSC/AINA (Catalunya)",
            "lang": "Català, Castellà, Euskera, Gallec",
            "params": "2B",
            "disk_gb": 1.5,   # Disk space
            "ram_gb": 2.5,    # RAM needed when running
            "description": "Optimitzat per llengües ibèriques",
            "mlx": None,
            "ollama": "hdnh2006/salamandra-2b-instruct",
            "gguf": None,  # No GGUF available yet
        },
    ],
    # ─────────────────────────────────────────────────────────────────────────
    # MEDIUM MODELS - For 12-16GB RAM machines
    # ─────────────────────────────────────────────────────────────────────────
    "medium": [
        {
            "key": "mistral7b",
            "name": "Mistral 7B",
            "origin": "Mistral AI (França)",
            "lang": "Multilingüe",
            "params": "7B",
            "disk_gb": 4.1,   # Disk space
            "ram_gb": 5.5,    # RAM needed when running
            "description": "Excel·lent equilibri qualitat/velocitat",
            "mlx": "mlx-community/Mistral-7B-Instruct-v0.3-4bit",
            "ollama": "mistral:7b",
            "gguf": "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        },
        {
            "key": "salamandra7b",
            "name": "Salamandra 7B",
            "origin": "BSC/AINA (Catalunya)",
            "lang": "Català, Castellà, Euskera, Gallec",
            "params": "7B",
            "disk_gb": 4.9,   # Disk space
            "ram_gb": 6.5,    # RAM needed when running
            "description": "El millor per català i llengües ibèriques",
            "mlx": None,
            "ollama": "cas/salamandra-7b-instruct",
            "gguf": "https://huggingface.co/cstr/salamandra-7b-instruct-GGUF/resolve/main/salamandra-7b-instruct-Q4_K_M.gguf",
        },
        {
            "key": "llama31_8b",
            "name": "Llama 3.1 8B",
            "origin": "Meta",
            "lang": "Multilingüe",
            "params": "8B",
            "disk_gb": 4.7,   # Disk space
            "ram_gb": 6.0,    # RAM needed when running
            "description": "Molt popular, excel·lent qualitat",
            "mlx": "mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
            "ollama": "llama3.1:8b",
            "gguf": "https://huggingface.co/lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        },
    ],
    # ─────────────────────────────────────────────────────────────────────────
    # LARGE MODELS - For 32GB+ RAM machines
    # ─────────────────────────────────────────────────────────────────────────
    "large": [
        {
            "key": "mixtral",
            "name": "Mixtral 8x7B",
            "origin": "Mistral AI (França)",
            "lang": "Multilingüe",
            "params": "47B (MoE)",
            "disk_gb": 26,    # Disk space
            "ram_gb": 32,     # RAM needed when running
            "description": "Màxima qualitat, model MoE",
            "mlx": "mlx-community/Mixtral-8x7B-Instruct-v0.1-4bit",
            "ollama": "mixtral:8x7b",
            "gguf": "https://huggingface.co/TheBloke/Mixtral-8x7B-Instruct-v0.1-GGUF/resolve/main/mixtral-8x7b-instruct-v0.1.Q4_K_M.gguf",
        },
        {
            "key": "llama31_70b",
            "name": "Llama 3.1 70B",
            "origin": "Meta",
            "lang": "Multilingüe",
            "params": "70B",
            "disk_gb": 40,    # Disk space
            "ram_gb": 48,     # RAM needed when running
            "description": "El millor de Meta, qualitat professional",
            "mlx": "mlx-community/Meta-Llama-3.1-70B-Instruct-4bit",
            "ollama": "llama3.1:70b",
            "gguf": "https://huggingface.co/lmstudio-community/Meta-Llama-3.1-70B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-70B-Instruct-Q4_K_M.gguf",
        },
    ],
}

# ═══════════════════════════════════════════════════════════════════════════
# TRANSLATIONS
# ═══════════════════════════════════════════════════════════════════════════
TRANSLATIONS = {
    "ca": {
        "lang_name": "Català",
        "analyzing_hardware": "Analitzant el teu hardware · Revisa que les dades siguin correctes",
        "platform": "Plataforma",
        "ram_available": "RAM Disponible",
        "disk_space": "Disc Disponible",
        "disk_free_of_total": "lliures / {total} GB total",
        "metal_support": "Suport Metal (GPU)",
        "yes": "Sí",
        "no": "No",
        "proceed_install": "Vols procedir amb la instal·lació?",
        "yes_no": "(S/n)",
        "yes_no_default_no": "(S/N)",
        "setting_up_env": "Configurant entorn virtual i dependències...",
        "creating_venv": "Creant entorn virtual...",
        "installing_deps": "Instal·lant dependències des de requirements.txt...",
        "requirements_not_found": "Fitxer requirements.txt no trobat!",
        "installing_inference": "Instal·lant motors d'inferència optimitzats...",
        "detected_apple": "Detectat Apple Silicon. Instal·lant",
        "mlx_version_fallback": "mlx-lm>=0.30.0 no disponible, instal·lant una versió compatible.",
        "installing_universal": "Instal·lant motor universal...",
        "installed_gpu": "instal·lat amb suport hardware.",
        "gpu_failed": "No s'ha pogut compilar amb GPU. Instal·lant versió CPU...",
        "generating_security": "Generant credencials de seguretat (.env)...",
        "security_explanation": "Claus d'accés per protegir la teva IA. Es guarden al fitxer .env",
        "env_created": ".env creat amb Clau API segura.",
        "api_key": "Clau API Mestra",
        "saved_at": "Guardada a",
        "env_exists": ".env ja existeix. No s'ha sobreescrit.",
        "preparing_data": "Preparant estructures de dades...",
        "module_cache_cleaned": "Cache de mòduls netejada.",
        "cache_explanation": "Neteja configuracions antigues per evitar conflictes",
        "executable_created": "Executable 'nexe' creat a l'arrel.",
        "executable_explanation": "Crea el comandament './nexe' per interactuar amb la IA",
        "symlink_created": "Symlink creat a /usr/local/bin/nexe",
        "symlink_global": "Pots usar 'nexe' des de qualsevol lloc del terminal",
        "symlink_failed": "No es pot crear symlink global (permisos)",
        "symlink_manual": "Per usar 'nexe' des de qualsevol lloc, afegeix això al teu ~/.zshrc o ~/.bashrc:",
        "downloading_qdrant": "Descarregant Qdrant (base de dades vectorial)...",
        "qdrant_explanation": "Emmagatzema el coneixement de la teva IA (memòria RAG)",
        "qdrant_download_info": """
  {bold}ℹ️  Què és Qdrant?{reset}
  Qdrant és una base de dades vectorial de codi obert (https://qdrant.tech).
  Permet que la teva IA tingui memòria persistent i pugui recordar converses
  i cercar informació semànticament (no només per paraules clau).

  {bold}📦 Mida:{reset} ~50MB (binari precompilat)
  {bold}🔒 Origen:{reset} GitHub oficial de Qdrant (https://github.com/qdrant/qdrant)

  Sense Qdrant, la IA no tindrà memòria RAG (però funcionarà igualment).
""",
        "qdrant_download_prompt": "Vols descarregar Qdrant ara?",
        "qdrant_skipped": "Qdrant omès. La memòria RAG no estarà disponible.",
        "qdrant_exists": "Qdrant ja existeix.",
        "qdrant_downloaded": "Qdrant descarregat correctament!",
        "qdrant_download_failed": "Error descarregant Qdrant",
        "install_complete": "NEXE SERVER INSTAL·LAT CORRECTAMENT!",
        "basic_commands": "COMANDES BÀSIQUES:",
        "activate_env": "Activar entorn",
        "start_server": "Arrencar Server",
        "local_chat": "Chat Local",
        "view_logs": "Veure Logs",
        "system_status": "Estat Sistema",
        "ingest_data": "Ingesta dades",
        "general_help": "Ajuda General",
        "tip": "Consell",
        "tip_text": "La memòria semàntica (RAG) s'activa per defecte. Usa './nexe chat --no-rag' per desactivar-la.",
        "tested_warning": "Testejat en Apple Silicon (M1/M2/M4) des de 8GB RAM. No testejat en Linux.",
        "how_to_start": "COM ARRENCAR NEXE:",
        "step_activate_venv": "Activa el teu entorn virtual (aïlla les dependències del sistema)",
        "step_start_server": "Inicia el servidor (arrenca la IA en segon pla)",
        "step_new_terminal": "Obre un nou terminal",
        "step_chat": "Escriu per xatejar amb la teva IA local",
        "save_memory_tip": "Per guardar coses a la memòria usa /save, /guardar o /recorda",
        "venv_automatic": "No cal activar el venv, './nexe' ja ho fa automàticament",
        "step": "Pas",
        "disclaimer_title": "PROJECTE PERSONAL · CONTRIBUCIONS BENVINGUDES",
        "disclaimer_bugs": "Pot contenir bugs, si en trobes si us plau avisa'ns.",
        "disclaimer_tested": "Només testejat en Apple Silicon. Contribueix lliurement:",
        "disclaimer_contribute": "rómpelo, porta'l al límit, monta mòduls nous.",
        "disclaimer_thanks": "Gràcies a la comunitat OSS per les eines que han fet possible Nexe.",
        "disclaimer_docs": "Llegeix la documentació a knowledge/ per entendre el sistema.",
        # Model selection
        "select_model": "Selecciona el Model d'IA",
        "recommended": "RECOMANAT",
        "model_size": "Mida",
        "model_ram": "RAM mín.",
        "model_speed": "Velocitat",
        "model_selection_title": "🤖 SELECCIÓ DE MODEL D'IA",
        "model_selection_ram_label": "La teva RAM:",
        "model_selection_ram_available_label": "RAM disponible per IA:",
        "model_selection_ram_percent": "(50-60% del total)",
        "model_selection_ram_note": "La resta es reserva per macOS, navegador i altres apps.",
        "model_size_title": "📦 MIDA DE MODELS",
        "model_size_option_small": "Models petits (8GB RAM) - Ràpids, menys qualitat",
        "model_size_option_medium": "Models mitjans (16GB RAM) - Equilibrats",
        "model_size_option_large": "Models grans (32GB+ RAM) - Màxima qualitat",
        "model_size_label_small": "petits",
        "model_size_label_medium": "mitjans",
        "model_size_label_large": "grans",
        "model_size_recommended": "Recomanat per la teva RAM: models {rec_label}",
        "model_size_prompt": "Escull mida [1-3] (Enter = {recommended}):",
        "model_category_small": "MODELS PETITS (per 8GB RAM)",
        "model_category_medium": "MODELS MITJANS (per 16GB RAM)",
        "model_category_large": "MODELS GRANS (per 32GB+ RAM)",
        "model_engines_label": "Motors",
        "model_disk_label": "Disc",
        "model_ram_label": "RAM",
        "model_choice_prompt": "Escull model [1-{count}] (Enter = {default}):",
        "model_status_compatible": "✓ Compatible",
        "model_status_maybe_tight": "⚠️ Pot anar just",
        "model_tag_local_language": "CATALÀ",
        "engine_desc_mlx": "Optimitzat per Apple Silicon (GPU Metal)",
        "engine_desc_ollama": "Universal, fàcil d'usar",
        "engine_desc_gguf": "Execució local directa, sense dependències",
        "engine_choice_prompt": "Escull [1-{count}] (Enter = {default}):",
        "engine_single_notice": "{model} s'executarà amb {engine}",
        "download_gguf": "Per descarregar el model GGUF:",
        "none": "Cap",
        "model_type_mlx": "MLX (Metal GPU - Més ràpid)",
        "model_type_gguf": "GGUF/Ollama (CPU/GPU Universal)",
        "select_size": "Quina mida de model vols?",
        "size_small": "Petit (1B) - Ràpid, menys precís",
        "size_medium": "Mitjà (3B) - Equilibrat",
        "size_large": "Gran (8B) - Més precís",
        "size_xl": "Extra Gran (70B) - Màxima qualitat",
        "select_engine": "Quin motor d'inferència prefereixes?",
        "engine_explanation": "El motor és el programa que executa el model d'IA al teu Mac.\nCada un té avantatges diferents (velocitat, compatibilitat, etc.):",
        "engine_mlx": "MLX - Optimitzat per Apple Silicon (Metal GPU)",
        "engine_ollama": "Ollama - Universal (funciona a tot arreu)",
        "model_selected": "Model seleccionat",
        "download_instructions": "INSTRUCCIONS DE DESCÀRREGA",
        "model_not_found": "El model no s'ha trobat localment.",
        "to_download_mlx": "Per descarregar el model MLX, executa:",
        "to_download_ollama": "Per descarregar el model amb Ollama, executa:",
        "install_ollama_first": "Si no tens Ollama instal·lat:",
        "installing_ollama": "Instal·lant Ollama...",
        "ollama_install_confirm": "Vols instal·lar Ollama ara?",
        "ollama_install_skipped": "Ollama no instal·lat. El pots instal·lar més tard.",
        "ollama_install_manual": "Instal·la'l manualment des de: https://ollama.com/download",
        "ollama_installed": "Ollama instal·lat correctament!",
        "ollama_install_failed": "Error instal·lant Ollama. Instal·la'l manualment:",
        "after_download": "Després de descarregar, ja pots usar:",
        "skip_download": "Vols continuar sense descarregar ara?",
        "downloading_model": "Descarregant model...",
        "download_success": "Model descarregat correctament!",
        "model_already_cached": "Model ja estava al cache (no cal descarregar)",
        "download_failed": "Error descarregant el model. Pots fer-ho manualment més tard.",
        "download_now": "Vols descarregar el model ara?",
        "manual_install_note": "Guarda aquestes instruccions per descarregar el model manualment.",
        "storage_cleanup_confirm": "Carpeta storage existent detectada. Vols esborrar-la?",
        "cleaning_storage": "Carpeta storage existent detectada. Esborrant per instal·lació neta...",
        "storage_removed": "storage/ eliminada correctament.",
        "storage_kept": "S'ha conservat storage/.",
        "qdrant_quarantine_info": """
  {bold}ℹ️  Què és Qdrant?{reset}
  Qdrant és una base de dades vectorial de codi obert (https://qdrant.tech).
  Permet que la teva IA tingui memòria persistent i pugui recordar converses.

  {bold}⚠️  Per què macOS el bloqueja?{reset}
  macOS bloqueja programes descarregats que no estan "notaritzats" per Apple.
  Això NO vol dir que sigui perillós - Qdrant és un projecte modern i segur
  utilitzat per milers de desenvolupadors arreu del món.

  Si acceptes, s'eliminarà la marca de quarantena i Qdrant podrà executar-se.
""",
        "qdrant_quarantine_prompt": "Vols eliminar la quarantena de Qdrant?",
        "qdrant_quarantine_cleared": "Quarantena de Qdrant eliminada.",
        "qdrant_quarantine_skipped": "Has omès eliminar la quarantena. Qdrant pot ser bloquejat per Gatekeeper.",
        "qdrant_quarantine_failed": "No s'ha pogut eliminar la quarantena. Executa manualment:",
        "embeddings_info": """
  {bold}ℹ️  Què són els embeddings?{reset}
  Els embeddings són representacions matemàtiques del text que permeten
  a la IA entendre el significat de les paraules i trobar informació similar.

  {bold}📦 Model: all-MiniLM-L6-v2{reset}
  És un model petit (~90MB) de codi obert creat per Microsoft Research.
  S'utilitza per donar memòria a la teva IA (sistema RAG).

  {bold}🔒 Origen:{reset} HuggingFace (repositori oficial de models d'IA)
""",
        "embeddings_download_prompt": "Vols descarregar el model d'embeddings ara?",
        "embeddings_skipped": "Embeddings omesos. Es descarregaran automàticament al primer ús.",
        "press_enter": "Prem Enter per continuar...",
        "download_skipped": "D'acord! Pots descarregar el model més tard amb les instruccions anteriors.",
        "download_options": "Què vols fer?",
        "label_model": "Model",
        "label_ollama_id": "ID d'Ollama",
        "label_engine": "Motor",
        "label_command": "Executa",
        "label_hf_id": "ID de HuggingFace",
        "step_checking_ollama": "Verificant Ollama...",
        "step_starting_ollama": "Arrencant Ollama...",
        "step_downloading_model": "Descarregant model (pot trigar uns minuts)...",
        "step_verify_download": "Verificant descàrrega...",
        "model_downloaded": "Model {model_id} descarregat correctament!",
        "model_not_in_list": "Model no trobat a 'ollama list'. Verifica manualment.",
        "step_download_embeddings": "Descarregant model d'embeddings (per memòria)...",
        "embeddings_downloaded": "Model d'embeddings (nomic-embed-text) descarregat!",
        "embeddings_download_failed": "No s'ha pogut descarregar nomic-embed-text. La memòria pot fallar.",
        "download_complete": "Descàrrega completada!",
        "download_retrying": "Descàrrega interrompuda, reintentant en 5 segons... (intent {attempt}/{max_retries})",
        "engine_label_gguf": "llama.cpp (GGUF)",
        "engine_label_mlx": "MLX (Apple Silicon)",
        "downloading_file": "Descarregant {filename}...",
        "download_destination": "Destí: {path}",
        "model_already_downloaded": "Model ja descarregat a {path}",
        "downloading_mlx": "Descarregant model MLX...",
        "model_downloaded_to": "Model MLX descarregat a {path}",
        "model_validating_mlx": "Validant model MLX...",
        "model_missing_config": "Advertència: {path} no conté config.json",
        "model_possible_issues": "El model pot tenir problemes, però continuem.",
        "model_validated": "Model MLX validat correctament",
        "download_partial_kept": "Els fitxers parcials ja descarregats es mantindran per reprendre.",
        "download_error_detail": "Error: {error}",
        "mlx_required_warning": "⚠️  IMPORTANT: Sense el model descarregat, MLX no funcionarà!",
        "mlx_fallback_ollama": "El xat farà fallback a Ollama (si el tens instal·lat).",
        "venv_clean_detected": "Venv existent detectat. Esborrant per instal·lació neta...",
        "venv_cleaned": "Venv eliminat correctament.",
        "metal_unavailable_title": "✗ Metal no està disponible",
        "metal_required": "MLX necessita Metal (GPU d'Apple Silicon) per funcionar.",
        "metal_unavailable_detail": "Tot i que tens Apple Silicon, Metal no es pot inicialitzar.",
        "metal_options": "⚠️  Opcions:",
        "metal_option_ollama": "Canviar a Ollama (recomanat)",
        "metal_option_abort": "Abortar instal·lació",
        "metal_choice_prompt": "Escull [1/2]:",
        "metal_switched_ollama": "Canviat a Ollama: {model_id}",
        "metal_no_ollama_alternative": "No s'ha trobat alternativa Ollama per aquest model",
        "install_cancelled": "Instal·lació cancel·lada",
        "symlink_not_created": "Symlink no creat ({error}), usa './nexe' des de {path}",
        "knowledge_folder_created_ok": "Carpeta 'knowledge/' creada",
        "embeddings_download_step": "Descarregant model d'embeddings (all-MiniLM-L6-v2)...",
        "embeddings_download_time": "Això pot trigar uns minuts segons la connexió...",
        "embeddings_download_start": "📥 Iniciant descàrrega...",
        "embeddings_download_complete": "✓ Descàrrega completada!",
        "embeddings_download_success": "✅ Model d'embeddings descarregat correctament",
        "embeddings_download_error": "⚠️  Error descarregant embeddings",
        "embeddings_download_auto": "Es descarregarà automàticament al primer ús",
        "knowledge_processing_step": "Processant documents de coneixement ({count} fitxers)...",
        "knowledge_processing_time": "Això pot trigar uns minuts (generant embeddings)...",
        "knowledge_processing_success": "✅ Documents processats i indexats correctament",
        "knowledge_processing_timeout": "⚠️  Ingesta massa lenta (>5min). Es farà al primer inici.",
        "knowledge_processing_error": "⚠️  Error processant documents: {error}",
        "knowledge_processing_auto": "Es processaran automàticament al primer inici del servidor",
        "knowledge_no_documents": "📝 No hi ha documents a knowledge/ (es poden afegir més tard)",
        "optional_global_command": "OPCIONAL: Comanda global",
        "optional_global_instructions": "Per executar 'nexe' des de qualsevol lloc (sense ./), executa:",
        "commands_available": "📄 Comandes disponibles a: COMMANDS.md",
        "commands_write_failed": "No s'ha pogut escriure COMMANDS.md: {error}",
        "auto_download_not_supported": "Plataforma {system}/{machine} no suportada per descàrrega automàtica",
        "release_asset_not_found": "Asset {asset_name} no trobat a la release",
        "checksum_fetching": "Descarregant checksum...",
        "checksum_not_found": "Checksum no disponible per aquest asset. Continuant sense verificació.",
        "checksum_parse_failed": "Checksum invàlid. Continuant sense verificació.",
        "checksum_download_failed": "No s'ha pogut descarregar el checksum. Continuant sense verificació.",
        "checksum_verifying": "Verificant checksum...",
        "checksum_mismatch": "Checksum incorrecte. S'ha cancel·lat la descàrrega.",
        "checksum_verified": "Checksum correcte.",
        "ollama_auto_install_not_supported": "Auto-instal·lació d'Ollama no suportada a {system}",
        "ollama_install_timeout": "La instal·lació d'Ollama ha superat el temps (>3 min)",
        "ollama_script_fetching": "Descarregant l'script d'instal·lació d'Ollama...",
        "run_manual_command": "Executa manualment: {cmd}",
        "ollama_not_found": "Ollama no trobat. Instal·la'l primer.",
        "curl_not_found": "curl no trobat. Descarregant amb el client integrat.",
        "option_download_now": "Descarregar ara",
        "option_manual_later": "Ho faré manualment (mostra instruccions)",
        "download_confirmation_title": "Ara descarregarem tot el necessari",
        "download_confirmation_text": "Les descàrregues són oficials de codi obert, lliures de virus.\n  Provenen de:\n    • HuggingFace (models d'IA)\n    • GitHub (Qdrant vectorial)\n    • PyPI (dependències Python)",
        "download_continue": "Prem Enter per continuar amb la instal·lació...",
        "download_warning_title": "⚠️  IMPORTANT: Descàrrega de model ({size})",
        "download_warning_power": "Endolla l'ordinador al corrent",
        "download_warning_sleep": "Evita que l'ordinador s'adormi (canvia Configuració > Bateria)",
        "download_warning_wifi": "Mantén una connexió WiFi/Ethernet estable",
        "download_warning_time": "La descàrrega pot trigar 10-30 minuts segons la velocitat",
        "download_warning_resume": "Si falla, tornar a executar reprendrà la descàrrega",
        "download_ready": "Estic llest, començar descàrrega",
        "download_failed_resume": "⚠️  Descàrrega interrompuda. Torna a executar l'instal·lador per reprendre.",
        "laptop_warning": "Si tens un portàtil:",
        "knowledge_folder_created": "Preparant carpeta de coneixement (RAG)...",
        "knowledge_explanation": "Aquí pots posar els teus documents (.txt, .md, .pdf) i la IA els llegirà.\nPer defecte, conté la documentació del propi sistema.\nTambé pots canviar el prompt de la IA editant 'personality/server.toml'",
    },
    "es": {
        "lang_name": "Español",
        "analyzing_hardware": "Analizando tu hardware · Revisa que los datos sean correctos",
        "platform": "Plataforma",
        "ram_available": "RAM Disponible",
        "disk_space": "Disco Disponible",
        "disk_free_of_total": "libres / {total} GB total",
        "metal_support": "Soporte Metal (GPU)",
        "yes": "Sí",
        "no": "No",
        "proceed_install": "¿Quieres proceder con la instalación?",
        "yes_no": "(S/n)",
        "yes_no_default_no": "(S/N)",
        "setting_up_env": "Configurando entorno virtual y dependencias...",
        "creating_venv": "Creando entorno virtual...",
        "installing_deps": "Instalando dependencias desde requirements.txt...",
        "requirements_not_found": "¡Archivo requirements.txt no encontrado!",
        "installing_inference": "Instalando motores de inferencia optimizados...",
        "detected_apple": "Detectado Apple Silicon. Instalando",
        "mlx_version_fallback": "mlx-lm>=0.30.0 no disponible, instalando una versión compatible.",
        "installing_universal": "Instalando motor universal...",
        "installed_gpu": "instalado con soporte hardware.",
        "gpu_failed": "No se pudo compilar con GPU. Instalando versión CPU...",
        "generating_security": "Generando credenciales de seguridad (.env)...",
        "security_explanation": "Claves de acceso para proteger tu IA. Se guardan en el archivo .env",
        "env_created": ".env creado con Clave API segura.",
        "api_key": "Clave API Maestra",
        "saved_at": "Guardada en",
        "env_exists": ".env ya existe. No se ha sobrescrito.",
        "preparing_data": "Preparando estructuras de datos...",
        "module_cache_cleaned": "Caché de módulos limpiada.",
        "cache_explanation": "Limpia configuraciones antiguas para evitar conflictos",
        "executable_created": "Ejecutable 'nexe' creado en la raíz.",
        "executable_explanation": "Crea el comando './nexe' para interactuar con la IA",
        "symlink_created": "Symlink creado en /usr/local/bin/nexe",
        "symlink_global": "Puedes usar 'nexe' desde cualquier lugar del terminal",
        "symlink_failed": "No se puede crear symlink global (permisos)",
        "symlink_manual": "Para usar 'nexe' desde cualquier lugar, añade esto a tu ~/.zshrc o ~/.bashrc:",
        "downloading_qdrant": "Descargando Qdrant (base de datos vectorial)...",
        "qdrant_explanation": "Almacena el conocimiento de tu IA (memoria RAG)",
        "qdrant_download_info": """
  {bold}ℹ️  ¿Qué es Qdrant?{reset}
  Qdrant es una base de datos vectorial de código abierto (https://qdrant.tech).
  Permite que tu IA tenga memoria persistente y pueda recordar conversaciones
  y buscar información semánticamente (no solo por palabras clave).

  {bold}📦 Tamaño:{reset} ~50MB (binario precompilado)
  {bold}🔒 Origen:{reset} GitHub oficial de Qdrant (https://github.com/qdrant/qdrant)

  Sin Qdrant, la IA no tendrá memoria RAG (pero funcionará igualmente).
""",
        "qdrant_download_prompt": "¿Quieres descargar Qdrant ahora?",
        "qdrant_skipped": "Qdrant omitido. La memoria RAG no estará disponible.",
        "qdrant_exists": "Qdrant ya existe.",
        "qdrant_downloaded": "Qdrant descargado correctamente!",
        "qdrant_download_failed": "Error descargando Qdrant",
        "install_complete": "NEXE SERVER INSTALADO CORRECTAMENTE!",
        "basic_commands": "COMANDOS BÁSICOS:",
        "activate_env": "Activar entorno",
        "start_server": "Iniciar Server",
        "local_chat": "Chat Local",
        "view_logs": "Ver Logs",
        "system_status": "Estado Sistema",
        "ingest_data": "Ingesta datos",
        "general_help": "Ayuda General",
        "tip": "Consejo",
        "tip_text": "La memoria semantica (RAG) se activa por defecto. Usa './nexe chat --no-rag' para desactivarla.",
        "tested_warning": "Probado en Apple Silicon (M1/M2/M4) desde 8GB RAM. No probado en Linux.",
        "how_to_start": "CÓMO ARRANCAR SERVER.NEXE:",
        "step_activate_venv": "Activa tu entorno virtual (aísla las dependencias del sistema)",
        "step_start_server": "Inicia el servidor (arranca la IA en segundo plano)",
        "step_new_terminal": "Abre un nuevo terminal",
        "step_chat": "Escribe para chatear con tu IA local",
        "save_memory_tip": "Para guardar cosas en la memoria usa /save, /guardar o /recorda",
        "venv_automatic": "No hace falta activar el venv, './nexe' ya lo hace automáticamente",
        "step": "Paso",
        "disclaimer_title": "PROYECTO PERSONAL · CONTRIBUCIONES BIENVENIDAS",
        "disclaimer_bugs": "Puede contener bugs, si encuentras alguno por favor avísanos.",
        "disclaimer_tested": "Solo probado en Apple Silicon. Contribuye libremente:",
        "disclaimer_contribute": "rómpelo, llévalo al límite, monta módulos nuevos.",
        "disclaimer_thanks": "Gracias a la comunidad OSS por las herramientas que han hecho posible Nexe.",
        "disclaimer_docs": "Lee la documentación en knowledge/ para entender el sistema.",
        # Model selection
        "select_model": "Selecciona el Modelo de IA",
        "recommended": "RECOMENDADO",
        "model_size": "Tamaño",
        "model_ram": "RAM mín.",
        "model_speed": "Velocidad",
        "model_selection_title": "🤖 SELECCIÓN DE MODELO DE IA",
        "model_selection_ram_label": "Tu RAM:",
        "model_selection_ram_available_label": "RAM disponible para IA:",
        "model_selection_ram_percent": "(50-60% del total)",
        "model_selection_ram_note": "El resto se reserva para macOS, navegador y otras apps.",
        "model_size_title": "📦 TAMAÑO DE MODELOS",
        "model_size_option_small": "Modelos pequeños (8GB RAM) - Rápidos, menor calidad",
        "model_size_option_medium": "Modelos medianos (16GB RAM) - Equilibrados",
        "model_size_option_large": "Modelos grandes (32GB+ RAM) - Máxima calidad",
        "model_size_label_small": "pequeños",
        "model_size_label_medium": "medianos",
        "model_size_label_large": "grandes",
        "model_size_recommended": "Recomendado para tu RAM: modelos {rec_label}",
        "model_size_prompt": "Elige tamaño [1-3] (Enter = {recommended}):",
        "model_category_small": "MODELOS PEQUEÑOS (para 8GB RAM)",
        "model_category_medium": "MODELOS MEDIANOS (para 16GB RAM)",
        "model_category_large": "MODELOS GRANDES (para 32GB+ RAM)",
        "model_engines_label": "Motores",
        "model_disk_label": "Disco",
        "model_ram_label": "RAM",
        "model_choice_prompt": "Elige modelo [1-{count}] (Enter = {default}):",
        "model_status_compatible": "✓ Compatible",
        "model_status_maybe_tight": "⚠️ Puede ir justo",
        "model_tag_local_language": "CATALÁN",
        "engine_desc_mlx": "Optimizado para Apple Silicon (GPU Metal)",
        "engine_desc_ollama": "Universal, fácil de usar",
        "engine_desc_gguf": "Ejecución local directa, sin dependencias",
        "engine_choice_prompt": "Elige [1-{count}] (Enter = {default}):",
        "engine_single_notice": "{model} se ejecutará con {engine}",
        "download_gguf": "Para descargar el modelo GGUF:",
        "none": "Ninguno",
        "model_type_mlx": "MLX (Metal GPU - Más rápido)",
        "model_type_gguf": "GGUF/Ollama (CPU/GPU Universal)",
        "select_size": "¿Qué tamaño de modelo quieres?",
        "size_small": "Pequeño (1B) - Rápido, menos preciso",
        "size_medium": "Mediano (3B) - Equilibrado",
        "size_large": "Grande (8B) - Más preciso",
        "size_xl": "Extra Grande (70B) - Máxima calidad",
        "select_engine": "¿Qué motor de inferencia prefieres?",
        "engine_explanation": "El motor es el programa que ejecuta el modelo de IA en tu Mac.\nCada uno tiene ventajas diferentes (velocidad, compatibilidad, etc.):",
        "engine_mlx": "MLX - Optimizado para Apple Silicon (Metal GPU)",
        "engine_ollama": "Ollama - Universal (funciona en todas partes)",
        "model_selected": "Modelo seleccionado",
        "download_instructions": "INSTRUCCIONES DE DESCARGA",
        "model_not_found": "El modelo no se ha encontrado localmente.",
        "to_download_mlx": "Para descargar el modelo MLX, ejecuta:",
        "to_download_ollama": "Para descargar el modelo con Ollama, ejecuta:",
        "install_ollama_first": "Si no tienes Ollama instalado:",
        "installing_ollama": "Instalando Ollama...",
        "ollama_install_confirm": "¿Quieres instalar Ollama ahora?",
        "ollama_install_skipped": "Ollama no instalado. Puedes instalarlo más tarde.",
        "ollama_install_manual": "Instálalo manualmente desde: https://ollama.com/download",
        "ollama_installed": "Ollama instalado correctamente!",
        "ollama_install_failed": "Error instalando Ollama. Instálalo manualmente:",
        "after_download": "Después de descargar, ya puedes usar:",
        "skip_download": "¿Quieres continuar sin descargar ahora?",
        "downloading_model": "Descargando modelo...",
        "download_success": "Modelo descargado correctamente!",
        "model_already_cached": "Modelo ya estaba en cache (no es necesario descargar)",
        "download_failed": "Error descargando el modelo. Puedes hacerlo manualmente más tarde.",
        "download_now": "¿Quieres descargar el modelo ahora?",
        "manual_install_note": "Guarda estas instrucciones para descargar el modelo manualmente.",
        "storage_cleanup_confirm": "Carpeta storage existente detectada. ¿Quieres borrarla?",
        "cleaning_storage": "Carpeta storage existente detectada. Borrando para instalación limpia...",
        "storage_removed": "storage/ eliminada correctamente.",
        "storage_kept": "Se ha conservado storage/.",
        "qdrant_quarantine_info": """
  {bold}ℹ️  ¿Qué es Qdrant?{reset}
  Qdrant es una base de datos vectorial de código abierto (https://qdrant.tech).
  Permite que tu IA tenga memoria persistente y pueda recordar conversaciones.

  {bold}⚠️  ¿Por qué macOS lo bloquea?{reset}
  macOS bloquea programas descargados que no están "notarizados" por Apple.
  Esto NO significa que sea peligroso - Qdrant es un proyecto moderno y seguro
  utilizado por miles de desarrolladores en todo el mundo.

  Si aceptas, se eliminará la marca de cuarentena y Qdrant podrá ejecutarse.
""",
        "qdrant_quarantine_prompt": "¿Quieres eliminar la cuarentena de Qdrant?",
        "qdrant_quarantine_cleared": "Cuarentena de Qdrant eliminada.",
        "qdrant_quarantine_skipped": "Has omitido eliminar la cuarentena. Qdrant puede ser bloqueado por Gatekeeper.",
        "qdrant_quarantine_failed": "No se pudo eliminar la cuarentena. Ejecuta manualmente:",
        "embeddings_info": """
  {bold}ℹ️  ¿Qué son los embeddings?{reset}
  Los embeddings son representaciones matemáticas del texto que permiten
  a la IA entender el significado de las palabras y encontrar información similar.

  {bold}📦 Modelo: all-MiniLM-L6-v2{reset}
  Es un modelo pequeño (~90MB) de código abierto creado por Microsoft Research.
  Se utiliza para dar memoria a tu IA (sistema RAG).

  {bold}🔒 Origen:{reset} HuggingFace (repositorio oficial de modelos de IA)
""",
        "embeddings_download_prompt": "¿Quieres descargar el modelo de embeddings ahora?",
        "embeddings_skipped": "Embeddings omitidos. Se descargarán automáticamente en el primer uso.",
        "press_enter": "Pulsa Enter para continuar...",
        "download_skipped": "¡De acuerdo! Puedes descargar el modelo más tarde con las instrucciones anteriores.",
        "download_options": "¿Qué quieres hacer?",
        "label_model": "Modelo",
        "label_ollama_id": "ID de Ollama",
        "label_engine": "Motor",
        "label_command": "Ejecuta",
        "label_hf_id": "ID de HuggingFace",
        "step_checking_ollama": "Verificando Ollama...",
        "step_starting_ollama": "Iniciando Ollama...",
        "step_downloading_model": "Descargando modelo (puede tardar unos minutos)...",
        "step_verify_download": "Verificando descarga...",
        "model_downloaded": "Modelo {model_id} descargado correctamente!",
        "model_not_in_list": "Modelo no encontrado en 'ollama list'. Verifica manualmente.",
        "step_download_embeddings": "Descargando modelo de embeddings (para memoria)...",
        "embeddings_downloaded": "Modelo de embeddings (nomic-embed-text) descargado!",
        "embeddings_download_failed": "No se pudo descargar nomic-embed-text. La memoria puede fallar.",
        "download_complete": "Descarga completada!",
        "download_retrying": "Descarga interrumpida, reintentando en 5 segundos... (intento {attempt}/{max_retries})",
        "engine_label_gguf": "llama.cpp (GGUF)",
        "engine_label_mlx": "MLX (Apple Silicon)",
        "downloading_file": "Descargando {filename}...",
        "download_destination": "Destino: {path}",
        "model_already_downloaded": "Modelo ya descargado en {path}",
        "downloading_mlx": "Descargando modelo MLX...",
        "model_downloaded_to": "Modelo MLX descargado en {path}",
        "model_validating_mlx": "Validando modelo MLX...",
        "model_missing_config": "Advertencia: {path} no contiene config.json",
        "model_possible_issues": "El modelo puede tener problemas, pero continuamos.",
        "model_validated": "Modelo MLX validado correctamente",
        "download_partial_kept": "Los archivos parciales ya descargados se mantendrán para reanudar.",
        "download_error_detail": "Error: {error}",
        "mlx_required_warning": "⚠️  IMPORTANTE: Sin el modelo descargado, MLX no funcionará!",
        "mlx_fallback_ollama": "El chat hará fallback a Ollama (si lo tienes instalado).",
        "venv_clean_detected": "Venv existente detectado. Borrando para instalación limpia...",
        "venv_cleaned": "Venv eliminado correctamente.",
        "metal_unavailable_title": "✗ Metal no está disponible",
        "metal_required": "MLX necesita Metal (GPU de Apple Silicon) para funcionar.",
        "metal_unavailable_detail": "Aunque tienes Apple Silicon, Metal no se puede inicializar.",
        "metal_options": "⚠️  Opciones:",
        "metal_option_ollama": "Cambiar a Ollama (recomendado)",
        "metal_option_abort": "Abortar instalación",
        "metal_choice_prompt": "Elige [1/2]:",
        "metal_switched_ollama": "Cambiado a Ollama: {model_id}",
        "metal_no_ollama_alternative": "No se encontró alternativa Ollama para este modelo",
        "install_cancelled": "Instalación cancelada",
        "symlink_not_created": "Symlink no creado ({error}), usa './nexe' desde {path}",
        "knowledge_folder_created_ok": "Carpeta 'knowledge/' creada",
        "embeddings_download_step": "Descargando modelo de embeddings (all-MiniLM-L6-v2)...",
        "embeddings_download_time": "Esto puede tardar unos minutos según la conexión...",
        "embeddings_download_start": "📥 Iniciando descarga...",
        "embeddings_download_complete": "✓ Descarga completada!",
        "embeddings_download_success": "✅ Modelo de embeddings descargado correctamente",
        "embeddings_download_error": "⚠️  Error descargando embeddings",
        "embeddings_download_auto": "Se descargará automáticamente en el primer uso",
        "knowledge_processing_step": "Procesando documentos de conocimiento ({count} archivos)...",
        "knowledge_processing_time": "Esto puede tardar unos minutos (generando embeddings)...",
        "knowledge_processing_success": "✅ Documentos procesados e indexados correctamente",
        "knowledge_processing_timeout": "⚠️  Ingesta demasiado lenta (>5min). Se hará en el primer inicio.",
        "knowledge_processing_error": "⚠️  Error procesando documentos: {error}",
        "knowledge_processing_auto": "Se procesarán automáticamente en el primer inicio del servidor",
        "knowledge_no_documents": "📝 No hay documentos en knowledge/ (se pueden añadir más tarde)",
        "optional_global_command": "OPCIONAL: Comando global",
        "optional_global_instructions": "Para ejecutar 'nexe' desde cualquier lugar (sin ./), ejecuta:",
        "commands_available": "📄 Comandos disponibles en: COMMANDS.md",
        "commands_write_failed": "No se pudo escribir COMMANDS.md: {error}",
        "auto_download_not_supported": "Plataforma {system}/{machine} no compatible con descarga automática",
        "release_asset_not_found": "Asset {asset_name} no encontrado en la release",
        "checksum_fetching": "Descargando checksum...",
        "checksum_not_found": "Checksum no disponible para este asset. Continuando sin verificación.",
        "checksum_parse_failed": "Checksum inválido. Continuando sin verificación.",
        "checksum_download_failed": "No se pudo descargar el checksum. Continuando sin verificación.",
        "checksum_verifying": "Verificando checksum...",
        "checksum_mismatch": "Checksum incorrecto. Descarga cancelada.",
        "checksum_verified": "Checksum correcto.",
        "ollama_auto_install_not_supported": "Auto-instalación de Ollama no soportada en {system}",
        "ollama_install_timeout": "La instalación de Ollama ha excedido el tiempo (>3 min)",
        "ollama_script_fetching": "Descargando el script de instalación de Ollama...",
        "run_manual_command": "Ejecuta manualmente: {cmd}",
        "ollama_not_found": "Ollama no encontrado. Instálalo primero.",
        "curl_not_found": "curl no encontrado. Descargando con el cliente integrado.",
        "option_download_now": "Descargar ahora",
        "option_manual_later": "Lo haré manualmente (mostrar instrucciones)",
        "download_confirmation_title": "Ahora descargaremos todo lo necesario",
        "download_confirmation_text": "Las descargas son oficiales de código abierto, libres de virus.\n  Provienen de:\n    • HuggingFace (modelos de IA)\n    • GitHub (Qdrant vectorial)\n    • PyPI (dependencias Python)",
        "download_continue": "Pulsa Enter para continuar con la instalación...",
        "download_warning_title": "⚠️  IMPORTANTE: Descarga de modelo ({size})",
        "download_warning_power": "Enchufa el ordenador a la corriente",
        "download_warning_sleep": "Evita que el ordenador se duerma (cambia Configuración > Batería)",
        "download_warning_wifi": "Mantén una conexión WiFi/Ethernet estable",
        "download_warning_time": "La descarga puede tardar 10-30 minutos según la velocidad",
        "download_warning_resume": "Si falla, volver a ejecutar reanudará la descarga",
        "download_ready": "Estoy listo, comenzar descarga",
        "download_failed_resume": "⚠️  Descarga interrumpida. Vuelve a ejecutar el instalador para reanudar.",
        "laptop_warning": "Si tienes un portátil:",
        "knowledge_folder_created": "Preparando carpeta de conocimiento (RAG)...",
        "knowledge_explanation": "Aquí puedes poner tus documentos (.txt, .md, .pdf) y la IA los leerá.\nPor defecto, contiene la documentación del propio sistema.\nTambién puedes cambiar el prompt de la IA editando 'personality/server.toml'",
    },
    "en": {
        "lang_name": "English",
        "analyzing_hardware": "Analyzing your hardware · Please verify the data is correct",
        "platform": "Platform",
        "ram_available": "Available RAM",
        "disk_space": "Available Disk",
        "disk_free_of_total": "free / {total} GB total",
        "metal_support": "Metal Support (GPU)",
        "yes": "Yes",
        "no": "No",
        "proceed_install": "Do you want to proceed with the installation?",
        "yes_no": "(Y/n)",
        "yes_no_default_no": "(Y/N)",
        "setting_up_env": "Setting up virtual environment and dependencies...",
        "creating_venv": "Creating virtual environment...",
        "installing_deps": "Installing dependencies from requirements.txt...",
        "requirements_not_found": "Requirements file not found!",
        "installing_inference": "Installing optimized inference engines...",
        "detected_apple": "Detected Apple Silicon. Installing",
        "mlx_version_fallback": "mlx-lm>=0.30.0 not available, installing a compatible version.",
        "installing_universal": "Installing universal engine...",
        "installed_gpu": "installed with hardware support.",
        "gpu_failed": "Could not compile with GPU. Installing CPU version...",
        "generating_security": "Generating security credentials (.env)...",
        "security_explanation": "Access keys to protect your AI. Stored in the .env file",
        "env_created": ".env created with secure API Key.",
        "api_key": "Master API Key",
        "saved_at": "Saved at",
        "env_exists": ".env already exists. Not overwritten.",
        "preparing_data": "Preparing data structures...",
        "module_cache_cleaned": "Module cache cleaned.",
        "cache_explanation": "Cleans old configurations to avoid conflicts",
        "executable_created": "Executable 'nexe' created at root.",
        "executable_explanation": "Creates the './nexe' command to interact with the AI",
        "symlink_created": "Symlink created at /usr/local/bin/nexe",
        "symlink_global": "You can use 'nexe' from anywhere in the terminal",
        "symlink_failed": "Cannot create global symlink (permissions)",
        "symlink_manual": "To use 'nexe' from anywhere, add this to your ~/.zshrc or ~/.bashrc:",
        "downloading_qdrant": "Downloading Qdrant (vector database)...",
        "qdrant_explanation": "Stores your AI's knowledge (RAG memory)",
        "qdrant_download_info": """
  {bold}ℹ️  What is Qdrant?{reset}
  Qdrant is an open-source vector database (https://qdrant.tech).
  It allows your AI to have persistent memory and remember conversations,
  searching information semantically (not just by keywords).

  {bold}📦 Size:{reset} ~50MB (precompiled binary)
  {bold}🔒 Source:{reset} Official Qdrant GitHub (https://github.com/qdrant/qdrant)

  Without Qdrant, the AI won't have RAG memory (but will still work).
""",
        "qdrant_download_prompt": "Download Qdrant now?",
        "qdrant_skipped": "Qdrant skipped. RAG memory won't be available.",
        "qdrant_exists": "Qdrant already exists.",
        "qdrant_downloaded": "Qdrant downloaded successfully!",
        "qdrant_download_failed": "Error downloading Qdrant",
        "install_complete": "NEXE SERVER INSTALLED SUCCESSFULLY!",
        "basic_commands": "BASIC COMMANDS:",
        "activate_env": "Activate environment",
        "start_server": "Start Server",
        "local_chat": "Local Chat",
        "view_logs": "View Logs",
        "system_status": "System Status",
        "ingest_data": "Ingest data",
        "general_help": "General Help",
        "tip": "Tip",
        "tip_text": "Semantic memory (RAG) is enabled by default. Use './nexe chat --no-rag' to disable it.",
        "tested_warning": "Tested on Apple Silicon (M1/M2/M4) from 8GB RAM. Not tested on Linux.",
        "how_to_start": "HOW TO START SERVER.NEXE:",
        "step_activate_venv": "Activate your virtual environment (isolates system dependencies)",
        "step_start_server": "Start the server (launches AI in background)",
        "step_new_terminal": "Open a new terminal",
        "step_chat": "Type to chat with your local AI",
        "save_memory_tip": "To save things to memory use /save, /guardar or /recorda",
        "venv_automatic": "No need to activate venv, './nexe' does it automatically",
        "step": "Step",
        "disclaimer_title": "PERSONAL PROJECT · CONTRIBUTIONS WELCOME",
        "disclaimer_bugs": "May contain bugs, if you find any please let us know.",
        "disclaimer_tested": "Only tested on Apple Silicon. Contribute freely:",
        "disclaimer_contribute": "break it, push it to the limit, build new modules.",
        "disclaimer_thanks": "Thanks to the OSS community for the tools that made Nexe possible.",
        "disclaimer_docs": "Read the documentation in knowledge/ to understand the system.",
        # Model selection
        "select_model": "Select AI Model",
        "recommended": "RECOMMENDED",
        "model_size": "Size",
        "model_ram": "Min. RAM",
        "model_speed": "Speed",
        "model_selection_title": "🤖 AI MODEL SELECTION",
        "model_selection_ram_label": "Your RAM:",
        "model_selection_ram_available_label": "RAM available for AI:",
        "model_selection_ram_percent": "(50-60% of total)",
        "model_selection_ram_note": "The rest is reserved for macOS, browser, and other apps.",
        "model_size_title": "📦 MODEL SIZE",
        "model_size_option_small": "Small models (8GB RAM) - Fast, lower quality",
        "model_size_option_medium": "Medium models (16GB RAM) - Balanced",
        "model_size_option_large": "Large models (32GB+ RAM) - Highest quality",
        "model_size_label_small": "small",
        "model_size_label_medium": "medium",
        "model_size_label_large": "large",
        "model_size_recommended": "Recommended for your RAM: {rec_label} models",
        "model_size_prompt": "Choose size [1-3] (Enter = {recommended}):",
        "model_category_small": "SMALL MODELS (for 8GB RAM)",
        "model_category_medium": "MEDIUM MODELS (for 16GB RAM)",
        "model_category_large": "LARGE MODELS (for 32GB+ RAM)",
        "model_engines_label": "Engines",
        "model_disk_label": "Disk",
        "model_ram_label": "RAM",
        "model_choice_prompt": "Choose model [1-{count}] (Enter = {default}):",
        "model_status_compatible": "✓ Compatible",
        "model_status_maybe_tight": "⚠️ Might be tight",
        "model_tag_local_language": "CATALAN",
        "engine_desc_mlx": "Optimized for Apple Silicon (Metal GPU)",
        "engine_desc_ollama": "Universal, easy to use",
        "engine_desc_gguf": "Direct local execution, no dependencies",
        "engine_choice_prompt": "Choose [1-{count}] (Enter = {default}):",
        "engine_single_notice": "{model} will run with {engine}",
        "download_gguf": "To download the GGUF model:",
        "none": "None",
        "model_type_mlx": "MLX (Metal GPU - Fastest)",
        "model_type_gguf": "GGUF/Ollama (Universal CPU/GPU)",
        "select_size": "What model size do you want?",
        "size_small": "Small (1B) - Fast, less accurate",
        "size_medium": "Medium (3B) - Balanced",
        "size_large": "Large (8B) - More accurate",
        "size_xl": "Extra Large (70B) - Maximum quality",
        "select_engine": "Which inference engine do you prefer?",
        "engine_explanation": "The engine is the program that runs the AI model on your Mac.\nEach has different advantages (speed, compatibility, etc.):",
        "engine_mlx": "MLX - Optimized for Apple Silicon (Metal GPU)",
        "engine_ollama": "Ollama - Universal (works everywhere)",
        "model_selected": "Selected model",
        "download_instructions": "DOWNLOAD INSTRUCTIONS",
        "model_not_found": "Model not found locally.",
        "to_download_mlx": "To download the MLX model, run:",
        "to_download_ollama": "To download the model with Ollama, run:",
        "install_ollama_first": "If you don't have Ollama installed:",
        "installing_ollama": "Installing Ollama...",
        "ollama_install_confirm": "Do you want to install Ollama now?",
        "ollama_install_skipped": "Ollama not installed. You can install it later.",
        "ollama_install_manual": "Install it manually from: https://ollama.com/download",
        "ollama_installed": "Ollama installed successfully!",
        "ollama_install_failed": "Error installing Ollama. Install it manually:",
        "after_download": "After downloading, you can use:",
        "skip_download": "Do you want to continue without downloading now?",
        "downloading_model": "Downloading model...",
        "download_success": "Model downloaded successfully!",
        "model_already_cached": "Model already cached (no download needed)",
        "download_failed": "Error downloading model. You can do it manually later.",
        "download_now": "Do you want to download the model now?",
        "manual_install_note": "Save these instructions to download the model manually.",
        "storage_cleanup_confirm": "Existing storage folder detected. Delete it?",
        "cleaning_storage": "Existing storage folder detected. Removing for a clean install...",
        "storage_removed": "storage/ removed successfully.",
        "storage_kept": "Kept existing storage/.",
        "qdrant_quarantine_info": """
  {bold}ℹ️  What is Qdrant?{reset}
  Qdrant is an open-source vector database (https://qdrant.tech).
  It allows your AI to have persistent memory and remember conversations.

  {bold}⚠️  Why does macOS block it?{reset}
  macOS blocks downloaded programs that aren't "notarized" by Apple.
  This does NOT mean it's dangerous - Qdrant is a modern, secure project
  used by thousands of developers worldwide.

  If you accept, the quarantine flag will be removed and Qdrant will run.
""",
        "qdrant_quarantine_prompt": "Remove Qdrant quarantine?",
        "qdrant_quarantine_cleared": "Qdrant quarantine removed.",
        "qdrant_quarantine_skipped": "Skipped quarantine removal. Qdrant may be blocked by Gatekeeper.",
        "qdrant_quarantine_failed": "Failed to remove quarantine. Run manually:",
        "embeddings_info": """
  {bold}ℹ️  What are embeddings?{reset}
  Embeddings are mathematical representations of text that allow
  the AI to understand word meanings and find similar information.

  {bold}📦 Model: all-MiniLM-L6-v2{reset}
  A small (~90MB) open-source model created by Microsoft Research.
  Used to give your AI memory (RAG system).

  {bold}🔒 Source:{reset} HuggingFace (official AI model repository)
""",
        "embeddings_download_prompt": "Download the embeddings model now?",
        "embeddings_skipped": "Embeddings skipped. Will download automatically on first use.",
        "press_enter": "Press Enter to continue...",
        "download_skipped": "Alright! You can download the model later using the instructions above.",
        "download_options": "What do you want to do?",
        "label_model": "Model",
        "label_ollama_id": "Ollama ID",
        "label_engine": "Engine",
        "label_command": "Run",
        "label_hf_id": "HuggingFace ID",
        "step_checking_ollama": "Checking Ollama...",
        "step_starting_ollama": "Starting Ollama...",
        "step_downloading_model": "Downloading model (this may take a few minutes)...",
        "step_verify_download": "Verifying download...",
        "model_downloaded": "Model {model_id} downloaded successfully!",
        "model_not_in_list": "Model not found in 'ollama list'. Please verify manually.",
        "step_download_embeddings": "Downloading embeddings model (for memory)...",
        "embeddings_downloaded": "Embeddings model (nomic-embed-text) downloaded!",
        "embeddings_download_failed": "Could not download nomic-embed-text. Memory may fail.",
        "download_complete": "Download complete!",
        "download_retrying": "Download interrupted, retrying in 5 seconds... (attempt {attempt}/{max_retries})",
        "engine_label_gguf": "llama.cpp (GGUF)",
        "engine_label_mlx": "MLX (Apple Silicon)",
        "downloading_file": "Downloading {filename}...",
        "download_destination": "Destination: {path}",
        "model_already_downloaded": "Model already downloaded at {path}",
        "downloading_mlx": "Downloading MLX model...",
        "model_downloaded_to": "MLX model downloaded to {path}",
        "model_validating_mlx": "Validating MLX model...",
        "model_missing_config": "Warning: {path} does not contain config.json",
        "model_possible_issues": "The model may have issues, but we will continue.",
        "model_validated": "MLX model validated successfully",
        "download_partial_kept": "Partial files already downloaded will be kept to resume.",
        "download_error_detail": "Error: {error}",
        "mlx_required_warning": "⚠️  IMPORTANT: Without the model downloaded, MLX will not work!",
        "mlx_fallback_ollama": "Chat will fall back to Ollama (if installed).",
        "venv_clean_detected": "Existing venv detected. Removing for a clean install...",
        "venv_cleaned": "Venv removed successfully.",
        "metal_unavailable_title": "✗ Metal is not available",
        "metal_required": "MLX needs Metal (Apple Silicon GPU) to work.",
        "metal_unavailable_detail": "Even though you have Apple Silicon, Metal cannot be initialized.",
        "metal_options": "⚠️  Options:",
        "metal_option_ollama": "Switch to Ollama (recommended)",
        "metal_option_abort": "Abort installation",
        "metal_choice_prompt": "Choose [1/2]:",
        "metal_switched_ollama": "Switched to Ollama: {model_id}",
        "metal_no_ollama_alternative": "No Ollama alternative found for this model",
        "install_cancelled": "Installation cancelled",
        "symlink_not_created": "Symlink not created ({error}); use './nexe' from {path}",
        "knowledge_folder_created_ok": "Folder 'knowledge/' created",
        "embeddings_download_step": "Downloading embeddings model (all-MiniLM-L6-v2)...",
        "embeddings_download_time": "This may take a few minutes depending on your connection...",
        "embeddings_download_start": "📥 Starting download...",
        "embeddings_download_complete": "✓ Download completed!",
        "embeddings_download_success": "✅ Embeddings model downloaded successfully",
        "embeddings_download_error": "⚠️  Error downloading embeddings",
        "embeddings_download_auto": "It will download automatically on first use",
        "knowledge_processing_step": "Processing knowledge documents ({count} files)...",
        "knowledge_processing_time": "This may take a few minutes (generating embeddings)...",
        "knowledge_processing_success": "✅ Documents processed and indexed successfully",
        "knowledge_processing_timeout": "⚠️  Ingestion too slow (>5min). It will run on first start.",
        "knowledge_processing_error": "⚠️  Error processing documents: {error}",
        "knowledge_processing_auto": "They will be processed automatically on first server start",
        "knowledge_no_documents": "📝 No documents in knowledge/ (you can add them later)",
        "optional_global_command": "OPTIONAL: Global command",
        "optional_global_instructions": "To run 'nexe' from anywhere (without ./), run:",
        "commands_available": "📄 Commands available at: COMMANDS.md",
        "commands_write_failed": "Could not write COMMANDS.md: {error}",
        "auto_download_not_supported": "Platform {system}/{machine} not supported for auto-download",
        "release_asset_not_found": "Asset {asset_name} not found in release",
        "checksum_fetching": "Fetching checksum...",
        "checksum_not_found": "Checksum not available for this asset. Continuing without verification.",
        "checksum_parse_failed": "Checksum file invalid. Continuing without verification.",
        "checksum_download_failed": "Failed to download checksum. Continuing without verification.",
        "checksum_verifying": "Verifying checksum...",
        "checksum_mismatch": "Checksum mismatch. Download aborted.",
        "checksum_verified": "Checksum OK.",
        "ollama_auto_install_not_supported": "Ollama auto-install not supported on {system}",
        "ollama_install_timeout": "Ollama install timed out (>3 min)",
        "ollama_script_fetching": "Downloading Ollama install script...",
        "run_manual_command": "Run manually: {cmd}",
        "ollama_not_found": "Ollama not found. Install it first.",
        "curl_not_found": "curl not found. Using built-in downloader.",
        "option_download_now": "Download now",
        "option_manual_later": "I'll do it manually (show instructions)",
        "download_confirmation_title": "We will now download everything needed",
        "download_confirmation_text": "Downloads are official open-source, virus-free.\n  Sources:\n    • HuggingFace (AI models)\n    • GitHub (Qdrant vectorial)\n    • PyPI (Python dependencies)",
        "download_continue": "Press Enter to continue with installation...",
        "download_warning_title": "⚠️  IMPORTANT: Model download ({size})",
        "download_warning_power": "Plug your computer into power",
        "download_warning_sleep": "Prevent computer from sleeping (change Settings > Battery)",
        "download_warning_wifi": "Keep a stable WiFi/Ethernet connection",
        "download_warning_time": "Download may take 10-30 minutes depending on speed",
        "download_warning_resume": "If it fails, running again will resume the download",
        "download_ready": "I'm ready, start download",
        "download_failed_resume": "⚠️  Download interrupted. Run the installer again to resume.",
        "laptop_warning": "If you have a laptop:",
        "knowledge_folder_created": "Preparing knowledge folder (RAG)...",
        "knowledge_explanation": "Here you can put your documents (.txt, .md, .pdf) and the AI will read them.\nBy default, it contains the system's own documentation.\nYou can also change the AI prompt by editing 'personality/server.toml'",
    },
}

# Global state
LANG = "ca"
HW_INFO = {}

def t(key: str, **kwargs) -> str:
    """Get translation for key."""
    text = TRANSLATIONS.get(LANG, TRANSLATIONS["en"]).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text

def clear():
    """Clear terminal screen safely (no shell injection risk)."""
    cmd = ['cls'] if os.name == 'nt' else ['clear']
    subprocess.run(cmd, shell=False, check=False)

def print_step(msg):
    print(f"\n{BLUE}[STEP]{RESET} {msg}")

def print_success(msg):
    print(f"{GREEN}[OK]{RESET} {msg}")

def print_warn(msg):
    print(f"{YELLOW}[WARN]{RESET} {msg}")

def print_error(msg):
    print(f"{RED}[ERROR]{RESET} {msg}")

def _fetch_text(url: str) -> str:
    """Fetch text content from URL with a small timeout."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")

def _parse_checksum(text: str):
    """Return the first SHA256 checksum found in text."""
    match = re.search(r"\b[a-fA-F0-9]{64}\b", text)
    return match.group(0).lower() if match else None

def _sha256_file(path: Path) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def _download_file(url: str, dest_path: Path) -> None:
    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as response, open(dest_path, "wb") as out_file:
        shutil.copyfileobj(response, out_file)

# ═══════════════════════════════════════════════════════════════════════════
# LANGUAGE SELECTION
# ═══════════════════════════════════════════════════════════════════════════
def select_language():
    """Interactive language selection."""
    global LANG
    clear()
    print(APP_LOGO)

    # Descriptions by language
    descriptions = {
        "ca": "Nexe és un servidor d'IA local, sobirà i persistent.\nNo es connecta al núvol. Memòria de conversa i personalitat configurable.",
        "es": "Nexe es un servidor de IA local, soberano y persistente.\nNo se conecta a la nube. Memoria de conversación y personalidad configurable.",
        "en": "Nexe is a local, sovereign and persistent AI server.\nDoes not connect to the cloud. Conversation memory and configurable personality."
    }

    print(f"\n{BOLD}Selecciona idioma / Select language / Selecciona idioma:{RESET}\n")
    print(f"  {CYAN}1.{RESET} Català")
    print(f"  {CYAN}2.{RESET} Español")
    print(f"  {CYAN}3.{RESET} English")

    choice = input(f"\n{BOLD}[1/2/3]:{RESET} ").strip()

    if choice == "2":
        LANG = "es"
    elif choice == "3":
        LANG = "en"
    else:
        LANG = "ca"

    # Show description after selection
    clear()
    print(APP_LOGO)
    print(f"\n{DIM}{descriptions[LANG]}{RESET}\n")
    input(f"{DIM}{t('press_enter')}{RESET}")

    return LANG

# ═══════════════════════════════════════════════════════════════════════════
# HARDWARE DETECTION
# ═══════════════════════════════════════════════════════════════════════════
def get_sysctl(key):
    try:
        return subprocess.check_output(["sysctl", "-n", key]).decode().strip()
    except Exception:
        return None

def detect_hardware():
    global HW_INFO
    print_step(f"{BOLD}{t('analyzing_hardware')}{RESET}")
    sys_type = platform.system()
    ram_gb = 0
    hw_type = "Generic Computer"
    is_rpi = False
    is_apple_silicon = False
    has_metal = False
    disk_total_gb = 0
    disk_free_gb = 0

    if sys_type == "Darwin":
        mem_bytes = int(get_sysctl("hw.memsize") or 0)
        ram_gb = round(mem_bytes / (1024**3))
        cpu_brand = get_sysctl("machdep.cpu.brand_string") or "Apple Processor"
        if "Apple" in cpu_brand or os.uname().machine == "arm64":
            hw_type = f"Apple Silicon ({os.uname().machine})"
            is_apple_silicon = True
            has_metal = True  # All Apple Silicon has Metal
        else:
            hw_type = "Apple Intel"
    elif sys_type == "Linux":
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if "MemTotal" in line:
                        ram_kb = int(re.search(r'\d+', line).group())
                        ram_gb = round(ram_kb / (1024*1024))
                        break
            model_path = Path('/proc/device-tree/model')
            if model_path.exists():
                with open(model_path, 'r') as f:
                    hw_type = f.read().strip().replace('\x00', '')
                if "Raspberry Pi" in hw_type:
                    is_rpi = True
            else:
                hw_type = f"Linux ({platform.machine()})"
        except Exception:
            ram_gb = 4

    # Detect disk space
    try:
        import shutil
        total, used, free = shutil.disk_usage(Path.home())
        disk_total_gb = round(total / (1024**3))
        disk_free_gb = round(free / (1024**3))
    except Exception:
        disk_total_gb = 0
        disk_free_gb = 0

    print(f"  {CYAN}🖥️  {t('platform')}:{RESET} {hw_type}")
    print(f"  {CYAN}🧠 {t('ram_available')}:{RESET}  {ram_gb} GB")
    if disk_total_gb > 0:
        disk_text = t('disk_free_of_total').format(total=disk_total_gb)
        print(f"  {CYAN}💾 {t('disk_space')}:{RESET} {disk_free_gb} GB {DIM}{disk_text}{RESET}")
    if is_apple_silicon:
        print(f"  {CYAN}⚡ {t('metal_support')}:{RESET} {GREEN}{t('yes')}{RESET}")

    # Compatibility warning
    print(f"\n  {YELLOW}⚠️  {t('tested_warning')}{RESET}")

    HW_INFO = {
        "ram": ram_gb,
        "type": hw_type,
        "is_rpi": is_rpi,
        "is_apple_silicon": is_apple_silicon,
        "has_metal": has_metal,
        "machine": platform.machine(),
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb
    }
    return HW_INFO

# ═══════════════════════════════════════════════════════════════════════════
# MODEL SELECTION
# ═══════════════════════════════════════════════════════════════════════════
def get_recommended_size(ram_gb):
    """
    Get recommended model size based on RAM.

    IMPORTANT: Models should use max 50-60% of total RAM to leave
    space for OS, browser, and other apps.

    RAM Total → RAM for Model → Recommended
    8 GB      → 4-5 GB        → small (2.4 GB) ✅ or medium (4 GB) ⚠️
    16 GB     → 8-10 GB       → medium (4 GB) ✅ or large (4.5 GB) ✅
    32 GB     → 16-20 GB      → large (4.5 GB) ✅
    64 GB+    → 32+ GB        → xl (26 GB) ✅
    """
    usable_ram = ram_gb * 0.55  # 55% of RAM for model

    if usable_ram >= 28:
        return "xl"
    elif usable_ram >= 8:
        return "large"
    elif usable_ram >= 5:
        return "medium"
    else:
        return "small"

def select_model(hw):
    """Interactive model selection with multiple options per category."""
    clear()
    print(APP_LOGO)

    ram = hw["ram"]
    usable_ram = int(ram * 0.55)
    recommended_size = get_recommended_size(ram)
    has_metal = hw["has_metal"]

    # Didactic explanation
    print(f"\n{BOLD}{t('model_selection_title')}{RESET}\n")
    print(f"  {CYAN}{t('model_selection_ram_label')}{RESET} {ram} GB")
    print(
        f"  {CYAN}{t('model_selection_ram_available_label')}{RESET} ~{usable_ram} GB "
        f"{DIM}{t('model_selection_ram_percent')}{RESET}"
    )
    print(f"  {DIM}{t('model_selection_ram_note')}{RESET}")

    # Determine recommended category based on RAM
    if usable_ram < 5:
        recommended = "1"
        rec_label = t("model_size_label_small")
    elif usable_ram < 20:
        recommended = "2"
        rec_label = t("model_size_label_medium")
    else:
        recommended = "3"
        rec_label = t("model_size_label_large")

    # Let user choose category regardless of RAM
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"\n{BOLD}{t('model_size_title')}{RESET}\n")
    print(f"  {CYAN}1.{RESET} {t('model_size_option_small')}")
    print(f"  {CYAN}2.{RESET} {t('model_size_option_medium')}")
    print(f"  {CYAN}3.{RESET} {t('model_size_option_large')}")
    print()
    print(f"  {DIM}{t('model_size_recommended', rec_label=rec_label)}{RESET}")
    print()
    size_choice = input(
        f"{BOLD}{t('model_size_prompt', recommended=recommended)}{RESET} "
    ).strip() or recommended

    category_map = {
        "1": ("small", t("model_category_small")),
        "2": ("medium", t("model_category_medium")),
        "3": ("large", t("model_category_large")),
    }
    category, category_name = category_map.get(size_choice, category_map[recommended])

    models = MODEL_CATALOG[category]

    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"\n{BOLD}{category_name}{RESET}\n")

    # Show available models in this category
    for i, model in enumerate(models, 1):
        fits = usable_ram >= model["ram_gb"]

        # Check available engines
        engines = []
        if model.get("mlx"):
            engines.append("MLX")
        if model.get("ollama"):
            engines.append("Ollama")
        if model.get("gguf"):
            engines.append("GGUF")
        engine_info = " / ".join(engines) if engines else t("none")

        # Catalan model highlight
        is_catalan = "AINA" in model["origin"] or "BSC" in model["origin"]
        catalan_tag = f" {MAGENTA}🏠 {t('model_tag_local_language')}{RESET}" if is_catalan else ""

        # Status based on RAM
        if fits:
            status = f"{GREEN}{t('model_status_compatible')}{RESET}"
        else:
            status = f"{RED}{t('model_status_maybe_tight')}{RESET}"

        print(f"  {CYAN}{i}.{RESET} {BOLD}{model['name']}{RESET} {DIM}({model['params']}){RESET}{catalan_tag}")
        print(f"     {model['origin']} | {t('model_engines_label')}: {engine_info}")
        print(
            f"     {CYAN}💾 {t('model_disk_label')}:{RESET} {model['disk_gb']} GB | "
            f"{CYAN}🧠 {t('model_ram_label')}:{RESET} {model['ram_gb']} GB"
        )
        print(f"     {DIM}{model['lang']}{RESET}")
        print(f"     {model['description']} | {status}")
        print()

    # Model selection
    default = "1"
    choice = input(
        f"{BOLD}{t('model_choice_prompt', count=len(models), default=default)}{RESET} "
    ).strip()
    if not choice:
        choice = default

    try:
        selected_model = models[int(choice) - 1]
    except (ValueError, IndexError):
        selected_model = models[0]

    # Engine selection - show all available options
    available_engines = []
    if has_metal and selected_model.get("mlx"):
        available_engines.append(("mlx", "MLX", t("engine_desc_mlx"), True))
    if selected_model.get("ollama"):
        available_engines.append(("ollama", "Ollama", t("engine_desc_ollama"), not has_metal))
    if selected_model.get("gguf"):
        available_engines.append(("llama_cpp", "llama.cpp (GGUF)", t("engine_desc_gguf"), False))

    engine = "ollama"  # Default fallback

    if len(available_engines) > 1:
        clear()
        print(APP_LOGO)
        print(f"\n{BOLD}⚡ {t('select_engine')}{RESET}")
        print(f"{BOLD}   {selected_model['name']}{RESET}\n")

        print(f"{DIM}{t('engine_explanation')}{RESET}\n")

        for i, (eng_key, eng_name, eng_desc, is_rec) in enumerate(available_engines, 1):
            rec_tag = f" {GREEN}← {t('recommended').upper()}{RESET}" if is_rec else ""
            print(f"  {CYAN}{i}.{RESET} {BOLD}{eng_name}{RESET}{rec_tag}")
            print(f"     {DIM}{eng_desc}{RESET}\n")

        default_idx = next((i for i, (_, _, _, rec) in enumerate(available_engines, 1) if rec), 1)
        engine_choice = input(
            f"{BOLD}{t('engine_choice_prompt', count=len(available_engines), default=default_idx)}{RESET} "
        ).strip()

        try:
            idx = int(engine_choice) - 1 if engine_choice else default_idx - 1
            engine = available_engines[idx][0]
        except (ValueError, IndexError):
            engine = available_engines[default_idx - 1][0]
    elif len(available_engines) == 1:
        engine = available_engines[0][0]
        print(
            f"\n  {DIM}ℹ️  "
            f"{t('engine_single_notice', model=selected_model['name'], engine=available_engines[0][1])}"
            f"{RESET}"
        )

    # Get model ID based on engine
    if engine == "mlx":
        model_id = selected_model["mlx"]
    elif engine == "llama_cpp":
        model_id = selected_model["gguf"]
    else:
        model_id = selected_model["ollama"]

    return {
        "size": category,
        "engine": engine,
        "id": model_id,
        "name": selected_model["name"],
        "disk_size": f"~{selected_model['disk_gb']} GB",
        "ram": selected_model["ram_gb"],
    }

def _show_manual_instructions(model, engine):
    """Show manual download instructions."""
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"{BOLD}📥 {t('download_instructions')}{RESET}")
    print(f"{YELLOW}{'─'*60}{RESET}\n")

    if engine == "ollama":
        print(f"{t('install_ollama_first')}")
        print(f"  {DIM}curl -fsSL https://ollama.com/install.sh | sh{RESET}\n")
        print(f"{t('to_download_ollama')}")
        print(f"  {CYAN}ollama pull {model['id']}{RESET}\n")
    elif engine == "llama_cpp":
        print(f"{t('download_gguf')}")
        print(f"  {CYAN}curl -L -o storage/models/{model['id'].split('/')[-1]} {model['id']}{RESET}\n")
    else:
        print(f"{t('to_download_mlx')}")
        print(f"  {CYAN}python -c \"from mlx_lm import load; load('{model['id']}')\" {RESET}\n")

    print(f"{t('after_download')}")
    print(f"  {CYAN}./nexe chat{RESET}\n")

    print(f"{DIM}💡 {t('manual_install_note')}{RESET}")

# ═══════════════════════════════════════════════════════════════════════════
# ENVIRONMENT SETUP
# ═══════════════════════════════════════════════════════════════════════════
def setup_environment(project_root, hw):
    print_step(f"{BOLD}{t('setting_up_env')}{RESET}")

    venv_path = project_root / "venv"
    if not venv_path.exists():
        print(f"  📦 {t('creating_venv')}")
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)

    # Path to pip/python based on OS
    if os.name == 'nt':
        pip_path = venv_path / "Scripts" / "pip.exe"
        python_path = venv_path / "Scripts" / "python.exe"
    else:
        pip_path = venv_path / "bin" / "pip"
        python_path = venv_path / "bin" / "python"

    # 1. Upgrade pip
    subprocess.run([str(pip_path), "install", "--upgrade", "pip"], capture_output=True)

    # 2. Install core requirements
    req_file = project_root / "requirements.txt"
    if req_file.exists():
        print(f"  📥 {t('installing_deps')}")
        subprocess.run([str(pip_path), "install", "-r", str(req_file)], check=True)
    else:
        print_error(t('requirements_not_found'))
        sys.exit(1)

    # 3. Hardware-Specific Inference Engines
    print_step(f"{BOLD}{t('installing_inference')}{RESET}")

    if hw['is_apple_silicon']:
        print(f"   {t('detected_apple')} {CYAN}mlx-lm{RESET}...")
        try:
            subprocess.run([str(pip_path), "install", "mlx-lm>=0.30.0"], check=True)
        except subprocess.CalledProcessError:
            print_warn(t(
                "mlx_version_fallback",
                "mlx-lm>=0.30.0 not available, installing latest compatible version."
            ))
            subprocess.run([str(pip_path), "install", "mlx-lm"], check=True)

    print(f"  🏗️ {t('installing_universal')} {CYAN}llama-cpp-python{RESET}...")
    env = os.environ.copy()
    if hw['is_apple_silicon']:
        env["CMAKE_ARGS"] = "-DGGML_METAL=on"

    try:
        subprocess.run(
            [str(pip_path), "install", "llama-cpp-python"],
            env=env,
            check=True,
            capture_output=True
        )
        print_success(f"llama-cpp-python {t('installed_gpu')}")
    except subprocess.CalledProcessError:
        print_warn(t('gpu_failed'))
        subprocess.run([str(pip_path), "install", "llama-cpp-python"], check=True)

    return python_path

def generate_env_file(project_root, model_config):
    """Generate .env file with security and model config.

    Security: API key is NOT printed to stdout to prevent exposure
    in CI/CD logs or shared terminal sessions.
    """
    print_step(f"{BOLD}{t('generating_security')}{RESET}")
    print(f"  {DIM}{t('security_explanation')}{RESET}")
    import secrets
    import stat
    secure_key = secrets.token_hex(32)
    env_file = project_root / ".env"

    if not env_file.exists():
        csrf_secret = secrets.token_hex(32)
        with open(env_file, "w") as f:
            f.write(f"NEXE_PRIMARY_API_KEY={secure_key}\n")
            f.write(f"NEXE_CSRF_SECRET={csrf_secret}\n")
            f.write(f"NEXE_ENV=production\n")
            f.write(f"NEXE_LOG_LEVEL=INFO\n")
            f.write(f"NEXE_APPROVED_MODULES=security,llama_cpp_module,mlx_module,ollama_module,web_ui_module\n")
            f.write(f"NEXE_LANG={LANG}\n")
            f.write(f"# Model configuration\n")
            f.write(f"NEXE_DEFAULT_MODEL={model_config['id']}\n")
            f.write(f"NEXE_MODEL_ENGINE={model_config['engine']}\n")
            # Engine-specific model paths (using relative paths for portability)
            if model_config['engine'] == 'mlx':
                model_name = model_config['id'].split('/')[-1]
                f.write(f"NEXE_MLX_MODEL=storage/models/{model_name}\n")
            elif model_config['engine'] == 'llama_cpp':
                # GGUF models are downloaded as single files
                filename = model_config['id'].split('/')[-1]
                f.write(f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n")
            f.write("QDRANT_HOST=localhost\n")
            f.write("QDRANT_PORT=6333\n")
            f.write("# Configurable timeouts (seconds)\n")
            f.write("NEXE_QDRANT_TIMEOUT=5.0\n")
            f.write("NEXE_SQLITE_PRELOAD_TIMEOUT=10.0\n")
            f.write("NEXE_OLLAMA_HEALTH_TIMEOUT=5.0\n")
            f.write("NEXE_OLLAMA_UNLOAD_TIMEOUT=10.0\n")

        # Set restrictive permissions (owner read/write only)
        env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # chmod 600

        print_success(t('env_created'))
        print(f"  🔑 {t('api_key')}: {DIM}[hidden - see .env file]{RESET}")
        print(f"  🔒 {t('saved_at')} {env_file} (chmod 600)")
    else:
        # Update existing .env with model configuration
        _update_env_model_config(env_file, model_config)
        print_success(t('env_exists'))


def _update_env_model_config(env_file, model_config):
    """Update model configuration in existing .env file."""
    import secrets

    # Read existing content
    with open(env_file, 'r') as f:
        lines = f.readlines()

    # Track which keys we need to update/add
    model_id = model_config['id']
    model_engine = model_config['engine']
    found_model = False
    found_engine = False
    found_csrf = False
    found_mlx_model = False
    found_llama_cpp_model = False
    new_lines = []

    for line in lines:
        if line.startswith('NEXE_DEFAULT_MODEL='):
            new_lines.append(f"NEXE_DEFAULT_MODEL={model_id}\n")
            found_model = True
        elif line.startswith('NEXE_MODEL_ENGINE='):
            new_lines.append(f"NEXE_MODEL_ENGINE={model_engine}\n")
            found_engine = True
        elif line.startswith('NEXE_CSRF_SECRET='):
            found_csrf = True
            new_lines.append(line)
        elif line.startswith('NEXE_MLX_MODEL='):
            found_mlx_model = True
            if model_engine == 'mlx':
                model_name = model_id.split('/')[-1]
                new_lines.append(f"NEXE_MLX_MODEL=storage/models/{model_name}\n")
            else:
                new_lines.append(line)
        elif line.startswith('NEXE_LLAMA_CPP_MODEL='):
            found_llama_cpp_model = True
            if model_engine == 'llama_cpp':
                filename = model_id.split('/')[-1]
                new_lines.append(f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Add missing keys at the end
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines.append('\n')

    if not found_csrf:
        new_lines.append(f"NEXE_CSRF_SECRET={secrets.token_hex(32)}\n")

    if not any('# Model configuration' in l for l in new_lines):
        new_lines.append("# Model configuration\n")
    if not found_model:
        new_lines.append(f"NEXE_DEFAULT_MODEL={model_id}\n")
    if not found_engine:
        new_lines.append(f"NEXE_MODEL_ENGINE={model_engine}\n")
    if not found_mlx_model and model_engine == 'mlx':
        model_name = model_id.split('/')[-1]
        new_lines.append(f"NEXE_MLX_MODEL=storage/models/{model_name}\n")
    if not found_llama_cpp_model and model_engine == 'llama_cpp':
        filename = model_id.split('/')[-1]
        new_lines.append(f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n")

    # Write back
    with open(env_file, 'w') as f:
        f.writelines(new_lines)

    print(f"  📝 {t('model_selected')}: {model_id} ({model_engine})")

def download_qdrant(project_root, hw):
    """Download Qdrant binary for the current platform."""
    import platform
    import tarfile

    qdrant_bin = project_root / "qdrant"
    if qdrant_bin.exists():
        print_success(t('qdrant_exists'))
        return True

    # Show informative explanation and ask for permission
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    info_text = t('qdrant_download_info').format(bold=BOLD, reset=RESET)
    print(info_text)
    print(f"{YELLOW}{'─'*60}{RESET}\n")

    confirm = input(f"{t('qdrant_download_prompt')} {t('yes_no')}: ").lower()
    if confirm == 'n':
        print(f"  {DIM}{t('qdrant_skipped')}{RESET}")
        return False

    print_step(f"{BOLD}{t('downloading_qdrant')}{RESET}")
    print(f"  {DIM}{t('qdrant_explanation')}{RESET}")

    # Determine platform
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            asset_name = "qdrant-aarch64-apple-darwin.tar.gz"
        else:
            asset_name = "qdrant-x86_64-apple-darwin.tar.gz"
    elif system == "linux":
        if "arm" in machine or "aarch64" in machine:
            asset_name = "qdrant-aarch64-unknown-linux-gnu.tar.gz"
        else:
            asset_name = "qdrant-x86_64-unknown-linux-gnu.tar.gz"
    else:
        print_warn(t('auto_download_not_supported', system=system, machine=machine))
        return False

    # Get latest release URL
    try:
        import urllib.request
        import json

        api_url = "https://api.github.com/repos/qdrant/qdrant/releases/latest"
        with urllib.request.urlopen(api_url, timeout=10) as response:
            release_data = json.loads(response.read().decode())

        assets = release_data.get("assets", [])
        download_url = None
        checksum_url = None
        checksum_candidates = [
            f"{asset_name}.sha256",
            f"{asset_name}.sha256sum",
            f"{asset_name}.sha256.txt",
            f"{asset_name}.sha256sum.txt",
        ]

        for asset in assets:
            name = asset.get("name")
            if name == asset_name:
                download_url = asset.get("browser_download_url")
            if name in checksum_candidates:
                checksum_url = asset.get("browser_download_url")

        if not download_url:
            print_warn(t('release_asset_not_found', asset_name=asset_name))
            return False

        checksum_value = None
        if checksum_url:
            try:
                print(f"  {DIM}{t('checksum_fetching')}{RESET}")
                checksum_text = _fetch_text(checksum_url)
                checksum_value = _parse_checksum(checksum_text)
                if not checksum_value:
                    print_warn(t('checksum_parse_failed'))
            except Exception:
                print_warn(t('checksum_download_failed'))
        else:
            print_warn(t('checksum_not_found'))

        # Download
        tar_path = project_root / asset_name
        print(f"  {BLUE}[...]{RESET} {download_url}")

        urllib.request.urlretrieve(download_url, tar_path)

        if checksum_value:
            print_step(t('checksum_verifying'))
            actual_checksum = _sha256_file(tar_path)
            if actual_checksum != checksum_value:
                print_warn(t('checksum_mismatch'))
                tar_path.unlink(missing_ok=True)
                return False
            print_success(t('checksum_verified'))

        # Extract
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name == "qdrant" or member.name.endswith("/qdrant"):
                    member.name = "qdrant"  # Extract to root
                    tar.extract(member, project_root)
                    break

        # Make executable
        qdrant_bin.chmod(0o755)

        # Cleanup tar
        tar_path.unlink()

        print_success(t('qdrant_downloaded'))
        _maybe_clear_quarantine(qdrant_bin)
        return True

    except Exception as e:
        print_warn(f"{t('qdrant_download_failed')}: {e}")
        return False


def _maybe_clear_quarantine(binary_path: Path) -> None:
    """Offer to remove Gatekeeper quarantine on macOS."""
    import platform

    if platform.system().lower() != "darwin":
        return

    # Show informative explanation
    info_text = t('qdrant_quarantine_info').format(bold=BOLD, reset=RESET)
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(info_text)
    print(f"{YELLOW}{'─'*60}{RESET}\n")

    confirm = input(f"{t('qdrant_quarantine_prompt')} {t('yes_no')}: ").lower()
    if confirm == 'n':
        print_warn(t('qdrant_quarantine_skipped'))
        return

    result = subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(binary_path)],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print_success(t('qdrant_quarantine_cleared'))
    else:
        print_warn(t('qdrant_quarantine_failed'))
        print(f"  {CYAN}xattr -dr com.apple.quarantine {binary_path}{RESET}")


def ensure_ollama_installed():
    """
    Ensure Ollama is installed (universal fallback for LLM inference).

    Ollama is always installed because:
    1. It's the universal fallback when MLX/llama.cpp fail
    2. It works on all platforms (macOS, Linux)
    3. It's the easiest way to run models
    """
    import platform

    # Check if already installed
    if shutil.which("ollama"):
        print_success(t('ollama_installed'))
        return True

    print_step(f"{BOLD}{t('installing_ollama')}{RESET}")
    confirm = input(f"{t('ollama_install_confirm')} {t('yes_no')}: ").lower()
    if confirm == 'n':
        print_warn(t('ollama_install_skipped'))
        print(f"  {DIM}{t('ollama_install_manual')}{RESET}")
        return False

    system = platform.system().lower()

    if system not in ("darwin", "linux"):
        print_warn(t('ollama_auto_install_not_supported', system=system))
        print(f"  {DIM}{t('ollama_install_manual')}{RESET}")
        return False

    install_url = "https://ollama.com/install.sh"
    install_cmd = f"curl -fsSL {install_url} -o /tmp/ollama_install.sh && sh /tmp/ollama_install.sh"

    try:
        import tempfile
        import urllib.request

        print(f"  {DIM}{t('ollama_script_fetching')}{RESET}")
        print(f"  {DIM}{t('label_command')}: {install_cmd}{RESET}")

        with urllib.request.urlopen(install_url, timeout=30) as response:
            script = response.read()

        script_path = None
        try:
            with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
                handle.write(script)
                script_path = Path(handle.name)
            script_path.chmod(0o700)

            result = subprocess.run(
                ["sh", str(script_path)],
                timeout=180  # 3 minutes max
            )
        finally:
            if script_path:
                script_path.unlink(missing_ok=True)

        if result.returncode == 0:
            print_success(t('ollama_installed'))
            return True
        else:
            print_warn(t('ollama_install_failed'))
            print(f"  {CYAN}{t('label_command')}: {install_cmd}{RESET}")
            return False

    except subprocess.TimeoutExpired:
        print_warn(t('ollama_install_timeout'))
        return False
    except Exception as e:
        print_warn(f"{t('ollama_install_failed')}: {e}")
        print(f"  {CYAN}{t('label_command')}: {install_cmd}{RESET}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# DIRECT DOWNLOAD FUNCTIONS (no python venv needed)
# ═══════════════════════════════════════════════════════════════════════════
def _download_ollama_model(model_config):
    """Download Ollama model immediately after selection."""
    clear()
    print(APP_LOGO)

    model_id = model_config['id']
    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   {t('label_model')}: {CYAN}{model_config['name']}{RESET}")
    print(f"   {t('label_ollama_id')}: {CYAN}{model_id}{RESET}")
    print(f"   {t('label_engine')}: Ollama")
    print()

    # Ask user
    print(f"{BOLD}{t('download_options')}{RESET}\n")
    print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
    print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
    print()

    choice = input(f"{BOLD}[1/2]:{RESET} ").strip()

    if choice == "1":
        try:
            # Check if Ollama is running
            print(f"\n{BLUE}[1/3]{RESET} {t('step_checking_ollama')}")
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            if result.returncode != 0:
                # Try to start Ollama
                print(f"{YELLOW}[...]{RESET} {t('step_starting_ollama')}")
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                import time
                time.sleep(3)

            # Download model - IMPORTANT: Don't capture output so user sees progress
            print(f"\n{BLUE}[2/3]{RESET} {t('step_downloading_model')}")
            print(f"      {DIM}{t('label_command')}: ollama pull {model_id}{RESET}\n")

            # Run with inherited stdout/stderr so Ollama's progress bar shows
            process = subprocess.Popen(
                ["ollama", "pull", model_id],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            return_code = process.wait()

            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, "ollama pull")

            # Verify model was downloaded
            print(f"\n{BLUE}[3/4]{RESET} {t('step_verify_download')}")
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            model_base = model_id.split(":")[0]
            if model_base in result.stdout or model_id in result.stdout:
                print_success(t('model_downloaded', model_id=model_id))
            else:
                print_warn(t('model_not_in_list'))
                print(f"  {DIM}{t('label_command')}: ollama list{RESET}")

            # Download embedding model (required for memory/RAG)
            print(f"\n{BLUE}[4/4]{RESET} {t('step_download_embeddings')}")
            print(f"      {DIM}{t('label_command')}: ollama pull nomic-embed-text{RESET}\n")

            embed_process = subprocess.Popen(
                ["ollama", "pull", "nomic-embed-text"],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            embed_return = embed_process.wait()

            if embed_return == 0:
                print_success(t('embeddings_downloaded'))
            else:
                print_warn(t('embeddings_download_failed'))
                print(f"  {DIM}{t('run_manual_command', cmd='ollama pull nomic-embed-text')}{RESET}")

        except subprocess.CalledProcessError as e:
            print_warn(f"{t('download_failed')} (code: {e.returncode})")
            _show_manual_instructions(model_config, "ollama")
        except FileNotFoundError:
            print_warn(t('ollama_not_found'))
            _show_manual_instructions(model_config, "ollama")
    else:
        _show_manual_instructions(model_config, "ollama")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    input(f"\n{DIM}[{t('press_enter')}]{RESET}")


def _download_gguf_model(model_config, project_root):
    """Download GGUF model immediately after selection."""
    clear()
    print(APP_LOGO)

    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   {t('label_model')}: {CYAN}{model_config['name']}{RESET}")
    print(f"   {t('label_engine')}: {t('engine_label_gguf')}")
    print()

    # Ask user
    print(f"{BOLD}{t('download_options')}{RESET}\n")
    print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
    print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
    print()

    choice = input(f"{BOLD}[1/2]:{RESET} ").strip()

    if choice == "1":
        try:
            models_dir = project_root / "storage" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            filename = model_config['id'].split('/')[-1]
            output_path = models_dir / filename

            print(f"\n{BLUE}[...]{RESET} {t('downloading_file', filename=filename)}")
            print(f"   {DIM}{model_config['id']}{RESET}")

            checksum_value = None
            for suffix in (".sha256", ".sha256sum"):
                try:
                    checksum_text = _fetch_text(model_config['id'] + suffix)
                    checksum_value = _parse_checksum(checksum_text)
                    if checksum_value:
                        break
                except Exception:
                    continue

            if shutil.which("curl"):
                subprocess.run([
                    "curl", "-L", "--progress-bar",
                    "-o", str(output_path),
                    model_config['id']
                ], check=True)
            else:
                print_warn(t('curl_not_found'))
                _download_file(model_config['id'], output_path)

            if checksum_value:
                print_step(t('checksum_verifying'))
                actual_checksum = _sha256_file(output_path)
                if actual_checksum != checksum_value:
                    print_warn(t('checksum_mismatch'))
                    output_path.unlink(missing_ok=True)
                    _show_manual_instructions(model_config, "llama_cpp")
                    return
                print_success(t('checksum_verified'))
            else:
                print_warn(t('checksum_not_found'))

            print_success(t('download_success'))
            print(f"  📁 {output_path}")
        except subprocess.CalledProcessError:
            print_warn(t('download_failed'))
            _show_manual_instructions(model_config, "llama_cpp")
        except Exception as e:
            print_warn(f"{t('download_failed')}: {e}")
            _show_manual_instructions(model_config, "llama_cpp")
    else:
        _show_manual_instructions(model_config, "llama_cpp")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    input(f"\n{DIM}[{t('press_enter')}]{RESET}")


def _download_mlx_model(model_config, project_root, python_path):
    """Download MLX model immediately after selection."""
    clear()
    print(APP_LOGO)

    model_id = model_config['id']
    model_name = model_id.split('/')[-1]

    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   {t('label_model')}: {CYAN}{model_config['name']}{RESET}")
    print(f"   {t('label_hf_id')}: {CYAN}{model_id}{RESET}")
    print(f"   {t('label_engine')}: {t('engine_label_mlx')}")
    print()

    # Ask user
    print(f"{BOLD}{t('download_options')}{RESET}\n")
    print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
    print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
    print()

    choice = input(f"{BOLD}[1/2]:{RESET} ").strip()

    if choice == "1":
        try:
            models_dir = project_root / "storage" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            local_model_path = models_dir / model_name

            if local_model_path.exists() and any(local_model_path.iterdir()):
                print(f"{GREEN}[OK]{RESET} {t('model_already_downloaded', path=local_model_path)}")
                input(f"\n{DIM}[{t('press_enter')}]{RESET}")
                return

            # Show BIG WARNING before download
            clear()
            print(APP_LOGO)
            print(f"\n{RED}{BOLD}{t('download_warning_title').format(size=model_config['disk_size'])}{RESET}\n")
            print(f"  {YELLOW}1.{RESET} {t('download_warning_power')}")
            print(f"  {YELLOW}2.{RESET} {t('download_warning_sleep')}")
            print(f"  {YELLOW}3.{RESET} {t('download_warning_wifi')}")
            print(f"\n  {DIM}• {t('download_warning_time')}{RESET}")
            print(f"  {DIM}• {t('download_warning_resume')}{RESET}\n")

            confirm = input(f"{GREEN}▶ {t('download_ready')} [Enter]:{RESET} ")

            print(f"\n{BLUE}[1/2]{RESET} {t('downloading_mlx')}")
            print(f"      {DIM}{t('download_destination', path=local_model_path)}{RESET}\n")

            # Download using huggingface_hub with resume + retry
            download_complete_msg = t('download_complete').replace('"', '\\"')
            download_retry_msg = t(
                'download_retrying',
                attempt='{attempt}',
                max_retries='{max_retries}'
            ).replace('"', '\\"')
            download_script = f'''
from huggingface_hub import snapshot_download
import time

max_retries = 3
for attempt in range(max_retries):
    try:
        snapshot_download(
            repo_id="{model_id}",
            local_dir="{local_model_path}",
            local_dir_use_symlinks=False,
            resume_download=True,
            max_workers=4
        )
        print("{download_complete_msg}")
        break
    except Exception as e:
        if attempt < max_retries - 1:
            print("{download_retry_msg}".format(attempt=attempt+1, max_retries=max_retries))
            time.sleep(5)
        else:
            raise e
'''
            process = subprocess.Popen(
                [str(python_path), "-c", download_script],
                stdout=sys.stdout,
                stderr=sys.stderr,
                env={**os.environ, "PYTHONPATH": str(project_root)}
            )
            return_code = process.wait()

            if return_code == 0:
                print_success(t('model_downloaded_to', path=local_model_path))

                # Validate model has required files
                print(f"\n{BLUE}[2/2]{RESET} {t('model_validating_mlx')}")
                config_file = local_model_path / "config.json"
                if not config_file.exists():
                    print_warn(t('model_missing_config', path=local_model_path))
                    print(f"{DIM}{t('model_possible_issues')}{RESET}")
                else:
                    print(f"{GREEN}✓{RESET} {t('model_validated')}")
            else:
                print(f"\n{YELLOW}{t('download_failed_resume')}{RESET}")
                print(f"{DIM}{t('download_partial_kept')}{RESET}\n")
                _show_manual_instructions(model_config, "mlx")

        except Exception as e:
            print(f"\n{YELLOW}{t('download_failed_resume')}{RESET}")
            print(f"{DIM}{t('download_error_detail', error=str(e)[:200])}{RESET}")
            print(f"{DIM}{t('download_partial_kept')}{RESET}\n")
            _show_manual_instructions(model_config, "mlx")
    else:
        _show_manual_instructions(model_config, "mlx")
        print(f"\n{YELLOW}{t('mlx_required_warning')}{RESET}")
        print(f"   {t('mlx_fallback_ollama')}")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    input(f"\n{DIM}[{t('press_enter')}]{RESET}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
def main():
    # 1. Language selection
    select_language()

    clear()
    print(APP_LOGO)
    project_root = Path(__file__).parent.resolve()

    # 2. Hardware detection
    hw = detect_hardware()

    # 3. Confirm installation
    confirm = input(f"\n{BOLD}{t('proceed_install')}{RESET} {t('yes_no')}: ").lower()
    if confirm == 'n':
        return

    # 3.5. Clean existing venv to avoid conflicts
    venv_path = project_root / "venv"
    if venv_path.exists():
        print(f"\n{YELLOW}[CLEAN]{RESET} {t('venv_clean_detected')}")
        import shutil
        shutil.rmtree(venv_path)
        print(f"{GREEN}[OK]{RESET} {t('venv_cleaned')}")

    storage_path = project_root / "storage"
    if storage_path.exists():
        confirm = input(
            f"\n{YELLOW}[CLEAN]{RESET} {t('storage_cleanup_confirm')} {t('yes_no_default_no')}: "
        ).strip().lower()
        if confirm in ("s", "y"):
            print(f"{YELLOW}[CLEAN]{RESET} {t('cleaning_storage')}")
            import shutil
            shutil.rmtree(storage_path)
            print(f"{GREEN}[OK]{RESET} {t('storage_removed')}")
        else:
            print(f"{DIM}{t('storage_kept')}{RESET}")

    # 4. MODEL SELECTION FIRST - while user is engaged
    model_config = select_model(hw)

    # 4.5. Show download confirmation screen with power warning
    clear()
    print(APP_LOGO)
    print(f"\n{BOLD}📦 {t('download_confirmation_title')}{RESET}\n")
    print(f"{DIM}{t('download_confirmation_text')}{RESET}\n")

    # Big warning for laptop users
    print(f"{YELLOW}{'─'*70}{RESET}")
    print(f"{YELLOW}{BOLD}⚠️  {t('laptop_warning')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_power')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_sleep')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_wifi')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_time')}{RESET}")
    print(f"{YELLOW}{'─'*70}{RESET}\n")

    input(f"{GREEN}{t('download_continue')}{RESET}")

    # 5. Create storage folders (needed for model download)
    print_step(f"{BOLD}{t('preparing_data')}{RESET}")
    folders = [
        "storage/cache",
        "storage/logs",
        "storage/models",
        "storage/vectors",
    ]
    for folder in folders:
        (project_root / folder).mkdir(parents=True, exist_ok=True)
        print(f"  ✅ {folder}/")

    # 6. If Ollama selected: install Ollama and download model NOW
    engine = model_config.get("engine", "ollama")
    if engine == "ollama":
        ensure_ollama_installed()
        # Download Ollama model immediately
        _download_ollama_model(model_config)
    elif engine == "llama_cpp":
        # Download GGUF model immediately (just needs curl)
        _download_gguf_model(model_config, project_root)

    # 7. Setup environment (pip install - takes time)
    python_path = setup_environment(project_root, hw)

    # 8. If MLX selected: validate Metal BEFORE downloading
    if engine == "mlx":
        # Verify Metal is actually available after installing mlx-lm
        metal_available = False
        try:
            result = subprocess.run(
                [str(python_path), "-c", "import mlx.core as mx; print(mx.metal.is_available())"],
                capture_output=True,
                text=True,
                timeout=10
            )
            metal_available = result.stdout.strip() == "True"
        except Exception:
            metal_available = False

        if not metal_available:
            clear()
            print(APP_LOGO)
            print(f"\n{RED}{t('metal_unavailable_title')}{RESET}\n")
            print(f"{DIM}{t('metal_required')}{RESET}")
            print(f"{DIM}{t('metal_unavailable_detail')}{RESET}\n")
            print(f"{YELLOW}{t('metal_options')}{RESET}\n")
            print(f"  {CYAN}1.{RESET} {t('metal_option_ollama')}")
            print(f"  {CYAN}2.{RESET} {t('metal_option_abort')}\n")

            choice = input(f"{BOLD}{t('metal_choice_prompt')}{RESET} ").strip()

            if choice == "1":
                # Get the selected_model to find Ollama equivalent
                # We need to reconstruct which model was selected
                # This is a bit hacky but necessary
                selected_model = None
                for category in MODEL_CATALOG:
                    for model in category["models"]:
                        if model.get("mlx") == model_config['id']:
                            selected_model = model
                            break
                    if selected_model:
                        break

                if selected_model and selected_model.get("ollama"):
                    model_config['engine'] = 'ollama'
                    model_config['id'] = selected_model['ollama']
                    print(
                        f"\n{GREEN}✓{RESET} "
                        f"{t('metal_switched_ollama', model_id=model_config['id'])}{RESET}\n"
                    )

                    # Download Ollama model
                    ensure_ollama_installed()
                    _download_ollama_model(model_config)
                else:
                    print_error(t('metal_no_ollama_alternative'))
                    sys.exit(1)
            else:
                print(f"\n{YELLOW}{t('install_cancelled')}{RESET}")
                sys.exit(0)
        else:
            # Metal is available, proceed with MLX download
            _download_mlx_model(model_config, project_root, python_path)

    # 9. Generate .env with model config
    generate_env_file(project_root, model_config)

    # 10. Clean module cache
    cache_file = project_root / "personality" / ".module_cache.json"
    if cache_file.exists():
        cache_file.unlink()
        print(f"  🧹 {t('module_cache_cleaned')}")
        print(f"     {DIM}{t('cache_explanation')}{RESET}")

    # 11. Download Qdrant binary
    download_qdrant(project_root, hw)

    # 12. Create nexe wrapper script
    nexe_wrapper = project_root / "nexe"
    with open(nexe_wrapper, "w") as f:
        f.write("#!/bin/bash\n")
        f.write("SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n")
        f.write("export PYTHONPATH=\"$PYTHONPATH:${SCRIPT_DIR}\"\n")
        f.write("\"${SCRIPT_DIR}/venv/bin/python\" -m core.cli \"$@\"\n")
    nexe_wrapper.chmod(0o755)
    print(f"  ✅ {t('executable_created')}")
    print(f"     {DIM}{t('executable_explanation')}{RESET}")

    # 12.5. Try to create symlink to /usr/local/bin for global access
    global_symlink_created = False
    try:
        symlink_path = Path("/usr/local/bin/nexe")
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(nexe_wrapper)
        print(f"  ✅ {t('symlink_created')}")
        print(f"     {DIM}{t('symlink_global')}{RESET}")
        global_symlink_created = True
    except PermissionError:
        print(f"\n  {YELLOW}⚠️  {t('symlink_failed')}{RESET}")
        print(f"     {DIM}{t('symlink_manual')}{RESET}")
        print(f"     {CYAN}export PATH=\"$PATH:{project_root}\"{RESET}\n")
    except Exception as e:
        print(
            f"  {DIM}"
            f"{t('symlink_not_created', error=str(e)[:50], path=project_root)}"
            f"{RESET}"
        )

    # 13. Create knowledge folder and inform user
    print_step(f"{BOLD}{t('knowledge_folder_created')}{RESET}")
    knowledge_dir = project_root / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)
    print(f"  ✅ {t('knowledge_folder_created_ok')}")
    print(f"  {DIM}{t('knowledge_explanation')}{RESET}")

    # 14. Download embedding model (with explanation and permission)
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    info_text = t('embeddings_info').format(bold=BOLD, reset=RESET)
    print(info_text)
    print(f"{YELLOW}{'─'*60}{RESET}\n")

    confirm = input(f"{t('embeddings_download_prompt')} {t('yes_no')}: ").lower()
    if confirm == 'n':
        print(f"  {DIM}{t('embeddings_skipped')}{RESET}")
    else:
        print_step(f"{BOLD}{t('embeddings_download_step')}{RESET}")
        print(f"  {DIM}{t('embeddings_download_time')}{RESET}\n")
        try:
            start_msg = t('embeddings_download_start').replace("'", "\\'")
            done_msg = t('embeddings_download_complete').replace("'", "\\'")
            # Don't capture output so user sees download progress from sentence-transformers
            result = subprocess.run([
                str(python_path), "-c",
                "from sentence_transformers import SentenceTransformer; "
                f"print('\\n  {start_msg}\\n'); "
                "model = SentenceTransformer('all-MiniLM-L6-v2'); "
                f"print('\\n  {done_msg}')"
            ], check=True, capture_output=False)  # ← Changed to False to show progress
            print(f"\n  {t('embeddings_download_success')}")
        except subprocess.CalledProcessError as e:
            print(f"  {YELLOW}{t('embeddings_download_error')}{RESET}")
            print(f"  {DIM}{t('embeddings_download_auto')}{RESET}")

    # 15. Ingest knowledge documents if any exist
    knowledge_files = list(knowledge_dir.glob("*.md")) + list(knowledge_dir.glob("*.txt")) + list(knowledge_dir.glob("*.pdf"))
    knowledge_files = [f for f in knowledge_files if not f.name.startswith('.') and f.name != 'README.md']

    if knowledge_files:
        print_step(
            f"{BOLD}{t('knowledge_processing_step', count=len(knowledge_files))}{RESET}"
        )
        print(f"  {DIM}{t('knowledge_processing_time')}{RESET}\n")
        try:
            # Start Qdrant first
            qdrant_bin = project_root / "qdrant"
            qdrant_storage = project_root / "storage" / "qdrant"
            qdrant_storage.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["QDRANT__STORAGE__STORAGE_PATH"] = str(qdrant_storage)
            env["QDRANT__SERVICE__HTTP_PORT"] = "6333"
            env["QDRANT__SERVICE__DISABLE_TELEMETRY"] = "true"

            qdrant_process = subprocess.Popen(
                [str(qdrant_bin), "--disable-telemetry"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )

            # Wait for Qdrant to start
            time.sleep(3)

            # Run ingestion with progress output (quiet=False)
            result = subprocess.run([
                str(python_path), "-c",
                f"import sys; sys.path.insert(0, '{project_root}'); "
                "import asyncio; "
                "from core.ingest.ingest_knowledge import ingest_knowledge; "
                f"asyncio.run(ingest_knowledge(quiet=False))"  # ← Changed to False to show progress
            ], check=True, capture_output=False, text=True, timeout=300)  # ← Changed to False

            print(f"\n  {t('knowledge_processing_success')}")

            # Create marker to skip re-ingestion on first server startup
            marker_file = project_root / "storage" / ".knowledge_ingested"
            marker_file.touch()

            # Stop Qdrant
            qdrant_process.terminate()
            qdrant_process.wait(timeout=5)

        except subprocess.TimeoutExpired:
            print(f"  {YELLOW}{t('knowledge_processing_timeout')}{RESET}")
            if 'qdrant_process' in locals():
                qdrant_process.terminate()
        except Exception as e:
            print(
                f"  {YELLOW}{t('knowledge_processing_error', error=str(e)[:200])}{RESET}"
            )
            print(f"  {DIM}{t('knowledge_processing_auto')}{RESET}")
            if 'qdrant_process' in locals():
                try:
                    qdrant_process.terminate()
                except:
                    pass
    else:
        print(f"  {DIM}{t('knowledge_no_documents')}{RESET}")

    # 16. Final summary
    input(f"\n{DIM}[{t('press_enter')}]{RESET}")
    clear()
    print(APP_LOGO)
    print(f"{GREEN}✅ {t('install_complete')}{RESET}")

    print(f"\n{BOLD}🤖 {t('label_model')}: {CYAN}{model_config['name']}{RESET}")

    # Use 'nexe' if global symlink was created, otherwise use './nexe'
    nexe_cmd = "nexe" if global_symlink_created else "./nexe"

    print(f"\n{BOLD}🚀 {t('how_to_start')}{RESET}")
    print(f"  {CYAN}{t('step')} 1:{RESET} {nexe_cmd} go")
    print(f"         {DIM}{t('step_start_server')}{RESET}")
    print(f"  {CYAN}{t('step')} 2:{RESET} {t('step_new_terminal')}")
    print(f"  {CYAN}{t('step')} 3:{RESET} {nexe_cmd} chat")
    print(f"         {DIM}{t('step_chat')}{RESET}")

    # If symlink not created, show instructions
    if not global_symlink_created:
        print(f"\n{YELLOW}📌 {t('optional_global_command')}{RESET}")
        print(f"  {DIM}{t('optional_global_instructions')}{RESET}")
        print(f"  {CYAN}sudo ln -sf {project_root}/nexe /usr/local/bin/nexe{RESET}")

    print(f"\n  {YELLOW}💡 {t('save_memory_tip')}{RESET}")
    print(f"  {DIM}💡 {t('venv_automatic')}{RESET}")

    # Create COMMANDS.md reference file
    commands_content = f"""# Nexe - Comandes / Commands

## 🚀 Ús bàsic / Basic usage

### Iniciar servidor / Start server
```bash
{nexe_cmd} go
```

### Xat interactiu / Interactive chat
```bash
{nexe_cmd} chat
```

### Xat amb motor específic / Chat with specific engine
```bash
{nexe_cmd} chat --engine mlx
{nexe_cmd} chat --engine ollama
{nexe_cmd} chat --engine llama_cpp
```

## 📊 Comandes de sistema / System commands

```bash
{nexe_cmd} status          # Estat del sistema / System status
{nexe_cmd} logs            # Veure logs / View logs
{nexe_cmd} health          # Health check
```

## 🧠 Gestió de memòria / Memory management

```bash
{nexe_cmd} memory store "text"     # Guardar a memòria / Save to memory
{nexe_cmd} memory recall "query"   # Cercar a memòria / Search memory
```

## 📚 Gestió de coneixement / Knowledge management

```bash
{nexe_cmd} knowledge ingest        # Processar documents / Process documents
{nexe_cmd} knowledge list          # Llistar documents / List documents
```

## ⚙️ Configuració / Configuration

- **Fitxer principal / Main file**: `.env`
- **Personalitat / Personality**: `personality/server.toml`
- **Models**: `storage/models/`
- **Logs**: `storage/logs/`

## 🔧 Troubleshooting

### Verificar MLX / Check MLX
```bash
./venv/bin/python -c "import mlx.core as mx; print('MLX:', mx.metal.is_available())"
```

### Reinstal·lar dependències / Reinstall dependencies
```bash
./venv/bin/pip install -r requirements.txt
```

---

📝 **Model actual / Current model**: {model_config['name']}
🔧 **Motor / Engine**: {model_config['engine']}
💾 **Ubicació / Location**: {project_root}

*Personal project by Jordi Goy · www.jgoy.net*
"""

    try:
        commands_file = project_root / "COMMANDS.md"
        with open(commands_file, 'w', encoding='utf-8') as f:
            f.write(commands_content)
        print(f"\n  {DIM}{t('commands_available')}{RESET}")
    except Exception as e:
        print_warn(t('commands_write_failed', error=e))

    print(f"\n{DIM}{'─'*65}{RESET}")
    print(f"\n{BOLD}{t('disclaimer_title')}{RESET}")
    print(f"  · {t('disclaimer_bugs')}")
    print(f"  · {t('disclaimer_tested')}")
    print(f"    {t('disclaimer_contribute')}")
    print(f"  · {t('disclaimer_thanks')}")
    print(f"  · {t('disclaimer_docs')}")
    print("\n" + "═"*65 + "\n")

if __name__ == "__main__":
    main()
