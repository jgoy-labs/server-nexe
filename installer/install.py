"""
────────────────────────────────────
Server Nexe
Location: installer/install.py
Description: Installer orchestrator — coordinates all installation steps.
────────────────────────────────────
"""

import os
import shutil
import sys
import subprocess
import time
from pathlib import Path

from .installer_display import (
    APP_LOGO, clear,
    GREEN, RED, YELLOW, CYAN, BOLD, DIM, RESET,
    print_step, print_success, print_warn, print_error,
)
from .installer_i18n import select_language, t, get_lang
from .installer_hardware import detect_hardware
from .installer_catalog import select_model, MODEL_CATALOG
from .installer_setup_env import setup_environment
from .installer_setup_config import generate_env_file
from .installer_setup_qdrant import download_qdrant
from .installer_setup_models import (
    ensure_ollama_installed,
    _download_ollama_model,
    _download_gguf_model,
    _download_mlx_model,
)
from .installer_finalize import show_final_summary


def run_installer():
    # 1. Language selection
    select_language()

    clear()
    print(APP_LOGO)
    project_root = Path(__file__).parent.parent.resolve()

    # 2. Hardware detection
    hw = detect_hardware()

    # 3. Confirm installation
    confirm = input(f"\n{BOLD}{t('proceed_install')}{RESET} {t('yes_no')}: ").lower()
    if confirm == 'n':
        return

    # 3.5. Clean existing venv to avoid conflicts
    venv_path = project_root / "venv"
    if venv_path.exists():
        print(f"\n{YELLOW}[CLEAN]{RESET} {t('cleaning_venv')}")
        shutil.rmtree(venv_path)
        print(f"{GREEN}[OK]{RESET} {t('venv_removed')}")

    storage_path = project_root / "storage"
    if storage_path.exists():
        print(f"\n{YELLOW}[CLEAN]{RESET} {t('cleaning_storage')}")
        shutil.rmtree(storage_path)
        print(f"{GREEN}[OK]{RESET} {t('storage_removed')}")

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
            print(f"\n{RED}{t('metal_unavailable')}{RESET}\n")
            print(f"{DIM}{t('metal_needs_explanation')}{RESET}")
            print(f"{DIM}{t('metal_cannot_init')}{RESET}\n")
            print(f"{YELLOW}{t('mlx_fallback_options')}{RESET}\n")
            print(f"  {CYAN}1.{RESET} {t('switch_to_ollama_option')}")
            print(f"  {CYAN}2.{RESET} {t('abort_install_option')}\n")

            choice = input(f"{BOLD}{t('select_fallback_prompt')}{RESET} ").strip()

            if choice == "1":
                # Get the selected_model to find Ollama equivalent
                # We need to reconstruct which model was selected
                # This is a bit hacky but necessary
                selected_model = None
                for category in MODEL_CATALOG:
                    for model in MODEL_CATALOG[category]:
                        if model.get("mlx") == model_config['id']:
                            selected_model = model
                            break
                    if selected_model:
                        break

                if selected_model and selected_model.get("ollama"):
                    model_config['engine'] = 'ollama'
                    model_config['id'] = selected_model['ollama']
                    print(f"\n{GREEN}✓{RESET} {t('switched_to_ollama_msg').format(id=model_config['id'])}\n")

                    # Download Ollama model
                    ensure_ollama_installed()
                    _download_ollama_model(model_config)
                else:
                    print_error(t('no_ollama_alternative'))
                    sys.exit(1)
            else:
                print(f"\n{YELLOW}{t('installation_cancelled')}{RESET}")
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
        f.write(f"export PYTHONPATH=\"$PYTHONPATH:{project_root}\"\n")
        f.write(f"{python_path} -m core.cli \"$@\"\n")
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
        print(f"  {DIM}{t('symlink_not_created').format(error=str(e)[:50], path=project_root)}{RESET}")

    # 13. Create knowledge folder and inform user
    print_step(f"{BOLD}{t('knowledge_folder_created')}{RESET}")
    knowledge_dir = project_root / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)
    print(f"  ✅ {t('knowledge_dir_created')}")
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
        print_step(f"{BOLD}{t('downloading_embeddings_step')} (all-MiniLM-L6-v2)...{RESET}")
        print(f"  {DIM}{t('downloading_model_progress')}{RESET}\n")
        try:
            # Don't capture output so user sees download progress from sentence-transformers
            msg_start = t('embeddings_starting').replace("'", "\\'")
            msg_done = t('embeddings_done').replace("'", "\\'")
            result = subprocess.run([
                str(python_path), "-c",
                f"from sentence_transformers import SentenceTransformer; "
                f"print('\\n  {msg_start}\\n'); "
                f"model = SentenceTransformer('all-MiniLM-L6-v2'); "
                f"print('\\n  {msg_done}')"
            ], check=True, capture_output=False)
            print(f"\n  {t('embeddings_downloaded_ok')}")
        except subprocess.CalledProcessError as e:
            print(f"  {YELLOW}{t('embeddings_download_error')}{RESET}")
            print(f"  {DIM}{t('embeddings_auto_download')}{RESET}")

    # 15. Ingest knowledge documents if any exist
    lang = get_lang()
    _ingest_dir = knowledge_dir / lang if (knowledge_dir / lang).is_dir() else knowledge_dir
    knowledge_files = list(_ingest_dir.glob("*.md")) + list(_ingest_dir.glob("*.txt")) + list(_ingest_dir.glob("*.pdf"))
    knowledge_files = [f for f in knowledge_files if not f.name.startswith('.')]

    if knowledge_files:
        print_step(f"{BOLD}{t('processing_knowledge').format(n=len(knowledge_files))}{RESET}")
        print(f"  {DIM}{t('processing_knowledge_wait')}{RESET}\n")
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
            ingest_env = {**os.environ, "NEXE_LANG": lang}
            result = subprocess.run([
                str(python_path), "-c",
                f"import sys; sys.path.insert(0, '{project_root}'); "
                "import asyncio; "
                "from core.ingest.ingest_knowledge import ingest_knowledge; "
                f"asyncio.run(ingest_knowledge(quiet=False))"
            ], check=True, capture_output=False, text=True, timeout=300, env=ingest_env)

            print(f"\n  {t('knowledge_indexed_ok')}")

            # Create marker to skip re-ingestion on first server startup
            marker_file = project_root / "storage" / ".knowledge_ingested"
            marker_file.touch()

            # Stop Qdrant
            qdrant_process.terminate()
            qdrant_process.wait(timeout=5)

        except subprocess.TimeoutExpired:
            print(f"  {YELLOW}⚠️  {t('ingest_timeout')}{RESET}")
            if 'qdrant_process' in locals():
                qdrant_process.terminate()
        except Exception as e:
            print(f"  {YELLOW}⚠️  {t('ingest_error').format(error=str(e)[:200])}{RESET}")
            print(f"  {DIM}{t('ingest_auto_first_start')}{RESET}")
            if 'qdrant_process' in locals():
                try:
                    qdrant_process.terminate()
                except Exception:
                    pass
    else:
        print(f"  {DIM}📝 {t('no_knowledge_docs')}{RESET}")

    # 16. Final summary
    show_final_summary(model_config, project_root, global_symlink_created, lang)
