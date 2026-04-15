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
    print_step, print_success, print_error,
)
from .installer_i18n import t


def _is_dmg_python(executable_path):
    """Detecta si l'executable Python ve d'un DMG montat (.app dins /Volumes/)."""
    return "/Volumes/" in executable_path and ".app/" in executable_path


def _find_python_bundle_root(executable_path):
    """Troba l'arrel del bundle Python (directori amb bin/ i lib/).

    Puja des de l'executable fins a trobar un directori que contingui
    tant bin/python3 com lib/libpython3.12.dylib.
    Retorna None si no és un bundle reconegut.
    """
    path = Path(executable_path).resolve()
    # L'executable sol ser a .../python/bin/python3
    # L'arrel del bundle és .../python/
    candidate = path.parent.parent  # bin/python3 -> python/
    if (candidate / "bin" / "python3").exists() and (candidate / "lib").exists():
        return candidate
    # Fallback: buscar cap amunt
    for parent in path.parents:
        if (parent / "bin" / "python3").exists() and (parent / "lib" / "libpython3.12.dylib").exists():
            return parent
    return None


def _copy_python_bundle(bundle_root, install_dir):
    """Copia el bundle Python complet al directori d'instal·lació.

    Crea install_dir/python_bundle/ amb bin/ i lib/ copiats.
    Retorna el path al python3 local.
    """
    import shutil

    dest = install_dir / "python_bundle"
    dest_python = dest / "bin" / "python3"

    # Si ja existeix, retorna directament
    if dest_python.exists():
        return str(dest_python)

    # Copiar bin/ i lib/
    dest_bin = dest / "bin"
    dest_lib = dest / "lib"

    if dest_bin.exists():
        shutil.rmtree(dest_bin)
    if dest_lib.exists():
        shutil.rmtree(dest_lib)

    shutil.copytree(str(bundle_root / "bin"), str(dest_bin), symlinks=False)
    shutil.copytree(str(bundle_root / "lib"), str(dest_lib), symlinks=False)

    # Assegurar permisos d'execució
    for f in dest_bin.iterdir():
        if f.is_file():
            f.chmod(f.stat().st_mode | 0o755)

    return str(dest_python)


def _get_python_for_venv(project_root):
    """Retorna el path al Python que s'ha d'usar per crear el venv.

    Si estem dins un DMG (sys.executable a /Volumes/*.app/), copia
    el bundle Python al directori d'instal·lació i retorna el Python local.
    Si no, retorna sys.executable directament.
    """
    if _is_dmg_python(sys.executable):
        bundle_root = _find_python_bundle_root(sys.executable)
        if bundle_root is not None:
            print(f"  📦 DMG detectat — copiant Python bundle a {project_root}/python_bundle/")
            local_python = _copy_python_bundle(bundle_root, project_root)
            return local_python
    return sys.executable


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


def _find_bundle_resources(project_root):
    """Retorna InstallNexe.app/Contents/Resources/ dins project_root si existeix.

    És el directori on build_dmg.sh posa els subdirectoris `wheels/` (Python
    wheels pre-descarregats) i `embeddings/` (model fastembed pre-descarregat)
    per a l'offline install. Retorna None si l'app bundle no hi és — el flow
    cau a online mode (PyPI + descàrrega a runtime), conservant el legacy.
    """
    candidate = project_root / "InstallNexe.app" / "Contents" / "Resources"
    if candidate.is_dir():
        return candidate
    return None


def _write_venv_pip_conf(venv_path, wheels_dir):
    """Escriu venv/pip.conf per forçar pip a usar nomÉs wheels locals.

    Efecte: totes les crides `pip install ...` posteriors dins el venv fan
    servir `--find-links=wheels_dir --no-index` implícit. Zero tocar PyPI,
    zero risc de compilació (no hi ha sdist a wheels_dir).

    Retorna True si s'ha configurat, False si wheels_dir no és usable
    (inexistent, no és dir, o està buit). En cas False, el caller cau a
    online mode sense tocar el pip.conf.
    """
    if wheels_dir is None or not wheels_dir.is_dir():
        return False
    if not any(wheels_dir.glob("*.whl")):
        return False
    pip_conf = venv_path / "pip.conf"
    pip_conf.write_text(
        "[global]\n"
        f"find-links = {wheels_dir}\n"
        "no-index = true\n",
        encoding="utf-8",
    )
    return True


def _seed_fastembed_cache(bundle_embeddings_dir, cache_dir):
    """Copia el bundle de fastembed al cache natiu de l'usuari.

    Així, el primer `TextEmbedding(model_name)` que fa l'installer (via
    `install.py`) troba el model ja present i no descarrega res de HuggingFace.
    RAG funciona offline des del primer boot.

    Retorna True si s'ha sembrat, False si el bundle no és usable (inexistent,
    no és dir, o està buit). Idempotent: es pot cridar múltiples vegades.
    """
    import shutil as _shutil

    if bundle_embeddings_dir is None or not bundle_embeddings_dir.is_dir():
        return False
    if not any(bundle_embeddings_dir.iterdir()):
        return False
    cache_dir.mkdir(parents=True, exist_ok=True)
    _shutil.copytree(
        str(bundle_embeddings_dir),
        str(cache_dir),
        dirs_exist_ok=True,
    )
    return True


