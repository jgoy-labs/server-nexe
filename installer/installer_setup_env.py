"""
────────────────────────────────────
Server Nexe
Location: installer/installer_setup_env.py
Description: Virtual environment setup and inference engine installation.
────────────────────────────────────
"""

import os
import sys
import subprocess
from pathlib import Path

from .installer_display import (
    CYAN, BOLD, DIM, RESET,
    print_step, print_success, print_warn, print_error,
)
from .installer_i18n import t


def setup_environment(project_root, hw, engine="auto"):
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
