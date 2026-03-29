"""
────────────────────────────────────
Server Nexe
Location: installer/installer_setup_env.py
Description: Virtual environment setup and inference engine installation.
────────────────────────────────────
"""

import os
import platform
import sys
import subprocess
from pathlib import Path

from .installer_display import (
    CYAN, BOLD, DIM, RESET,
    print_step, print_success, print_warn, print_error,
)
from .installer_i18n import t


def _make_venv_standalone(venv_path):
    """Fer el venv autònom del DMG/app bundle.

    Quan el venv es crea amb --copies des del Python bundled:
    1. Copia libpython3.12.dylib perque @executable_path el trobi
    2. Re-signa ad-hoc el Python del venv (treu hardened runtime)
       perque pugui carregar .so instal·lats per pip (PyObjC, etc.)
    """
    import shutil

    # Copiar libpython al venv perque el binari copiat la trobi
    bundled_lib = Path(sys.executable).parent.parent / "lib" / "libpython3.12.dylib"
    venv_lib_dir = venv_path / "lib"
    venv_lib = venv_lib_dir / "libpython3.12.dylib"
    if bundled_lib.exists() and not venv_lib.exists():
        shutil.copy2(str(bundled_lib), str(venv_lib))

    # Re-signar ad-hoc (sense hardened runtime) perque pip .so funcioni
    # + treure quarantine (AirDrop/Safari afegeixen com.apple.quarantine)
    for name in ("python3.12", "python3", "python"):
        venv_bin = venv_path / "bin" / name
        if venv_bin.exists() and not venv_bin.is_symlink():
            subprocess.run(
                ["codesign", "--force", "--sign", "-", str(venv_bin)],
                capture_output=True,
            )
            subprocess.run(
                ["xattr", "-rd", "com.apple.quarantine", str(venv_bin)],
                capture_output=True,
            )

    # Treure quarantine de libpython copiat
    if venv_lib.exists():
        subprocess.run(
            ["xattr", "-rd", "com.apple.quarantine", str(venv_lib)],
            capture_output=True,
        )


def setup_environment(project_root, hw, engine="auto"):
    print_step(f"{BOLD}{t('setting_up_env')}{RESET}")

    import shutil as _shutil

    venv_path = project_root / "venv"

    # Si el venv existeix però està trencat (pip3 no hi és), esborrar i recrear
    if venv_path.exists():
        pip3 = venv_path / "bin" / "pip3"
        if not pip3.exists():
            print(f"  ⚠️  Venv trencat detectat, recreant...")
            _shutil.rmtree(venv_path)

    if not venv_path.exists():
        print(f"  📦 {t('creating_venv')}")
        if platform.system() == "Darwin":
            # macOS: --copies --without-pip per evitar SIGABRT del binari copiat
            # (necessita libpython copiada ABANS de poder executar ensurepip)
            subprocess.run(
                [sys.executable, "-m", "venv", "--copies", "--without-pip", "venv"],
                check=True,
            )
            _make_venv_standalone(venv_path)
            # Ara el Python del venv funciona — instal·lar pip
            venv_python = str(venv_path / "bin" / "python3")
            subprocess.run([venv_python, "-m", "ensurepip", "--upgrade"], check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)

    # Path to pip/python based on OS
    if os.name == 'nt':
        pip_path = venv_path / "Scripts" / "pip.exe"
        python_path = venv_path / "Scripts" / "python.exe"
    else:
        pip_path = venv_path / "bin" / "pip3"
        python_path = venv_path / "bin" / "python3"

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

    # 2b. Install macOS-only deps (rumps/tray) on Darwin
    if platform.system() == "Darwin":
        req_macos = project_root / "requirements-macos.txt"
        if req_macos.exists():
            subprocess.run([str(pip_path), "install", "-r", str(req_macos)], check=True)

    # 3. Hardware-Specific Inference Engines
    print_step(f"{BOLD}{t('installing_inference')}{RESET}")

    if hw['is_apple_silicon']:
        print(f"   {t('detected_apple')} {CYAN}mlx-lm{RESET}...")
        print(f"   {DIM}{t('mlx_dep_warning_title')} {t('mlx_dep_warning_body')}{RESET}")
        # Pin to 0.30.7: first version with qwen3_5 architecture support.
        # Note: requires transformers>=5.0.0 which conflicts with sentence-transformers
        # metadata, but works correctly at runtime.
        subprocess.run([str(pip_path), "install", "mlx-lm==0.30.7"], check=True)

    if engine in ("llama_cpp", "all"):
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
