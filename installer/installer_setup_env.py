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
    print_step, print_success, print_error, print_warn,
)
from .installer_i18n import t


def _is_dmg_python(executable_path):
    """Detect whether the Python executable comes from a mounted DMG (.app inside /Volumes/)."""
    return "/Volumes/" in executable_path and ".app/" in executable_path


def _find_python_bundle_root(executable_path):
    """Find the root of the Python bundle (directory with bin/ and lib/).

    Walk up from the executable until finding a directory that contains
    both bin/python3 and lib/libpython3.12.dylib.
    Returns None if it is not a recognised bundle.
    """
    path = Path(executable_path).resolve()
    # The executable is usually at .../python/bin/python3
    # The bundle root is .../python/
    candidate = path.parent.parent  # bin/python3 -> python/
    if (candidate / "bin" / "python3").exists() and (candidate / "lib").exists():
        return candidate
    # Fallback: search upward
    for parent in path.parents:
        if (parent / "bin" / "python3").exists() and (parent / "lib" / "libpython3.12.dylib").exists():
            return parent
    return None


def _copy_python_bundle(bundle_root, install_dir):
    """Copy the full Python bundle to the installation directory.

    Creates install_dir/python_bundle/ with bin/ and lib/ copied.
    Returns the path to the local python3.
    """
    import shutil

    dest = install_dir / "python_bundle"
    dest_python = dest / "bin" / "python3"

    # If already exists, return directly
    if dest_python.exists():
        return str(dest_python)

    # Copy bin/ and lib/
    dest_bin = dest / "bin"
    dest_lib = dest / "lib"

    if dest_bin.exists():
        shutil.rmtree(dest_bin)
    if dest_lib.exists():
        shutil.rmtree(dest_lib)

    shutil.copytree(str(bundle_root / "bin"), str(dest_bin), symlinks=False)
    shutil.copytree(str(bundle_root / "lib"), str(dest_lib), symlinks=False)

    # Ensure execute permissions
    for f in dest_bin.iterdir():
        if f.is_file():
            f.chmod(f.stat().st_mode | 0o755)

    return str(dest_python)


def _get_python_for_venv(project_root):
    """Return the Python path to use for creating the venv.

    If running inside a DMG (sys.executable in /Volumes/*.app/), copy
    the Python bundle to the installation directory and return the local
    Python. Otherwise return sys.executable directly.
    """
    if _is_dmg_python(sys.executable):
        bundle_root = _find_python_bundle_root(sys.executable)
        if bundle_root is not None:
            print(f"  📦 DMG detected — copying Python bundle to {project_root}/python_bundle/")
            local_python = _copy_python_bundle(bundle_root, project_root)
            return local_python
    return sys.executable


def _make_venv_standalone(venv_path):
    """Make the venv independent of the DMG/app bundle.

    When the venv is created with --copies from the bundled Python:
    1. Copy libpython3.12.dylib so @executable_path can find it
    2. Ad-hoc re-sign the venv Python (remove hardened runtime)
       so it can load .so files installed by pip (PyObjC, etc.)
    """
    import shutil

    # Copy libpython into the venv so the copied binary can find it
    bundled_lib = Path(sys.executable).parent.parent / "lib" / "libpython3.12.dylib"
    venv_lib_dir = venv_path / "lib"
    venv_lib = venv_lib_dir / "libpython3.12.dylib"
    if bundled_lib.exists() and not venv_lib.exists():
        shutil.copy2(str(bundled_lib), str(venv_lib))

    # Ad-hoc re-sign (without hardened runtime) so pip .so files work
    # + strip quarantine (AirDrop/Safari add com.apple.quarantine)
    for name in ("python3.12", "python3", "python"):
        venv_bin = venv_path / "bin" / name
        if venv_bin.exists() and not venv_bin.is_symlink():
            subprocess.run(  # nosec B603 B607: venv_bin is project_root-derived Path; codesign via PATH (macOS-only, ad-hoc sign of venv python)
                ["codesign", "--force", "--sign", "-", str(venv_bin)],
                capture_output=True,
            )
            subprocess.run(  # nosec B603 B607: venv_bin is project_root-derived Path; xattr via PATH (strip quarantine)
                ["xattr", "-rd", "com.apple.quarantine", str(venv_bin)],
                capture_output=True,
            )

    # Strip quarantine from the copied libpython
    if venv_lib.exists():
        subprocess.run(  # nosec B603 B607: venv_lib is project_root-derived Path; xattr via PATH
            ["xattr", "-rd", "com.apple.quarantine", str(venv_lib)],
            capture_output=True,
        )


