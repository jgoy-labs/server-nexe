"""
Tests per installer/installer_setup_env.py — fix del venv trencat quan s'expulsa el DMG.

Cobertura:
- _is_dmg_python: detecta si sys.executable ve d'un DMG montat
- _copy_python_bundle: copia el bundle Python al directori d'instal·lació
- _get_python_for_venv: tria el Python correcte (bundle copiat vs sys.executable)
- _make_venv_standalone: safety net per assegurar que el venv és autònom
- setup_environment: integració (path macOS amb DMG simulat)
"""

import os
import platform
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ── Helpers per simular un bundle Python dins /Volumes/ ──────────────


def _make_fake_python_bundle(tmp_path, base="/Volumes/Install Nexe/InstallNexe.app"):
    """Crea un bundle Python fals dins tmp_path que simula /Volumes/."""
    # Estructura: base/Contents/Resources/python/bin/python3
    #                                             /lib/python3.12/encodings/__init__.py
    #                                             /lib/libpython3.12.dylib
    bundle_root = tmp_path / base.lstrip("/")
    bin_dir = bundle_root / "Contents" / "Resources" / "python" / "bin"
    lib_dir = bundle_root / "Contents" / "Resources" / "python" / "lib"
    py_lib_dir = lib_dir / "python3.12" / "encodings"

    bin_dir.mkdir(parents=True)
    lib_dir.mkdir(parents=True)
    py_lib_dir.mkdir(parents=True)

    # Crear binari fals (fitxer executable)
    python_bin = bin_dir / "python3"
    python_bin.write_text("#!/bin/sh\necho fake python")
    python_bin.chmod(0o755)

    # Crear python3.12 symlink
    (bin_dir / "python3.12").symlink_to(python_bin)

    # Crear libpython fals
    (lib_dir / "libpython3.12.dylib").write_bytes(b"\x00" * 100)

    # Crear encodings fals
    (py_lib_dir / "__init__.py").write_text("# encodings stub")

    return str(python_bin)


# ── Tests per _is_dmg_python ─────────────────────────────────────────


class TestIsDmgPython:
    """Detecta si Python ve d'un DMG montat."""

    def test_volumes_path_detected(self):
        from installer.installer_setup_env import _is_dmg_python
        assert _is_dmg_python("/Volumes/Install Nexe/InstallNexe.app/Contents/Resources/python/bin/python3")

    def test_app_bundle_in_volumes(self):
        from installer.installer_setup_env import _is_dmg_python
        assert _is_dmg_python("/Volumes/MyDisk/SomeApp.app/python3")

    def test_homebrew_not_detected(self):
        from installer.installer_setup_env import _is_dmg_python
        assert not _is_dmg_python("/opt/homebrew/bin/python3.12")

    def test_usr_local_not_detected(self):
        from installer.installer_setup_env import _is_dmg_python
        assert not _is_dmg_python("/usr/local/bin/python3")

    def test_venv_not_detected(self):
        from installer.installer_setup_env import _is_dmg_python
        assert not _is_dmg_python("/Users/user/project/venv/bin/python3")

    def test_linux_not_detected(self):
        from installer.installer_setup_env import _is_dmg_python
        assert not _is_dmg_python("/usr/bin/python3")


# ── Tests per _find_python_bundle_root ───────────────────────────────


class TestFindPythonBundleRoot:
    """Troba l'arrel del bundle Python a partir del path de l'executable."""

    def test_standard_bundle_layout(self, tmp_path):
        fake_py = _make_fake_python_bundle(tmp_path)
        from installer.installer_setup_env import _find_python_bundle_root
        root = _find_python_bundle_root(fake_py)
        assert root is not None
        assert (root / "bin" / "python3").exists()
        assert (root / "lib" / "libpython3.12.dylib").exists()

    def test_returns_none_for_system_python(self):
        from installer.installer_setup_env import _find_python_bundle_root
        result = _find_python_bundle_root("/opt/homebrew/bin/python3.12")
        assert result is None


# ── Tests per _copy_python_bundle ────────────────────────────────────


class TestCopyPythonBundle:
    """Copia el bundle Python del DMG al directori d'instal·lació."""

    def test_copies_bin_and_lib(self, tmp_path):
        fake_py = _make_fake_python_bundle(tmp_path)
        from installer.installer_setup_env import _find_python_bundle_root, _copy_python_bundle

        bundle_root = _find_python_bundle_root(fake_py)
        install_dir = tmp_path / "install"
        install_dir.mkdir()

        local_python = _copy_python_bundle(bundle_root, install_dir)

        assert Path(local_python).exists()
        assert (install_dir / "python_bundle" / "bin" / "python3").exists()
        assert (install_dir / "python_bundle" / "lib" / "libpython3.12.dylib").exists()
        assert (install_dir / "python_bundle" / "lib" / "python3.12" / "encodings" / "__init__.py").exists()

    def test_local_python_is_executable(self, tmp_path):
        fake_py = _make_fake_python_bundle(tmp_path)
        from installer.installer_setup_env import _find_python_bundle_root, _copy_python_bundle

        bundle_root = _find_python_bundle_root(fake_py)
        install_dir = tmp_path / "install"
        install_dir.mkdir()

        local_python = _copy_python_bundle(bundle_root, install_dir)
        assert os.access(local_python, os.X_OK)

    def test_no_volumes_references_in_bundle(self, tmp_path):
        fake_py = _make_fake_python_bundle(tmp_path)
        from installer.installer_setup_env import _find_python_bundle_root, _copy_python_bundle

        bundle_root = _find_python_bundle_root(fake_py)
        install_dir = tmp_path / "install"
        install_dir.mkdir()

        local_python = _copy_python_bundle(bundle_root, install_dir)
        bundle_dir = install_dir / "python_bundle"

        # Cap symlink dins del bundle copiat ha d'apuntar a /Volumes/
        for p in bundle_dir.rglob("*"):
            if p.is_symlink():
                target = str(os.readlink(p))
                assert "/Volumes/" not in target, f"Symlink {p} apunta a {target}"

    def test_skips_if_already_copied(self, tmp_path):
        fake_py = _make_fake_python_bundle(tmp_path)
        from installer.installer_setup_env import _find_python_bundle_root, _copy_python_bundle

        bundle_root = _find_python_bundle_root(fake_py)
        install_dir = tmp_path / "install"
        install_dir.mkdir()

        # Primera còpia
        local_python1 = _copy_python_bundle(bundle_root, install_dir)
        # Segona còpia — no ha de petar
        local_python2 = _copy_python_bundle(bundle_root, install_dir)
        assert local_python1 == local_python2


