"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b161_ollama_install_guard.py
Description: B161 — install.py (interactive path) must stop cleanly when
            ensure_ollama_installed() returns False, instead of ignoring the
            return value and falling through to _download_ollama_model (which
            then degrades into a confusing error). install_headless.py already
            guards this; the interactive path must too.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import installer.install as inst


def _arrange_ollama_fallback(monkeypatch, ollama_ok):
    """Drive _handle_mlx_engine into the 'switch to Ollama' branch."""
    # Metal unavailable → fallback menu is shown.
    monkeypatch.setattr(inst.subprocess, "run", lambda *a, **k: MagicMock(stdout="False"))
    # User chooses option "1" (switch to Ollama).
    monkeypatch.setattr("builtins.input", lambda *a, **k: "1")
    # The catalog has an Ollama alternative for our MLX model.
    monkeypatch.setattr(inst, "MODEL_CATALOG",
                        {"small": [{"mlx": "mlx-model-x", "ollama": "ollama-model-x"}]})
    monkeypatch.setattr(inst, "ensure_ollama_installed", lambda: ollama_ok)
    download_calls = []
    monkeypatch.setattr(inst, "_download_ollama_model", lambda *a, **k: download_calls.append(1))
    # Silence display helpers.
    monkeypatch.setattr(inst, "clear", lambda: None)
    monkeypatch.setattr(inst, "print_error", lambda *a, **k: None)
    return download_calls


def test_exits_when_ollama_install_fails(monkeypatch):
    """B161: ensure_ollama_installed()==False → SystemExit, no model download."""
    download_calls = _arrange_ollama_fallback(monkeypatch, ollama_ok=False)
    cfg = {"id": "mlx-model-x", "engine": "mlx"}
    with pytest.raises(SystemExit):
        inst._handle_mlx_engine(cfg, Path("/tmp"), Path("/tmp/py"))
    assert download_calls == [], "must NOT download a model when Ollama install failed"


def test_proceeds_when_ollama_install_succeeds(monkeypatch):
    """No over-blocking: ensure_ollama_installed()==True → download proceeds."""
    download_calls = _arrange_ollama_fallback(monkeypatch, ollama_ok=True)
    cfg = {"id": "mlx-model-x", "engine": "mlx"}
    inst._handle_mlx_engine(cfg, Path("/tmp"), Path("/tmp/py"))
    assert download_calls == [1]
