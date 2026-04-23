"""
────────────────────────────────────
Server Nexe
Location: installer/installer_setup_models.py
Description: Model downloads (Ollama / GGUF / MLX) with post-download
             SHA256 verification (F4.1 audit DoD-AUD-SX-0423 §2.7).

Ollama runtime installation (app bundle + install script) moved to
``installer.installer_ollama_install`` on 2026-04-23. ``ensure_ollama_installed``
is re-exported from here for backwards compatibility with the existing
``install_headless.py`` / ``install.py`` imports.
────────────────────────────────────
"""

import os
import sys
import subprocess
from pathlib import Path

from .download_verify import DownloadIntegrityError, verify_download_integrity
from .installer_display import (
    APP_LOGO, clear,
    GREEN, RED, YELLOW, CYAN, BOLD, DIM, RESET,
    print_success, print_warn,
)
from .installer_i18n import t
from .installer_ollama_install import (  # re-exported — see docstring
    _find_ollama,
    ensure_ollama_installed,
)

__all__ = [
    "ensure_ollama_installed",
    "_download_ollama_model",
    "_download_gguf_model",
    "_download_mlx_model",
]


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
        print(f"{t('download_gguf_instructions')}")
        print(f"  {CYAN}curl -L -o storage/models/{model['id'].split('/')[-1]} {model['id']}{RESET}\n")
    else:
        print(f"{t('to_download_mlx')}")
        print(f"  {CYAN}python -c \"from mlx_lm import load; load('{model['id']}')\" {RESET}\n")

    print(f"{t('after_download')}")
    print(f"  {CYAN}./nexe chat{RESET}\n")

    print(f"{DIM}💡 {t('manual_install_note')}{RESET}")