def _find_bundle_resources(project_root):
    """Locate InstallNexe.app/Contents/Resources/ with wheels/ and embeddings/.

    Search order:
    1. NEXE_BUNDLE_RESOURCES env var (set explicitly by the caller).
    2. project_root/InstallNexe.app/... (development layout, co-located).
    3. Mounted volumes (/Volumes/*/InstallNexe.app/...) — real DMG case: the
       SwiftUI wizard runs from the mounted DMG, extracts the payload to
       project_root (/Applications/server-nexe/), but the app bundle with
       the wheels stays on the DMG volume. Without this fallback pip.conf
       is not written and pip falls back to PyPI (where llama-cpp-python
       only has an sdist → compilation → CLT prompt on a fresh M1).

    Returns None if no candidate has wheels/ → the flow falls back to online mode.
    """
    # 1. Explicit env var (allows SwiftUI wizard or tests to override)
    env_path = os.environ.get("NEXE_BUNDLE_RESOURCES")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_dir() and (candidate / "wheels").is_dir():
            return candidate

    # 2. Co-located with project (development layout)
    candidate = project_root / "InstallNexe.app" / "Contents" / "Resources"
    if candidate.is_dir() and (candidate / "wheels").is_dir():
        return candidate

    # 3. Mounted DMG volume (client install)
    volumes = Path("/Volumes")
    if volumes.is_dir():
        try:
            for vol in volumes.iterdir():
                candidate = vol / "InstallNexe.app" / "Contents" / "Resources"
                if candidate.is_dir() and (candidate / "wheels").is_dir():
                    return candidate
        except PermissionError:
            pass  # Some volumes may not be readable

    return None


def _write_venv_pip_conf(venv_path, wheels_dir):
    """Write venv/pip.conf to force pip to use ONLY local wheels.

    Effect: all subsequent `pip install ...` calls inside the venv implicitly
    use `--find-links=wheels_dir --no-index`. Zero PyPI contact, zero
    compilation risk (no sdist in wheels_dir).

    Returns True if configured, False if wheels_dir is not usable
    (non-existent, not a dir, or empty). On False the caller falls back to
    online mode without touching pip.conf.
    """
    if wheels_dir is None or not wheels_dir.is_dir():
        return False
    if not any(wheels_dir.glob("*.whl")):
        return False
    pip_conf = venv_path / "pip.conf"
    # Use file:// URI so paths with spaces (e.g. "/Volumes/Install Nexe/...")
    # are not split by pip's config parser. Path.as_uri() percent-encodes
    # spaces as %20.
    wheels_uri = wheels_dir.resolve().as_uri()
    pip_conf.write_text(
        "[global]\n"
        f"find-links = {wheels_uri}\n"
        "no-index = true\n",
        encoding="utf-8",
    )
    return True


def _seed_fastembed_cache(bundle_embeddings_dir, cache_dir):
    """Copy the fastembed bundle into the user's native cache.

    This way the first `TextEmbedding(model_name)` call made by the
    installer (via `install.py`) finds the model already present and
    downloads nothing from HuggingFace. RAG works offline from the first
    boot.

    SHA256 weight pinning (internal security review AUD-INT-001 §2.7): before copying, validate the bundle's
    integrity manifest (``embeddings.manifest.json``). On mismatch,
    ``DownloadIntegrityError`` propagates so the installer aborts before
    poisoning the user's fastembed cache. Legacy DMGs
    do not ship a manifest — the verifier logs a WARNING and we copy the
    bundle as-is to stay compatible with existing 1.0.2-beta installs.

    Returns True if seeded, False if the bundle is not usable (non-existent,
    not a dir, or empty). Idempotent: can be called multiple times.
    """
    import shutil as _shutil

    if bundle_embeddings_dir is None or not bundle_embeddings_dir.is_dir():
        return False
    if not any(bundle_embeddings_dir.iterdir()):
        return False

    from installer.download_verify import verify_embedding_bundle
    # The verifier returns True (pin matches), False (legacy DMG without
    # manifest), or raises DownloadIntegrityError (tampered bundle). We
    # surface the False case to stdout so the operator sees the gap
    # instead of having it buried in a logger-only warning.
    pinned = verify_embedding_bundle(bundle_embeddings_dir)
    if not pinned:
        print("  ⚠️  Embedding bundle: no SHA256 manifest "
              "(legacy DMG) — proceeding without integrity enforcement")

    cache_dir.mkdir(parents=True, exist_ok=True)
    _shutil.copytree(
        str(bundle_embeddings_dir),
        str(cache_dir),
        dirs_exist_ok=True,
    )
    return True


