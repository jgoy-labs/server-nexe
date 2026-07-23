"""
Unit tests for the 6 private helpers extracted from setup_environment at 9f6c054:

  _ensure_venv
  _setup_offline_bundle
  _install_requirements
  _install_macos_deps
  _install_mlx_engines
  _install_llama_cpp
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ── _ensure_venv ──────────────────────────────────────────────────────────────


class TestEnsureVenv:
    """_ensure_venv(project_root, venv_path)"""

    @patch("installer.installer_setup_env._make_venv_standalone")
    @patch("installer.installer_setup_env._get_python_for_venv", return_value="/usr/bin/python3")
    @patch("installer.installer_setup_env.subprocess")
    @patch("installer.installer_setup_env.platform")
    def test_ensure_venv_creates_on_darwin(
        self, mock_platform, mock_subprocess, mock_get_py, mock_standalone, tmp_path
    ):
        """Absent venv on Darwin → subprocess.run called with --copies --without-pip."""
        mock_platform.system.return_value = "Darwin"
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        venv_path = tmp_path / "venv"
        # venv does NOT exist yet

        from installer.installer_setup_env import _ensure_venv
        _ensure_venv(tmp_path, venv_path)

        # First call must include -m venv --copies --without-pip
        first_call_args = mock_subprocess.run.call_args_list[0]
        cmd = first_call_args[0][0]
        assert "-m" in cmd
        assert "venv" in cmd
        assert "--copies" in cmd
        assert "--without-pip" in cmd

    @patch("installer.installer_setup_env.subprocess")
    @patch("installer.installer_setup_env.platform")
    def test_ensure_venv_skips_if_healthy(self, mock_platform, mock_subprocess, tmp_path):
        """Healthy venv (bin/pip3 present) → subprocess.run NOT called."""
        mock_platform.system.return_value = "Darwin"

        venv_path = tmp_path / "venv"
        pip3 = venv_path / "bin" / "pip3"
        pip3.parent.mkdir(parents=True)
        pip3.write_text("#!/bin/sh\n")

        from installer.installer_setup_env import _ensure_venv
        _ensure_venv(tmp_path, venv_path)

        mock_subprocess.run.assert_not_called()

    @patch("installer.installer_setup_env._make_venv_standalone")
    @patch("installer.installer_setup_env._get_python_for_venv", return_value="/usr/bin/python3")
    @patch("installer.installer_setup_env.subprocess")
    @patch("installer.installer_setup_env.platform")
    def test_ensure_venv_recreates_if_broken(
        self, mock_platform, mock_subprocess, mock_get_py, mock_standalone, tmp_path
    ):
        """Broken venv (directory exists but bin/pip3 missing) → rmtree + subprocess called."""
        mock_platform.system.return_value = "Darwin"
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        # bin/pip3 is intentionally absent — broken venv

        # shutil is imported locally inside _ensure_venv as `_shutil`; patch at shutil module level
        import shutil as real_shutil
        rmtree_calls = []
        original_rmtree = real_shutil.rmtree

        def fake_rmtree(path, **kwargs):
            rmtree_calls.append(path)
            # Actually remove so venv_path.exists() returns False afterwards
            original_rmtree(path, **kwargs)

        with patch("shutil.rmtree", side_effect=fake_rmtree):
            from installer.installer_setup_env import _ensure_venv
            _ensure_venv(tmp_path, venv_path)

        assert len(rmtree_calls) >= 1
        assert mock_subprocess.run.called


# ── _setup_offline_bundle ─────────────────────────────────────────────────────


class TestSetupOfflineBundle:
    """_setup_offline_bundle(project_root, venv_path)"""

    @patch("installer.installer_setup_env._seed_fastembed_cache", return_value=True)
    @patch("installer.installer_setup_env._write_venv_pip_conf", return_value=True)
    @patch("installer.installer_setup_env._find_bundle_resources")
    def test_setup_offline_bundle_with_bundle(
        self, mock_find, mock_write_conf, mock_seed, tmp_path
    ):
        """Bundle present → _write_venv_pip_conf and _seed_fastembed_cache both called."""
        resources = tmp_path / "resources"
        (resources / "wheels").mkdir(parents=True)
        (resources / "embeddings").mkdir()
        mock_find.return_value = resources

        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        from installer.installer_setup_env import _setup_offline_bundle
        _setup_offline_bundle(tmp_path, venv_path)

        mock_write_conf.assert_called_once()
        mock_seed.assert_called_once()

    @patch("installer.installer_setup_env._seed_fastembed_cache", return_value=False)
    @patch("installer.installer_setup_env._write_venv_pip_conf", return_value=False)
    @patch("installer.installer_setup_env._find_bundle_resources", return_value=None)
    def test_setup_offline_bundle_no_bundle(
        self, mock_find, mock_write_conf, mock_seed, tmp_path
    ):
        """No bundle → _write_venv_pip_conf NOT called."""
        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        from installer.installer_setup_env import _setup_offline_bundle
        _setup_offline_bundle(tmp_path, venv_path)

        mock_write_conf.assert_not_called()


# ── _install_requirements ─────────────────────────────────────────────────────


class TestInstallRequirements:
    """_install_requirements(pip_path, req_file, venv_path)"""

    def test_install_requirements_missing_file(self, tmp_path):
        """Missing requirements.txt → sys.exit(1)."""
        pip_path = tmp_path / "pip3"
        req_file = tmp_path / "requirements.txt"  # does not exist
        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        from installer.installer_setup_env import _install_requirements
        with pytest.raises(SystemExit):
            _install_requirements(pip_path, req_file, venv_path)

    @patch("installer.installer_setup_env.subprocess")
    def test_install_requirements_success(self, mock_subprocess, tmp_path):
        """Successful install → subprocess.run called exactly once."""
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        pip_path = tmp_path / "pip3"
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask\n")
        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        from installer.installer_setup_env import _install_requirements
        _install_requirements(pip_path, req_file, venv_path)

        assert mock_subprocess.run.call_count == 1

    @patch("installer.installer_setup_env.subprocess")
    def test_install_requirements_offline_fallback(self, mock_subprocess, tmp_path, monkeypatch):
        """Offline fail + explicit consent (env) → pip.conf removed + retry (WS8-05)."""
        monkeypatch.setenv("NEXE_ALLOW_UNPINNED", "1")
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]

        pip_path = tmp_path / "pip3"
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask\n")
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"
        pip_conf.write_text("[global]\nno-index = true\n")

        from installer.installer_setup_env import _install_requirements
        _install_requirements(pip_path, req_file, venv_path)

        assert not pip_conf.exists(), "pip.conf should have been removed on fallback"
        assert mock_subprocess.run.call_count == 2

    @patch("installer.installer_setup_env.subprocess")
    def test_install_requirements_offline_fallback_refused_without_consent(
        self, mock_subprocess, tmp_path, monkeypatch
    ):
        """WS8-05: offline fail WITHOUT consent (headless) → abort fail-closed, pip.conf preserved."""
        monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
        monkeypatch.setattr("installer.download_verify.sys.stdin", MagicMock(isatty=lambda: False))
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]

        pip_path = tmp_path / "pip3"
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask\n")
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"
        pip_conf.write_text("[global]\nno-index = true\n")

        from installer.download_verify import UnpinnedModelError
        from installer.installer_setup_env import _install_requirements
        with pytest.raises(UnpinnedModelError):
            _install_requirements(pip_path, req_file, venv_path)

        assert pip_conf.exists(), "pip.conf must be preserved when consent is refused"
        assert mock_subprocess.run.call_count == 1, "no PyPI retry without consent"

    @patch("installer.installer_setup_env.subprocess")
    def test_install_requirements_offline_fallback_interactive_decline(
        self, mock_subprocess, tmp_path, monkeypatch
    ):
        """WS8-05: interactive user answers 'n' → abort, pip.conf preserved."""
        monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
        monkeypatch.setattr("installer.download_verify.sys.stdin", MagicMock(isatty=lambda: True))
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]

        pip_path = tmp_path / "pip3"
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask\n")
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"
        pip_conf.write_text("[global]\nno-index = true\n")

        from installer.download_verify import UnpinnedModelError
        from installer.installer_setup_env import _install_requirements
        with pytest.raises(UnpinnedModelError):
            _install_requirements(pip_path, req_file, venv_path)

        assert pip_conf.exists()
        assert mock_subprocess.run.call_count == 1

    @patch("installer.installer_setup_env.subprocess")
    def test_install_requirements_online_failure_raises(self, mock_subprocess, tmp_path):
        """Online mode failure (no pip.conf) → CalledProcessError re-raised."""
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = err

        pip_path = tmp_path / "pip3"
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask\n")
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        # No pip.conf — online mode

        from installer.installer_setup_env import _install_requirements
        with pytest.raises(subprocess.CalledProcessError):
            _install_requirements(pip_path, req_file, venv_path)


# ── _install_macos_deps ───────────────────────────────────────────────────────


class TestInstallMacosDeps:
    """_install_macos_deps(pip_path, project_root, venv_path)"""

    @patch("installer.installer_setup_env.subprocess")
    def test_install_macos_deps_no_file(self, mock_subprocess, tmp_path):
        """No requirements-macos.txt → returns without subprocess call."""
        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        # requirements-macos.txt intentionally absent

        from installer.installer_setup_env import _install_macos_deps
        _install_macos_deps(pip_path, tmp_path, venv_path)

        mock_subprocess.run.assert_not_called()

    @patch("installer.installer_setup_env.subprocess")
    def test_install_macos_deps_success(self, mock_subprocess, tmp_path):
        """requirements-macos.txt present, install succeeds → subprocess called once."""
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        pip_path = tmp_path / "pip3"
        req_macos = tmp_path / "requirements-macos.txt"
        req_macos.write_text("rumps\n")
        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        from installer.installer_setup_env import _install_macos_deps
        _install_macos_deps(pip_path, tmp_path, venv_path)

        assert mock_subprocess.run.call_count == 1

    @patch("installer.installer_setup_env.subprocess")
    def test_install_macos_deps_offline_fallback(self, mock_subprocess, tmp_path, monkeypatch):
        """Offline fail + explicit consent (env) → pip.conf unlinked + retry (WS8-05)."""
        monkeypatch.setenv("NEXE_ALLOW_UNPINNED", "1")
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]

        pip_path = tmp_path / "pip3"
        req_macos = tmp_path / "requirements-macos.txt"
        req_macos.write_text("rumps\n")
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"
        pip_conf.write_text("[global]\nno-index = true\n")

        from installer.installer_setup_env import _install_macos_deps
        _install_macos_deps(pip_path, tmp_path, venv_path)

        assert not pip_conf.exists(), "pip.conf should be unlinked after fallback"
        assert mock_subprocess.run.call_count == 2

    @patch("installer.installer_setup_env.subprocess")
    def test_install_macos_deps_refused_without_consent(self, mock_subprocess, tmp_path, monkeypatch):
        """WS8-05: macOS fallback fails closed headless without consent."""
        monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
        monkeypatch.setattr("installer.download_verify.sys.stdin", MagicMock(isatty=lambda: False))
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]
        pip_path = tmp_path / "pip3"
        (tmp_path / "requirements-macos.txt").write_text("rumps\n")
        venv_path = tmp_path / "venv"; venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"; pip_conf.write_text("[global]\nno-index = true\n")

        from installer.download_verify import UnpinnedModelError
        from installer.installer_setup_env import _install_macos_deps
        with pytest.raises(UnpinnedModelError):
            _install_macos_deps(pip_path, tmp_path, venv_path)
        assert pip_conf.exists()
        assert mock_subprocess.run.call_count == 1


# ── _install_linux_deps ──────────────────────────────────────────────────────


class TestInstallLinuxDepsRefusal:
    @patch("installer.installer_setup_env.subprocess")
    def test_install_linux_deps_refused_without_consent(self, mock_subprocess, tmp_path, monkeypatch):
        """WS8-05: Linux fallback fails closed headless without consent."""
        monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
        monkeypatch.setattr("installer.download_verify.sys.stdin", MagicMock(isatty=lambda: False))
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]
        pip_path = tmp_path / "pip3"
        (tmp_path / "requirements-linux.txt").write_text("secretstorage\n")
        venv_path = tmp_path / "venv"; venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"; pip_conf.write_text("[global]\nno-index = true\n")

        from installer.download_verify import UnpinnedModelError
        from installer.installer_setup_env import _install_linux_deps
        with pytest.raises(UnpinnedModelError):
            _install_linux_deps(pip_path, tmp_path, venv_path)
        assert pip_conf.exists()
        assert mock_subprocess.run.call_count == 1


# ── _install_mlx_engines ──────────────────────────────────────────────────────


class TestInstallMlxEngines:
    """_install_mlx_engines(pip_path, venv_path)"""

    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    @patch("installer.installer_setup_env.subprocess")
    def test_install_mlx_engines_success(self, mock_subprocess, mock_t, tmp_path):
        """Both mlx-lm and mlx-vlm install OK → exactly 2 subprocess calls."""
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        from installer.installer_setup_env import _install_mlx_engines
        _install_mlx_engines(pip_path, venv_path)

        assert mock_subprocess.run.call_count == 2

    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    @patch("installer.installer_setup_env.subprocess")
    def test_install_mlx_engines_fallback(self, mock_subprocess, mock_t, tmp_path, monkeypatch):
        """Second package fails offline + consent (env) → pip.conf unlinked + retry = 3 total calls (WS8-05)."""
        monkeypatch.setenv("NEXE_ALLOW_UNPINNED", "1")
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        # First package (mlx-lm) OK, second (mlx-vlm) fails first, then OK
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0),  # mlx-lm OK
            err,                      # mlx-vlm offline fail
            MagicMock(returncode=0),  # mlx-vlm PyPI retry OK
        ]

        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"
        pip_conf.write_text("[global]\nno-index = true\n")

        from installer.installer_setup_env import _install_mlx_engines
        _install_mlx_engines(pip_path, venv_path)

        assert not pip_conf.exists(), "pip.conf should be unlinked after fallback"
        assert mock_subprocess.run.call_count == 3

    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    @patch("installer.installer_setup_env.subprocess")
    def test_install_mlx_engines_refused_without_consent(self, mock_subprocess, mock_t, tmp_path, monkeypatch):
        """WS8-05: mlx fallback fails closed headless without consent."""
        monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
        monkeypatch.setattr("installer.download_verify.sys.stdin", MagicMock(isatty=lambda: False))
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [MagicMock(returncode=0), err, MagicMock(returncode=0)]
        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"; venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"; pip_conf.write_text("[global]\nno-index = true\n")

        from installer.download_verify import UnpinnedModelError
        from installer.installer_setup_env import _install_mlx_engines
        with pytest.raises(UnpinnedModelError):
            _install_mlx_engines(pip_path, venv_path)
        assert pip_conf.exists()


# ── _install_llama_cpp ────────────────────────────────────────────────────────


class TestInstallLlamaCpp:
    """_install_llama_cpp(pip_path, venv_path)"""

    @patch("installer.installer_setup_env.print_success")
    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    @patch("installer.installer_setup_env.subprocess")
    def test_install_llama_cpp_success(self, mock_subprocess, mock_t, mock_print_success, tmp_path):
        """Successful install → no exception raised."""
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        from installer.installer_setup_env import _install_llama_cpp
        _install_llama_cpp(pip_path, venv_path)  # must not raise

    @patch("installer.installer_setup_env.print_success")
    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    @patch("installer.installer_setup_env.subprocess")
    def test_install_llama_cpp_refused_without_consent(self, mock_subprocess, mock_t, mock_ps, tmp_path, monkeypatch):
        """WS8-05: llama-cpp fallback fails closed headless without consent."""
        monkeypatch.delenv("NEXE_ALLOW_UNPINNED", raising=False)
        monkeypatch.setattr("installer.download_verify.sys.stdin", MagicMock(isatty=lambda: False))
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]
        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"; venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"; pip_conf.write_text("[global]\nno-index = true\n")

        from installer.download_verify import UnpinnedModelError
        from installer.installer_setup_env import _install_llama_cpp
        with pytest.raises(UnpinnedModelError):
            _install_llama_cpp(pip_path, venv_path)
        assert pip_conf.exists()

        assert mock_subprocess.run.call_count == 1

    @patch("installer.installer_setup_env.print_success")
    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    @patch("installer.installer_setup_env.subprocess")
    def test_install_llama_cpp_offline_fallback(self, mock_subprocess, mock_t, mock_print_success, tmp_path, monkeypatch):
        """Offline fail + consent (env) → pip.conf unlinked + retry = 2 subprocess calls (WS8-05)."""
        monkeypatch.setenv("NEXE_ALLOW_UNPINNED", "1")
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = [err, MagicMock(returncode=0)]

        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        pip_conf = venv_path / "pip.conf"
        pip_conf.write_text("[global]\nno-index = true\n")

        from installer.installer_setup_env import _install_llama_cpp
        _install_llama_cpp(pip_path, venv_path)

        assert not pip_conf.exists(), "pip.conf should be unlinked after fallback"
        assert mock_subprocess.run.call_count == 2

    @patch("installer.installer_setup_env.print_success")
    @patch("installer.installer_setup_env.t", side_effect=lambda x: x)
    @patch("installer.installer_setup_env.subprocess")
    def test_install_llama_cpp_online_failure_raises(self, mock_subprocess, mock_t, mock_print_success, tmp_path):
        """Online mode failure (no pip.conf) → CalledProcessError re-raised."""
        err = subprocess.CalledProcessError(1, "pip", stderr=b"error")
        mock_subprocess.CalledProcessError = subprocess.CalledProcessError
        mock_subprocess.run.side_effect = err

        pip_path = tmp_path / "pip3"
        venv_path = tmp_path / "venv"
        venv_path.mkdir()
        # No pip.conf — online mode

        from installer.installer_setup_env import _install_llama_cpp
        with pytest.raises(subprocess.CalledProcessError):
            _install_llama_cpp(pip_path, venv_path)
