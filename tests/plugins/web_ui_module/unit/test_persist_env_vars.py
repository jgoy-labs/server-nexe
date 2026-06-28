"""
Tests for _persist_env_vars helper (Bug B-model-persist fix + MC-076).

Verifies that the model and backend selected in the UI are persisted to .env
to survive server restarts, and (MC-076) that no value containing a newline can
be persisted (line-injection guard).

NOTE: these tests now call the REAL `_persist_env_vars(updates, env_path=...)`
(via its testable `env_path` parameter) instead of a duplicated copy of its body
— so a change in the implementation is actually exercised (was test-theatre).
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
        _persist_env_vars({"NEXE_DEFAULT_MODEL": "qwen3:8b"}, env_path=env_file)
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=qwen3:8b" in content
        assert "NEXE_MODEL_ENGINE=ollama" in content
        assert "mistral:latest" not in content

    def test_adds_missing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_MODEL_ENGINE=ollama\n")
        _persist_env_vars({"NEXE_DEFAULT_MODEL": "qwen3:8b"}, env_path=env_file)
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=qwen3:8b" in content
        assert "NEXE_MODEL_ENGINE=ollama" in content

    def test_preserves_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# Model configuration\n"
            "NEXE_DEFAULT_MODEL=mistral:latest\n"
        )
        _persist_env_vars({"NEXE_DEFAULT_MODEL": "llama3.2"}, env_path=env_file)
        content = env_file.read_text()
        assert "# Model configuration" in content
        assert "NEXE_DEFAULT_MODEL=llama3.2" in content

    def test_no_env_file_silently_skips(self, tmp_path):
        env_file = tmp_path / ".env"
        # File does not exist — should not raise
        _persist_env_vars({"NEXE_DEFAULT_MODEL": "any"}, env_path=env_file)

    def test_updates_both_backend_and_model(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "NEXE_DEFAULT_MODEL=mistral:latest\n"
            "NEXE_MODEL_ENGINE=ollama\n"
        )
        _persist_env_vars(
            {"NEXE_DEFAULT_MODEL": "qwen3:8b", "NEXE_MODEL_ENGINE": "mlx"},
            env_path=env_file,
        )
        content = env_file.read_text()
        assert "NEXE_DEFAULT_MODEL=qwen3:8b" in content
        assert "NEXE_MODEL_ENGINE=mlx" in content


class TestMC076LineInjectionGuard:
    def test_value_with_newline_is_refused(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_MODEL_ENGINE=ollama\n")
        # Un model amb \n intentaria injectar una línia (p.ex. una API key).
        with pytest.raises(ValueError):
            _persist_env_vars(
                {"NEXE_DEFAULT_MODEL": "x\nNEXE_ADMIN_API_KEY=attacker"},
                env_path=env_file,
            )
        # El .env NO ha de contenir la línia injectada.
        content = env_file.read_text()
        assert "NEXE_ADMIN_API_KEY" not in content
        assert "attacker" not in content

    def test_carriage_return_is_refused(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_MODEL_ENGINE=ollama\n")
        with pytest.raises(ValueError):
            _persist_env_vars({"NEXE_DEFAULT_MODEL": "x\rEVIL=1"}, env_path=env_file)
        assert "EVIL=1" not in env_file.read_text()

    def test_unicode_line_separator_is_refused(self, tmp_path):
        """MC-076 (enduriment): U+2028/U+2029/U+0085 els reconeix splitlines(),
        que és el que usa el re-read de _persist_env_vars → injecció via Unicode."""
        env_file = tmp_path / ".env"
        env_file.write_text("NEXE_MODEL_ENGINE=ollama\n")
        for sep in ("\u2028", "\u2029", "\x85"):
            with pytest.raises(ValueError):
                _persist_env_vars(
                    {"NEXE_DEFAULT_MODEL": f"x{sep}INJECT=1"}, env_path=env_file
                )
            assert "INJECT=1" not in env_file.read_text()
