"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_config_merge.py
Description: TDD B9 — deep-merge personality/server.toml + root server.toml.
             Priority: DEFAULT < personality/server.toml < root server.toml < ENV vars

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from pathlib import Path

from core.config import load_config, reset_config


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_config()
    monkeypatch.delenv("NEXE_SERVER_PORT", raising=False)
    yield
    reset_config()


def _write_toml(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestConfigMerge:

    def test_only_root_server_toml(self, tmp_path):
        """Scenario 1: Only root server.toml → identical behaviour to current."""
        _write_toml(tmp_path / "server.toml", '[core.server]\nport = 8080\n')
        config = load_config(project_root=tmp_path)
        assert config["core"]["server"]["port"] == 8080
        assert config["core"]["server"]["host"] == "127.0.0.1"  # default preserved

    def test_only_personality_server_toml(self, tmp_path):
        """Scenario 2: Only personality/server.toml → identical behaviour to current."""
        _write_toml(
            tmp_path / "personality" / "server.toml",
            '[core.server]\nport = 7777\n'
            '[personality.orchestrator]\nadditional_paths = ["memory"]\n'
        )
        config = load_config(project_root=tmp_path)
        assert config["core"]["server"]["port"] == 7777
        assert config["personality"]["orchestrator"]["additional_paths"] == ["memory"]

    def test_both_deep_merge_root_overrides_personality(self, tmp_path):
        """Scenario 3 (RED gate): Both present → deep-merge.

        personality/server.toml = BASE, root server.toml = OVERRIDE.
        - Partial root overwrites ONLY its own fields.
        - Fields from personality NOT present in root are PRESERVED.
        """
        _write_toml(
            tmp_path / "personality" / "server.toml",
            '[core.server]\nport = 7777\n'
            '[personality.orchestrator]\nadditional_paths = ["memory", "personality"]\n'
        )
        _write_toml(
            tmp_path / "server.toml",
            '[core.server]\nport = 9999\n'  # Partial override — does NOT touch additional_paths
        )
        config = load_config(project_root=tmp_path)
        # Root override wins on port
        assert config["core"]["server"]["port"] == 9999
        # personality/server.toml set additional_paths; root doesn't touch it → must be preserved
        assert config["personality"]["orchestrator"]["additional_paths"] == ["memory", "personality"]

    def test_no_config_files_returns_defaults(self, tmp_path):
        """Scenario 4: No files → defaults (identical to current behaviour)."""
        config = load_config(project_root=tmp_path)
        assert config["core"]["server"]["host"] == "127.0.0.1"
        assert config["core"]["server"]["port"] == 9119
        assert "personality" not in config

    def test_invalid_personality_toml_fallback_graceful(self, tmp_path):
        """personality/server.toml invalid → log error, override continues working."""
        _write_toml(
            tmp_path / "personality" / "server.toml",
            "INVALID TOML CONTENT !!!{}"
        )
        _write_toml(tmp_path / "server.toml", '[core.server]\nport = 9999\n')
        config = load_config(project_root=tmp_path)
        # Override must keep loading despite error in personality
        assert config["core"]["server"]["port"] == 9999
        # Default host preserved (personality was not loaded)
        assert config["core"]["server"]["host"] == "127.0.0.1"

    def test_direct_config_path_with_i18n(self, tmp_path):
        """Direct config_path + i18n → i18n.t is called correctly."""
        from unittest.mock import MagicMock
        config_file = tmp_path / "custom.toml"
        _write_toml(config_file, '[core.server]\nport = 7654\n')
        i18n = MagicMock()
        i18n.t.return_value = "Translated message"
        config = load_config(config_path=config_file, i18n=i18n)
        assert config["core"]["server"]["port"] == 7654
        assert i18n.t.called

    def test_direct_config_path_invalid_toml_with_i18n_error(self, tmp_path):
        """Invalid config_path + i18n → calls i18n.t error branch, returns defaults."""
        from unittest.mock import MagicMock
        config_file = tmp_path / "bad.toml"
        _write_toml(config_file, "INVALID TOML !!!")
        i18n = MagicMock()
        i18n.t.return_value = "Translated error"
        config = load_config(config_path=config_file, i18n=i18n)
        # Fallback to defaults
        assert config["core"]["server"]["port"] == 9119
        assert i18n.t.called