def _default_fastembed_cache_dir():
    """Ubicació del cache de fastembed per a l'usuari actual.

    Respecta FASTEMBED_CACHE_DIR si està exportada (usada pel wizard al
    dev Mac per redirigir el cache). Cau a `~/.cache/fastembed/` que és
    la convenció cross-platform de fastembed.
    """
    env_override = os.environ.get("FASTEMBED_CACHE_DIR")
    if env_override:
        return Path(env_override).expanduser()
    return Path.home() / ".cache" / "fastembed"


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
            python_for_venv = _get_python_for_venv(project_root)
            subprocess.run(
                [python_for_venv, "-m", "venv", "--copies", "--without-pip", "venv"],
                check=True, capture_output=True,
            )
            _make_venv_standalone(venv_path)
            # Ara el Python del venv funciona — instal·lar pip
            venv_python = str(venv_path / "bin" / "python3")
            subprocess.run([venv_python, "-m", "ensurepip", "--upgrade"], check=True, capture_output=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", "venv"], check=True, capture_output=True)

    # Path to pip/python based on OS
    if os.name == 'nt':
        pip_path = venv_path / "Scripts" / "pip.exe"
        python_path = venv_path / "Scripts" / "python.exe"
    else:
        pip_path = venv_path / "bin" / "pip3"
        python_path = venv_path / "bin" / "python3"

    # Offline install: if the DMG bundle shipped wheels + embedding model,
    # wire them in now. If the bundle is absent (e.g. running from a git
    # checkout), everything below falls back to PyPI + HuggingFace at runtime
    # (legacy behaviour preserved).
    bundle_resources = _find_bundle_resources(project_root)
    if bundle_resources is not None:
        wheels_dir = bundle_resources / "wheels"
        if _write_venv_pip_conf(venv_path, wheels_dir):
            print(f"  📦 Offline install: wheels locals ({wheels_dir})")
        embeddings_dir = bundle_resources / "embeddings"
        if _seed_fastembed_cache(embeddings_dir, _default_fastembed_cache_dir()):
            print("  📦 Embedding model disponible offline")

    # 1. Upgrade pip
    subprocess.run([str(pip_path), "install", "--upgrade", "pip"], capture_output=True)

    # 2. Install core requirements
    req_file = project_root / "requirements.txt"
    if req_file.exists():
        print(f"  📥 {t('installing_deps')}")
        subprocess.run([str(pip_path), "install", "-r", str(req_file)], check=True, capture_output=True)
    else:
        print_error(t('requirements_not_found'))
        sys.exit(1)

    # 2b. Install macOS-only deps (rumps/tray) on Darwin
    if platform.system() == "Darwin":
        req_macos = project_root / "requirements-macos.txt"
        if req_macos.exists():
            subprocess.run([str(pip_path), "install", "-r", str(req_macos)], check=True, capture_output=True)

    # 3. Hardware-Specific Inference Engines
    print_step(f"{BOLD}{t('installing_inference')}{RESET}")

    if hw['is_apple_silicon']:
        print(f"   {t('detected_apple')} {CYAN}mlx-lm{RESET} + {CYAN}mlx-vlm{RESET}...")
        print(f"   {DIM}{t('mlx_dep_warning_title')} {t('mlx_dep_warning_body')}{RESET}")
        # mlx-lm 0.31.2: suport qwen3_5 + compatible mlx-vlm 0.4.4.
        subprocess.run([str(pip_path), "install", "mlx-lm==0.31.2"], check=True, capture_output=True)
        # mlx-vlm 0.4.4: suport ampli VLM (gemma4, qwen3_5_moe, qwen3_vl, llava,
        # paligemma, internvl, …). Retorna GenerationResult i exigeix image=path.
        # Arrossega numpy 2.x — verificat zero regressions a full suite.
        subprocess.run([str(pip_path), "install", "mlx-vlm==0.4.4"], check=True, capture_output=True)

    # Install llama-cpp-python always so users can switch engines from the UI
    # (Motor dropdown). The arm64 macOS wheel published on PyPI (and the one
    # bundled in offline mode) already ships with Metal enabled, so no
    # source build and no Xcode Command Line Tools are required.
    print(f"  🏗️ {t('installing_universal')} {CYAN}llama-cpp-python{RESET}...")
    subprocess.run(
        [str(pip_path), "install", "llama-cpp-python"],
        check=True,
        capture_output=True,
    )
    print_success(f"llama-cpp-python {t('installed_gpu')}")

    return python_path