# ── Tests per _get_python_for_venv ───────────────────────────────────


class TestGetPythonForVenv:
    """Tria el Python correcte per crear el venv."""

    @patch("installer.installer_setup_env._is_dmg_python", return_value=False)
    def test_returns_sys_executable_when_not_dmg(self, mock_is_dmg):
        from installer.installer_setup_env import _get_python_for_venv
        result = _get_python_for_venv(Path("/fake/project"))
        assert result == sys.executable

    @patch("installer.installer_setup_env._is_dmg_python", return_value=True)
    @patch("installer.installer_setup_env._find_python_bundle_root")
    @patch("installer.installer_setup_env._copy_python_bundle")
    def test_copies_bundle_when_dmg(self, mock_copy, mock_find_root, mock_is_dmg):
        mock_find_root.return_value = Path("/fake/bundle")
        mock_copy.return_value = "/fake/project/python_bundle/bin/python3"

        from installer.installer_setup_env import _get_python_for_venv
        result = _get_python_for_venv(Path("/fake/project"))

        assert result == "/fake/project/python_bundle/bin/python3"
        mock_copy.assert_called_once()


# ── Tests per _make_venv_standalone (ja existent, ha de seguir funcionant) ──


class TestMakeVenvStandalone:
    """Safety net: _make_venv_standalone segueix funcionant."""

    @patch("subprocess.run")
    def test_copies_libpython_if_exists(self, mock_run, tmp_path):
        # Simular bundle amb libpython
        lib_dir = tmp_path / "bundle" / "lib"
        lib_dir.mkdir(parents=True)
        (lib_dir / "libpython3.12.dylib").write_bytes(b"\x00" * 50)

        # Simular venv
        venv_path = tmp_path / "venv"
        venv_lib = venv_path / "lib"
        venv_lib.mkdir(parents=True)
        venv_bin = venv_path / "bin"
        venv_bin.mkdir(parents=True)

        with patch("installer.installer_setup_env.sys") as mock_sys:
            mock_sys.executable = str(tmp_path / "bundle" / "bin" / "python3")
            from installer.installer_setup_env import _make_venv_standalone
            _make_venv_standalone(venv_path)

        assert (venv_lib / "libpython3.12.dylib").exists()


# ── Tests d'integració per setup_environment ─────────────────────────


class TestSetupEnvironmentDmgPath:
    """Verifica que setup_environment usa el Python local quan ve de DMG."""

    @patch("installer.installer_setup_env.platform")
    @patch("installer.installer_setup_env.subprocess")
    @patch("installer.installer_setup_env._get_python_for_venv")
    @patch("installer.installer_setup_env._make_venv_standalone")
    @patch("installer.installer_setup_env.print_step")
    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    def test_uses_local_python_for_venv_creation(
        self, mock_t, mock_print_step, mock_standalone, mock_get_py,
        mock_subprocess, mock_platform, tmp_path
    ):
        mock_platform.system.return_value = "Darwin"
        mock_get_py.return_value = "/local/python_bundle/bin/python3"

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "requirements.txt").write_text("flask\n")

        hw = {"is_apple_silicon": False}

        from installer.installer_setup_env import setup_environment
        setup_environment(project_root, hw, engine="auto")

        # Verificar que la crida a venv usa el python local, NO sys.executable
        venv_call = mock_subprocess.run.call_args_list[0]
        python_used = venv_call[0][0][0]
        assert python_used == "/local/python_bundle/bin/python3"
        assert "/Volumes/" not in python_used


class TestSetupEnvironmentNonDmg:
    """Verifica que setup_environment funciona normal quan NO ve de DMG."""

    @patch("installer.installer_setup_env.platform")
    @patch("installer.installer_setup_env.subprocess")
    @patch("installer.installer_setup_env._get_python_for_venv")
    @patch("installer.installer_setup_env._make_venv_standalone")
    @patch("installer.installer_setup_env.print_step")
    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    def test_uses_sys_executable_when_not_dmg(
        self, mock_t, mock_print_step, mock_standalone, mock_get_py,
        mock_subprocess, mock_platform, tmp_path
    ):
        mock_platform.system.return_value = "Darwin"
        mock_get_py.return_value = sys.executable

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "requirements.txt").write_text("flask\n")

        hw = {"is_apple_silicon": False}

        from installer.installer_setup_env import setup_environment
        setup_environment(project_root, hw, engine="auto")

        venv_call = mock_subprocess.run.call_args_list[0]
        python_used = venv_call[0][0][0]
        assert python_used == sys.executable