def _download_ollama_model(model_config, headless=False):
    """Download Ollama model immediately after selection."""
    clear()
    print(APP_LOGO)

    model_id = model_config['id']
    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   Model: {CYAN}{model_config['name']}{RESET}")
    print(f"   Ollama ID: {CYAN}{model_id}{RESET}")
    print(f"   {t('engine_ollama_label')}")
    print()

    if headless:
        choice = "1"  # Always download in headless mode
    else:
        print(f"{BOLD}{t('download_options')}{RESET}\n")
        print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
        print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
        print()

        try:
            choice = input(f"{BOLD}[1/2]:{RESET} ").strip()
        except (EOFError, OSError):
            choice = "1"  # Default to download if no stdin

    if choice == "1":
        try:
            ollama_bin = _find_ollama()
            print(f"\n{CYAN}[1/3]{RESET} {t('ollama_checking')}")
            result = subprocess.run([ollama_bin, "list"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"{YELLOW}[...]{RESET} {t('starting_ollama')}")
                subprocess.Popen([ollama_bin, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # Wait for Ollama to be ready (max 15s)
                import time
                import socket
                for _ in range(30):
                    try:
                        with socket.create_connection(("localhost", 11434), timeout=0.5):
                            break
                    except (ConnectionRefusedError, OSError):
                        time.sleep(0.5)
                else:
                    print(f"{YELLOW}[WARN]{RESET} Ollama may not be ready yet")

            print(f"\n{CYAN}[2/3]{RESET} {t('downloading_model_progress')}")
            print(f"      {DIM}{ollama_bin} pull {model_id}{RESET}\n")

            process = subprocess.Popen(
                [ollama_bin, "pull", model_id],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            return_code = process.wait()

            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, "ollama pull")

            print(f"\n{CYAN}[3/4]{RESET} {t('verifying_download')}")
            result = subprocess.run([ollama_bin, "list"], capture_output=True, text=True)
            model_base = model_id.split(":")[0]
            if model_base in result.stdout or model_id in result.stdout:
                # F4.1 (audit DoD-AUD-SX-0423 §2.7): compare the manifest
                # digest reported by Ollama against the catalog pin. On
                # mismatch the call raises DownloadIntegrityError, which
                # bubbles up to the caller (CLI exits non-zero, GUI marks
                # step 3 as error). Legacy entries (expected=None) return
                # False here and we surface a not-pinned notice.
                try:
                    matched = verify_download_integrity(
                        "ollama", model_id, Path("."),
                        ollama_bin=ollama_bin,
                    )
                except DownloadIntegrityError as exc:
                    print_warn(f"✗ Integrity check failed for {model_id}")
                    print(str(exc))
                    raise
                if matched:
                    print_success(t('model_downloaded_ok').format(id=model_id))
                else:
                    print(f"{YELLOW}⚠️  {model_id}: SHA256 not pinned in catalog "
                          f"— install proceeded without integrity check{RESET}")
                    print_success(t('model_downloaded_ok').format(id=model_id))
            else:
                print_warn(t('model_not_in_list'))
                print(f"  {DIM}{t('run_ollama_list')}{RESET}")

            print(f"\n{CYAN}[4/4]{RESET} {t('downloading_embeddings_step')}")
            print(f"      {DIM}{ollama_bin} pull nomic-embed-text{RESET}\n")

            embed_process = subprocess.Popen(
                [ollama_bin, "pull", "nomic-embed-text"],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            embed_return = embed_process.wait()

            if embed_return == 0:
                print_success(t('embeddings_downloaded'))
            else:
                print_warn(t('embeddings_failed'))
                print(f"  {DIM}{t('embeddings_manual')}{RESET}")

        except subprocess.CalledProcessError as e:
            print_warn(f"{t('download_failed')} (code: {e.returncode})")
            if headless:
                raise
            _show_manual_instructions(model_config, "ollama")
        except FileNotFoundError:
            print_warn(t('ollama_not_found'))
            if headless:
                raise
            _show_manual_instructions(model_config, "ollama")
    else:
        _show_manual_instructions(model_config, "ollama")
        print(f"\n{YELLOW}⚠️  Model {model_id} NOT downloaded. Before starting nexe, run:{RESET}")
        print(f"  {CYAN}ollama pull {model_id}{RESET}")
        print(f"  {CYAN}ollama pull nomic-embed-text{RESET}")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    if not headless:
        try:
            input(f"\n{DIM}[{t('press_enter')}]{RESET}")
        except (EOFError, OSError):
            pass


def _download_gguf_model(model_config, project_root, headless=False):
    """Download GGUF model immediately after selection."""
    clear()
    print(APP_LOGO)

    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   Model: {CYAN}{model_config['name']}{RESET}")
    print(f"   {t('engine_gguf_label')}")
    print()

    if headless:
        choice = "1"  # Always download in headless mode
    else:
        print(f"{BOLD}{t('download_options')}{RESET}\n")
        print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
        print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
        print()

        try:
            choice = input(f"{BOLD}[1/2]:{RESET} ").strip()
        except (EOFError, OSError):
            choice = "1"  # Default to download if no stdin

    if choice == "1":
        try:
            models_dir = project_root / "storage" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            filename = model_config['id'].split('/')[-1]
            output_path = models_dir / filename

            print(f"\n{CYAN}[...]{RESET} {t('downloading_file').format(filename=filename)}")
            print(f"   {DIM}{model_config['id']}{RESET}")

            subprocess.run([
                "curl", "-L", "--progress-bar",
                "-o", str(output_path),
                model_config['id']
            ], check=True)

            # Verify file was actually downloaded and has content
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(f"Downloaded file is empty or missing: {output_path}")

            # F4.1 (audit DoD-AUD-SX-0423 §2.7): SHA256 integrity check.
            try:
                matched = verify_download_integrity(
                    "gguf", model_config['id'], output_path,
                )
            except DownloadIntegrityError as exc:
                print_warn(f"✗ Integrity check failed for {filename}")
                print(str(exc))
                raise
            if not matched:
                print(f"{YELLOW}⚠️  {filename}: SHA256 not pinned in catalog "
                      f"— install proceeded without integrity check{RESET}")

            print_success(t('download_success'))
            print(f"  📁 {output_path}")
        except DownloadIntegrityError:
            # Already printed as "✗ Integrity check failed …" above.
            # Propagate unconditionally (interactive and headless alike).
            # A SHA256 mismatch is never a "try these manual commands"
            # situation — the file is still on disk, the pin is wrong, or
            # the download is poisoned. Downgrading to _show_manual_instructions
            # would turn a security control into a warning the user can click
            # past, which defeats the entire point of F4.1.
            raise
        except subprocess.CalledProcessError:
            print_warn(t('download_failed'))
            if headless:
                raise
            _show_manual_instructions(model_config, "llama_cpp")
        except Exception as e:
            print_warn(f"{t('download_failed')}: {e}")
            if headless:
                raise
            _show_manual_instructions(model_config, "llama_cpp")
    else:
        _show_manual_instructions(model_config, "llama_cpp")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    if not headless:
        try:
            input(f"\n{DIM}[{t('press_enter')}]{RESET}")
        except (EOFError, OSError):
            pass


def _download_mlx_model(model_config, project_root, python_path, headless=False):
    """Download MLX model immediately after selection."""
    clear()
    print(APP_LOGO)

    model_id = model_config['id']
    model_name = model_id.split('/')[-1]

    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   Model: {CYAN}{model_config['name']}{RESET}")
    print(f"   HuggingFace ID: {CYAN}{model_id}{RESET}")
    print(f"   {t('engine_mlx_label')}")
    print()

    if headless:
        choice = "1"  # Always download in headless mode
    else:
        print(f"{BOLD}{t('download_options')}{RESET}\n")
        print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
        print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
        print()

        try:
            choice = input(f"{BOLD}[1/2]:{RESET} ").strip()
        except (EOFError, OSError):
            choice = "1"  # Default to download if no stdin

    if choice == "1":
        try:
            models_dir = project_root / "storage" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            local_model_path = models_dir / model_name

            if local_model_path.exists() and any(local_model_path.iterdir()):
                print(f"{GREEN}[OK]{RESET} {t('model_already_downloaded').format(path=local_model_path)}")
                if not headless:
                    try:
                        input(f"\n{DIM}[{t('press_enter')}]{RESET}")
                    except (EOFError, OSError):
                        pass
                return

            if not headless:
                clear()
                print(APP_LOGO)
                print(f"\n{RED}{BOLD}{t('download_warning_title').format(size=model_config['disk_size'])}{RESET}\n")
                print(f"  {YELLOW}1.{RESET} {t('download_warning_power')}")
                print(f"  {YELLOW}2.{RESET} {t('download_warning_sleep')}")
                print(f"  {YELLOW}3.{RESET} {t('download_warning_wifi')}")
                print(f"\n  {DIM}• {t('download_warning_time')}{RESET}")
                print(f"  {DIM}• {t('download_warning_resume')}{RESET}\n")

                try:
                    input(f"{GREEN}▶ {t('download_ready')} [Enter]:{RESET} ")
                except (EOFError, OSError):
                    pass

            print(f"\n{CYAN}[1/2]{RESET} {t('downloading_mlx_step')}")
            print(f"      {DIM}{t('mlx_destination').format(path=local_model_path)}{RESET}\n")

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
        print("Download complete!")
        break
    except Exception as e:
        if attempt < max_retries - 1:
            print(f"Download interrupted, retrying in 5 seconds... (attempt {{attempt+1}}/{{max_retries}})")
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
                print_success(t('mlx_downloaded_ok').format(path=local_model_path))

                print(f"\n{CYAN}[2/3]{RESET} {t('mlx_validating')}")
                config_file = local_model_path / "config.json"
                if not config_file.exists():
                    print_warn(t('mlx_config_missing').format(path=local_model_path))
                    print(f"{DIM}{t('mlx_may_have_issues')}{RESET}")
                else:
                    print(f"{GREEN}✓{RESET} {t('mlx_validated_ok')}")

                # F4.1 (audit DoD-AUD-SX-0423 §2.7): SHA256 check of the
                # whole snapshot dir against the catalog pin. Legacy
                # entries (expected=None) surface a not-pinned notice.
                print(f"\n{CYAN}[3/3]{RESET} Integrity verification (SHA256)")
                try:
                    matched = verify_download_integrity(
                        "mlx", model_id, local_model_path,
                    )
                except DownloadIntegrityError as exc:
                    print_warn(f"✗ Integrity check failed for {model_id}")
                    print(str(exc))
                    raise
                if matched:
                    print(f"{GREEN}✓{RESET} SHA256 pin verified")
                else:
                    print(f"{YELLOW}⚠️  {model_id}: SHA256 not pinned in catalog "
                          f"— install proceeded without integrity check{RESET}")
            else:
                raise subprocess.CalledProcessError(return_code, "mlx_download")

        except DownloadIntegrityError:
            # Already printed as "✗ Integrity check failed …" above.
            # Propagate without wrapping it in the generic "download
            # interrupted, resume later" banner — that message is for
            # network / IO failures, not for an integrity mismatch, and
            # showing both at once confuses the user.
            raise
        except Exception as e:
            print(f"\n{YELLOW}{t('download_failed_resume')}{RESET}")
            print(f"{DIM}Error: {str(e)[:200]}{RESET}")
            print(f"{DIM}{t('partial_files_preserved')}{RESET}\n")
            if headless:
                raise
            _show_manual_instructions(model_config, "mlx")
    else:
        _show_manual_instructions(model_config, "mlx")
        print(f"\n{YELLOW}{t('mlx_no_model_warning')}{RESET}")
        print(f"   {t('mlx_fallback_ollama')}")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    if not headless:
        try:
            input(f"\n{DIM}[{t('press_enter')}]{RESET}")
        except (EOFError, OSError):
            pass
