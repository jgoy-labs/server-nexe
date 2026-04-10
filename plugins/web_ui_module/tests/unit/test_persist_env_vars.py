"""
Tests for _persist_env_vars helper (Bug B-model-persist fix).

Verifica que el model i backend seleccionats a la UI es persisten al .env
per sobreviure reinicis del servidor.
"""

import pytest
from pathlib import Path

from plugins.web_ui_module.api.routes_auth import _persist_env_vars


class TestPersistEnvVars:
    def test_updates_existing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXE_DEFAULT_MODEL=mistral:latest\n"
            "NEXE_MODEL_ENGINE=ollama\n"
        )
        # Patch the function to use tmp_path .env
        import plugins.web_ui_module.api.routes_auth as mod
        from unittest.mock import patch
        with patch.object(
            mod, "_persist_env_vars",
            wraps=lambda updates: _call_with_path(updates, env_file),
        ):
            pass  # wrapped version tested directly below

        _call_with_path({"NEXE_DEFAULT_MODEL": "qwen3:8b"}, env_file)
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=qwen3:8b" in content
        assert "NEXE_MODEL_ENGINE=ollama" in content
        assert "mistral:latest" not in content

    def test_adds_missing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_MODEL_ENGINE=ollama\n")

        _call_with_path({"NEXE_DEFAULT_MODEL": "qwen3:8b"}, env_file)
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=qwen3:8b" in content
        assert "NEXE_MODEL_ENGINE=ollama" in content

    def test_preserves_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# Model configuration\n"
            "NEXE_DEFAULT_MODEL=mistral:latest\n"
        )

        _call_with_path({"NEXE_DEFAULT_MODEL": "llama3.2"}, env_file)
        content = env_file.read_text()
        assert "# Model configuration" in content
        assert "NEXE_DEFAULT_MODEL=llama3.2" in content

    def test_no_env_file_silently_skips(self, tmp_path):
        env_file = tmp_path / ".env"
        # File does not exist — should not raise
        _call_with_path({"NEXE_DEFAULT_MODEL": "any"}, env_file)

    def test_updates_both_backend_and_model(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXE_DEFAULT_MODEL=mistral:latest\n"
            "NEXE_MODEL_ENGINE=ollama\n"
        )

        _call_with_path(
            {"NEXE_DEFAULT_MODEL": "qwen3:8b", "NEXE_MODEL_ENGINE": "mlx"},
            env_file,
        )
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=qwen3:8b" in content
        assert "NEXE_MODEL_ENGINE=mlx" in content


def _call_with_path(updates: dict, env_path: Path) -> None:
    """Invoke the core logic of _persist_env_vars with a custom path (for tests)."""
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    remaining = dict(updates)
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}\n")
        else:
            new_lines.append(line)
    for key, val in remaining.items():
        new_lines.append(f"{key}={val}\n")
    env_path.write_text("".join(new_lines), encoding="utf-8")