def _default_fastembed_cache_dir():
    """Location of the fastembed cache for the current user.

    Inlined here to avoid importing memory.embeddings.paths at installer
    time — that module triggers memory/embeddings/__init__.py → module.py
    → structlog, which is not installed yet when this runs (pre-pip-install).
    Logic mirrors memory.embeddings.paths.default_fastembed_cache_dir exactly.
    """
    env_override = os.environ.get("FASTEMBED_CACHE_DIR")
    if env_override:
        return Path(env_override).expanduser()
    return Path.home() / ".cache" / "fastembed"


# ═══════════════════════════════════════════════════════════════════════════
# FAÇADE HELPERS — each absorbs one logical block of setup_environment
# ═══════════════════════════════════════════════════════════════════════════

def _ensure_venv(project_root, venv_path):
    """Create the venv if absent; recreate if broken (pip3 missing)."""
    import shutil as _shutil

    if venv_path.exists():
        pip3 = venv_path / "bin" / "pip3"
        if not pip3.exists():
            print("  ⚠️  Broken venv detected, recreating...")
            _shutil.rmtree(venv_path)

    if not venv_path.exists():
        print(f"  📦 {t('creating_venv')}")
        if platform.system() == "Darwin":
            # macOS: --copies --without-pip to avoid SIGABRT from the copied binary
            # (it needs libpython copied BEFORE ensurepip can be executed)
            python_for_venv = _get_python_for_venv(project_root)
            subprocess.run(  # nosec B603: python_for_venv from _get_python_for_venv (sys.executable or bundled Python copy); literal venv module args
                [python_for_venv, "-m", "venv", "--copies", "--without-pip", "venv"],
                check=True, capture_output=True,
            )
            _make_venv_standalone(venv_path)
            # Now the venv Python works — install pip
            venv_python = str(venv_path / "bin" / "python3")
            subprocess.run([venv_python, "-m", "ensurepip", "--upgrade"], check=True, capture_output=True)  # nosec B603: venv_python is venv_path-derived absolute Path; literal ensurepip args
        else:
            subprocess.run([sys.executable, "-m", "venv", "venv"], check=True, capture_output=True)  # nosec B603: sys.executable + literal venv module args


def _setup_offline_bundle(project_root, venv_path):
    """Wire in wheels + embeddings from the DMG bundle if present.

    pip.conf with no-index=true is written AFTER pip upgrade so the upgrade
    itself is not blocked. If the bundle is absent (e.g. git checkout),
    falls back to PyPI + HuggingFace at runtime (legacy behaviour preserved).
    """
    bundle_resources = _find_bundle_resources(project_root)
    if bundle_resources is not None:
        wheels_dir = bundle_resources / "wheels"
        if _write_venv_pip_conf(venv_path, wheels_dir):
            print(f"  📦 Offline install: wheels locals ({wheels_dir})")
        embeddings_dir = bundle_resources / "embeddings"
        if _seed_fastembed_cache(embeddings_dir, _default_fastembed_cache_dir()):
            print("  📦 Embedding model available offline")


