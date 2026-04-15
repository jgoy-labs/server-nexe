"""
────────────────────────────────────
Server Nexe
Location: installer/install.py
Description: Installer orchestrator — coordinates all installation steps.
────────────────────────────────────
"""

import os
import re
import shutil
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .installer_display import (
    APP_LOGO, clear,
    GREEN, RED, YELLOW, CYAN, BOLD, DIM, RESET,
    print_step, print_error,
)
from .installer_i18n import select_language, t, get_lang
from .installer_hardware import detect_hardware
from .installer_catalog import select_model, MODEL_CATALOG
from .installer_setup_env import setup_environment
from .installer_setup_config import generate_env_file
from .installer_setup_models import (
    ensure_ollama_installed,
    _download_ollama_model,
    _download_gguf_model,
    _download_mlx_model,
)
from .installer_finalize import show_final_summary
from .installer_reinstall import (
    REINSTALL_MODE_BACKUP,
    REINSTALL_MODE_OVERWRITE,
    REINSTALL_MODE_WIPE,
    apply_reinstall_mode,
    detect_existing_install,
)


class _TeeWriter:
    """Duplicates stdout to a log file, stripping ANSI codes for the file."""
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

    def __init__(self, log_path):
        self._terminal = sys.stdout
        self._log = open(log_path, 'w', encoding='utf-8')
        self._log.write(f"# Nexe Installer Log — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        self.log_path = log_path

    def write(self, text):
        self._terminal.write(text)
        self._log.write(self._ANSI_RE.sub('', text))
        self._log.flush()

    def flush(self):
        self._terminal.flush()
        self._log.flush()

    def close(self):
        self._log.close()
        sys.stdout = self._terminal

    def __getattr__(self, name):
        return getattr(self._terminal, name)


def run_installer():
    # 1. Language selection
    select_language()

    clear()
    print(APP_LOGO)
    project_root = Path(__file__).parent.parent.resolve()

    # Setup install log — storage/logs/ may not exist yet, create early
    log_dir = project_root / "storage" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"install_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    tee = _TeeWriter(log_path)
    sys.stdout = tee

    # 2. Hardware detection
    hw = detect_hardware()

    # 3. Confirm installation
    confirm = input(f"\n{BOLD}{t('proceed_install')}{RESET} {t('yes_no')}: ").strip().lower()
    if confirm not in ('y', 'yes', 's', 'si', 'sí'):
        print("Cancelled.")
        tee.close()
        return

    # 3.5. Reinstall handling — Bug 7 fix.
    # Si detectem instal·lació existent oferim 3 opcions:
    #   1) Esborra-ho tot
    #   2) Sobreescriu sistema preservant dades
    #   3) Backup automàtic + instal·lació neta (default segur)
    if detect_existing_install(project_root):
        print(f"\n{YELLOW}[!] Instal·lació existent detectada a:{RESET} {project_root}")
        print(f"\n  {CYAN}1){RESET} Esborra-ho tot (.env, storage/, knowledge/, venv)")
        print(f"  {CYAN}2){RESET} Sobreescriu sistema preservant dades (manté .env, storage/, knowledge/)")
        print(f"  {CYAN}3){RESET} Backup automàtic + instal·lació neta {DIM}[per defecte]{RESET}")
        choice = input(f"\n{BOLD}Tria [1/2/3]:{RESET} ").strip()
        mode_map = {
            "1": REINSTALL_MODE_WIPE,
            "2": REINSTALL_MODE_OVERWRITE,
            "3": REINSTALL_MODE_BACKUP,
            "": REINSTALL_MODE_BACKUP,
        }
        mode = mode_map.get(choice, REINSTALL_MODE_BACKUP)
        try:
            summary = apply_reinstall_mode(project_root, mode)
            print(f"{GREEN}[OK]{RESET} Mode aplicat: {mode}")
            if summary.get("backup_dir"):
                print(f"  📦 Backup creat a: {summary['backup_dir']}")
            if summary.get("removed"):
                print(f"  🧹 {len(summary['removed'])} elements esborrats")
        except Exception as e:
            print_error(f"Reinstall mode failed: {e}")
            return
    else:
        # Sense instal·lació prèvia: assegurem que el venv està net per si de cas.
        venv_path = project_root / "venv"
        if venv_path.exists():
            print(f"\n{YELLOW}[CLEAN]{RESET} {t('cleaning_venv')}")
            shutil.rmtree(venv_path)
            print(f"{GREEN}[OK]{RESET} {t('venv_removed')}")

    # 4. MODEL SELECTION FIRST - while user is engaged
    model_config = select_model(hw)

    # 4b. Skip intended for power users who already run Ollama with local
    # models. Don't force a download — detect the first locally available
    # Ollama model and use it as the default. Only if nothing is detected,
    # fall back to downloading Qwen3.5 2B (smallest multilingual option) so
    # the server still boots with something. Previously the skip branch left
    # .env without NEXE_DEFAULT_MODEL and the server came up unhealthy.
    if model_config is None:
        detected = None
        try:
            import json as _json
            import urllib.request as _urlreq
            with _urlreq.urlopen("http://localhost:11434/api/tags", timeout=2) as _resp:
                _data = _json.loads(_resp.read().decode("utf-8"))
                _models = _data.get("models", [])
                if _models:
                    detected = _models[0].get("name")
        except Exception:
            detected = None

        if detected:
            print(f"\n{GREEN}✓{RESET} {DIM}Model Ollama detectat: {CYAN}{detected}{RESET}{DIM} — s'usarà com a default.{RESET}\n")
            model_config = {
                "size": "small",
                "engine": "ollama",
                "id": detected,
                "name": detected,
                "disk_size": "(local)",
                "ram": 0,
                "prompt_tier": "full",
                "chat_format": "chatml",
            }
        else:
            print(f"\n{YELLOW}Cap model local detectat — instal·lant Qwen3.5 2B per defecte perquè el servidor arrenqui.{RESET}\n")
            _fallback = next(
                (m for m in MODEL_CATALOG["small"] if m.get("key") == "qwen35_2b"),
                MODEL_CATALOG["small"][0],
            )
            model_config = {
                "size": "small",
                "engine": "ollama",
                "id": _fallback["ollama"],
                "name": _fallback["name"],
                "disk_size": f"~{_fallback['disk_gb']} GB",
                "ram": _fallback["ram_gb"],
                "prompt_tier": _fallback.get("prompt_tier", "small"),
                "chat_format": _fallback.get("chat_format", "chatml"),
            }

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
    python_path = setup_environment(project_root, hw, engine=model_config.get('engine', 'auto'))

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

    # 11. (Q5.5 reobert 2026-04-08) — Qdrant binari servidor extern eliminat.
    #     El server v0.9.0 usa QdrantClient(path="storage/vectors") embedded
    #     via core/qdrant_pool.py. Cap binari extern necessari.

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

    confirm = input(f"{t('embeddings_download_prompt')} {t('yes_no')}: ").strip().lower()
    if confirm not in ('y', 'yes', 's', 'si', 'sí'):
        print(f"  {DIM}{t('embeddings_skipped')}{RESET}")
    else:
        # Read embedding model from server.toml (SSOT)
        _emb_model = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
        try:
            import toml as _toml
            _srv_cfg = _toml.load(project_root / "personality" / "server.toml")
            _emb_model = _srv_cfg.get("plugins", {}).get("models", {}).get("embedding", _emb_model)
        except Exception:
            pass
        print_step(f"{BOLD}{t('downloading_embeddings_step')} ({_emb_model})...{RESET}")
        print(f"  {DIM}{t('downloading_model_progress')}{RESET}\n")
        try:
            # Don't capture output so user sees download progress from fastembed
            msg_start = t('embeddings_starting').replace("'", "\\'")
            msg_done = t('embeddings_done').replace("'", "\\'")
            emb_env = {**os.environ, "TRANSFORMERS_VERBOSITY": "error"}
            result = subprocess.run([
                str(python_path), "-c",
                f"from fastembed import TextEmbedding; "
                f"import sys; "
                f"print('\\n  {msg_start}\\n'); "
                f"model = TextEmbedding(sys.argv[1]); "
                f"print('\\n  {msg_done}')",
                _emb_model,
            ], check=True, capture_output=False, env=emb_env)
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
            # Q5.5 reobert (2026-04-08): ingestió via embedded QdrantClient.
            # Abans arrencàvem un binari Qdrant servidor extern a 'storage/qdrant/'
            # que ningú connectava (ingest_knowledge va per embedded via
            # core/qdrant_pool.py a 'storage/vectors/'), deixant residu mort.
            # Ara la ingestió va directament per embedded.
            ingest_env = {**os.environ, "NEXE_LANG": lang, "TRANSFORMERS_VERBOSITY": "error"}
            result = subprocess.run([
                str(python_path), "-c",
                f"import sys; sys.path.insert(0, '{project_root}'); "
                "import asyncio; "
                "from core.ingest.ingest_knowledge import ingest_knowledge; "
                # F7: explicit target_collection so install-time docs go to
                # nexe_documentation (corporate know-how), not user_knowledge.
                f"asyncio.run(ingest_knowledge(quiet=False, target_collection='nexe_documentation'))"
            ], check=True, capture_output=False, text=True, timeout=300, env=ingest_env)

            print(f"\n  {t('knowledge_indexed_ok')}")

            # Create marker to skip re-ingestion on first server startup
            marker_file = project_root / "storage" / ".knowledge_ingested"
            marker_file.touch()

        except subprocess.TimeoutExpired:
            print(f"  {YELLOW}⚠️  {t('ingest_timeout')}{RESET}")
        except Exception as e:
            print(f"  {YELLOW}⚠️  {t('ingest_error').format(error=str(e)[:200])}{RESET}")
            print(f"  {DIM}{t('ingest_auto_first_start')}{RESET}")
    else:
        print(f"  {DIM}📝 {t('no_knowledge_docs')}{RESET}")

    # 16. Final summary
    show_final_summary(model_config, project_root, global_symlink_created, lang)

    # Close install log
    print(f"\n  {DIM}📋 Install log: {log_path}{RESET}")
    tee.close()


def add_login_item(app_path: str = "/Applications/Nexe.app") -> bool:
    """Add Nexe to macOS login items via osascript (legacy, universal).

    Equivalent to the Swift doAddLoginItem() in CompletionView.swift.
    Returns True on success, False on failure.
    """
    script = (
        f'tell application "System Events" to make login item at end '
        f'with properties {{path:"{app_path}", hidden:true}}'
    )
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main():
    """Entry point with optional flags for headless / scripted use."""
    import argparse

    parser = argparse.ArgumentParser(description="Nexe installer")
    parser.add_argument(
        "--add-login-item",
        action="store_true",
        help="Add Nexe to macOS login items after installation (auto-start at login)",
    )
    parser.add_argument(
        "--app-path",
        default="/Applications/Nexe.app",
        help="Path to Nexe.app for the login item (default: /Applications/Nexe.app)",
    )
    args = parser.parse_args()

    run_installer()

    if args.add_login_item:
        ok = add_login_item(app_path=args.app_path)
        if ok:
            print(f"{GREEN}✅ Login item added: Nexe will start at login.{RESET}")
        else:
            print(f"{YELLOW}⚠️  Could not add login item. Add manually via System Settings → General → Login Items.{RESET}")


if __name__ == "__main__":
    main()
