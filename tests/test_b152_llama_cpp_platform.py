"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b152_llama_cpp_platform.py
Description: B152 — _install_llama_cpp must be platform-guarded like its sibling
            _install_macos_deps. On Linux (and Windows) the first release is
            Ollama-only (requirements-linux.txt excludes llama_cpp_python), so
            it must NOT be installed there; on macOS it still must.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path
from unittest.mock import MagicMock

import installer.installer_setup_env as se


def _run_setup(monkeypatch, system, is_apple_silicon):
    calls = {"llama": 0, "mlx": 0, "macos": 0}
    monkeypatch.setattr(se, "_ensure_venv", lambda *a, **k: None)
    monkeypatch.setattr(se, "_setup_offline_bundle", lambda *a, **k: None)
    monkeypatch.setattr(se, "_install_requirements", lambda *a, **k: None)
    monkeypatch.setattr(se, "print_step", lambda *a, **k: None)
    monkeypatch.setattr(se, "_install_macos_deps", lambda *a, **k: calls.__setitem__("macos", calls["macos"] + 1))
    monkeypatch.setattr(se, "_install_mlx_engines", lambda *a, **k: calls.__setitem__("mlx", calls["mlx"] + 1))
    monkeypatch.setattr(se, "_install_llama_cpp", lambda *a, **k: calls.__setitem__("llama", calls["llama"] + 1))
    monkeypatch.setattr(se, "subprocess", MagicMock())
    monkeypatch.setattr(se.platform, "system", lambda: system)
    se.setup_environment(Path("/tmp/proj-b152"), {"is_apple_silicon": is_apple_silicon})
    return calls


def test_llama_cpp_not_installed_on_linux(monkeypatch):
    """B152: Linux is Ollama-only in the first release → no llama-cpp-python."""
    calls = _run_setup(monkeypatch, "Linux", is_apple_silicon=False)
    assert calls["llama"] == 0, "llama_cpp must NOT be installed on Linux"


def test_llama_cpp_installed_on_macos(monkeypatch):
    """No over-blocking: macOS still installs llama-cpp-python."""
    calls = _run_setup(monkeypatch, "Darwin", is_apple_silicon=True)
    assert calls["llama"] == 1, "llama_cpp must still be installed on macOS"