def _install_requirements(pip_path, req_file, venv_path):
    """Install requirements.txt with offline→PyPI fallback on failure."""
    if not req_file.exists():
        print_error(t('requirements_not_found'))
        sys.exit(1)

    print(f"  📥 {t('installing_deps')}")
    pip_conf_path = venv_path / "pip.conf"
    try:
        subprocess.run([str(pip_path), "install", "-r", str(req_file)], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; req_file is project_root/requirements.txt
    except subprocess.CalledProcessError as e:
        if pip_conf_path.exists():
            # Offline install failed — a wheel is probably missing from
            # the bundle. Show what pip complained about, remove pip.conf
            # (which had no-index=true), and retry with PyPI as fallback.
            print("  ⚠️ Offline install incomplete — falling back to PyPI...")
            if e.stderr:
                for line in e.stderr.decode("utf-8", errors="replace").splitlines()[-10:]:
                    print(f"     {line}")
            print_warn(
                "Supply-chain guarantee lost: no-index removed, installing "
                "from PyPI without hash pins. Verify installed packages manually."
            )
            pip_conf_path.unlink()
            subprocess.run([str(pip_path), "install", "-r", str(req_file)], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; req_file is project_root/requirements.txt (PyPI fallback)
            print("  ✅ Fallback to PyPI succeeded")
        else:
            # No pip.conf means we were already in online mode — real failure.
            print(f"  ❌ pip install -r requirements.txt failed (exit {e.returncode}):")
            if e.stderr:
                for line in e.stderr.decode("utf-8", errors="replace").splitlines()[-20:]:
                    print(f"     {line}")
            raise


def _install_macos_deps(pip_path, project_root, venv_path):
    """Install macOS-only deps (rumps/tray) with offline→PyPI fallback."""
    req_macos = project_root / "requirements-macos.txt"
    if not req_macos.exists():
        return
    pip_conf_path = venv_path / "pip.conf"
    try:
        subprocess.run([str(pip_path), "install", "-r", str(req_macos)], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; req_macos is project_root/requirements-macos.txt
    except subprocess.CalledProcessError as e:
        if pip_conf_path.exists():
            print("  ⚠️ Offline install incomplete (macOS deps) — falling back to PyPI...")
            if e.stderr:
                for line in e.stderr.decode("utf-8", errors="replace").splitlines()[-5:]:
                    print(f"     {line}")
            print_warn(
                "Supply-chain guarantee lost: no-index removed for macOS deps, "
                "installing from PyPI without hash pins."
            )
            pip_conf_path.unlink(missing_ok=True)
            subprocess.run([str(pip_path), "install", "-r", str(req_macos)], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; req_macos is project_root/requirements-macos.txt (PyPI fallback)
        else:
            raise


def _install_linux_deps(pip_path, project_root, venv_path):
    """Install Linux-only deps (secretstorage keyring backend) with offline→PyPI fallback."""
    req_linux = project_root / "requirements-linux.txt"
    if not req_linux.exists():
        return
    pip_conf_path = venv_path / "pip.conf"
    try:
        subprocess.run([str(pip_path), "install", "-r", str(req_linux)], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; req_linux is project_root/requirements-linux.txt
    except subprocess.CalledProcessError as e:
        if pip_conf_path.exists():
            print("  ⚠️ Offline install incomplete (Linux deps) — falling back to PyPI...")
            if e.stderr:
                for line in e.stderr.decode("utf-8", errors="replace").splitlines()[-5:]:
                    print(f"     {line}")
            print_warn(
                "Supply-chain guarantee lost: no-index removed for Linux deps, "
                "installing from PyPI without hash pins."
            )
            pip_conf_path.unlink(missing_ok=True)
            subprocess.run([str(pip_path), "install", "-r", str(req_linux)], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; req_linux is project_root/requirements-linux.txt (PyPI fallback)
        else:
            raise


def _install_mlx_engines(pip_path, venv_path):
    """Install pinned mlx-lm + mlx-vlm with offline→PyPI fallback per package."""
    print(f"   {t('detected_apple')} {CYAN}mlx-lm{RESET} + {CYAN}mlx-vlm{RESET}...")
    print(f"   {DIM}{t('mlx_dep_warning_title')} {t('mlx_dep_warning_body')}{RESET}")
    for engine_spec in ("mlx-lm==0.31.3", "mlx-vlm==0.4.4"):
        try:
            subprocess.run([str(pip_path), "install", engine_spec], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; engine_spec from local literal tuple (pinned versions)
        except subprocess.CalledProcessError:
            pip_conf_path = venv_path / "pip.conf"
            if pip_conf_path.exists():
                print(f"  ⚠️ Offline install failed for {engine_spec} — fallback to PyPI...")
                print_warn(
                    f"Supply-chain guarantee lost: no-index removed for {engine_spec}, "
                    "installing from PyPI without hash pins."
                )
                pip_conf_path.unlink(missing_ok=True)
                subprocess.run([str(pip_path), "install", engine_spec], check=True, capture_output=True)  # nosec B603: pip_path absolute venv Path; engine_spec from local literal tuple (PyPI fallback)
            else:
                raise


def _install_llama_cpp(pip_path, venv_path):
    """Install llama-cpp-python (always, enables engine switching from UI).

    The arm64 macOS wheel on PyPI ships with Metal enabled — no source
    build and no Xcode Command Line Tools required.
    """
    print(f"  🏗️ {t('installing_universal')} {CYAN}llama-cpp-python{RESET}...")
    try:
        subprocess.run(  # nosec B603: pip_path absolute venv Path; literal pinned llama-cpp-python version
            [str(pip_path), "install", "llama-cpp-python==0.3.19"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        pip_conf_path = venv_path / "pip.conf"
        if pip_conf_path.exists():
            print("  ⚠️ Offline install failed for llama-cpp-python — fallback to PyPI...")
            print_warn(
                "Supply-chain guarantee lost: no-index removed for llama-cpp-python, "
                "installing from PyPI without hash pins."
            )
            pip_conf_path.unlink(missing_ok=True)
            subprocess.run(  # nosec B603: pip_path absolute venv Path; literal pinned llama-cpp-python version (PyPI fallback)
                [str(pip_path), "install", "llama-cpp-python==0.3.19"],
                check=True,
                capture_output=True,
            )
        else:
            raise
    print_success(f"llama-cpp-python {t('installed_gpu')}")


def setup_environment(project_root, hw, engine="auto"):
    """Create the virtualenv, install dependencies, and configure the selected engine."""
    print_step(f"{BOLD}{t('setting_up_env')}{RESET}")

    venv_path = project_root / "venv"
    _ensure_venv(project_root, venv_path)

    # Path to pip/python based on OS
    if os.name == 'nt':
        pip_path = venv_path / "Scripts" / "pip.exe"
        python_path = venv_path / "Scripts" / "python.exe"
    else:
        pip_path = venv_path / "bin" / "pip3"
        python_path = venv_path / "bin" / "python3"

    # 1. Upgrade pip BEFORE writing pip.conf. With no-index=true active,
    # pip cannot upgrade itself (it's not in the wheels bundle). Running
    # the upgrade first lets pip use PyPI if available, or silently keep
    # the ensurepip version if offline — both are fine for our needs.
    subprocess.run([str(pip_path), "install", "--upgrade", "pip"], capture_output=True)  # nosec B603: pip_path absolute venv Path; literal pip args

    _setup_offline_bundle(project_root, venv_path)
    _install_requirements(pip_path, project_root / "requirements.txt", venv_path)

    # 2b. Install macOS-only deps (rumps/tray) on Darwin
    if platform.system() == "Darwin":
        _install_macos_deps(pip_path, project_root, venv_path)

    # 2c. Install Linux-only deps (secretstorage keyring backend) on Linux
    if platform.system() == "Linux":
        _install_linux_deps(pip_path, project_root, venv_path)

    # 3. Hardware-Specific Inference Engines
    print_step(f"{BOLD}{t('installing_inference')}{RESET}")
    if hw['is_apple_silicon']:
        _install_mlx_engines(pip_path, venv_path)
    # B152: llama-cpp-python is macOS-only in the first release (Linux/Windows
    # are Ollama-only — see requirements-linux.txt). Guard it like the sibling
    # _install_macos_deps, instead of installing it unconditionally.
    if platform.system() == "Darwin":
        _install_llama_cpp(pip_path, venv_path)

    return python_path
