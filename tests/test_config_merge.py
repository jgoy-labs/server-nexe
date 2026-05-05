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
        """Escenari 1: Només root server.toml → comportament idèntic a l'actual."""
        _write_toml(tmp_path / "server.toml", '[core.server]\nport = 8080\n')
        config = load_config(project_root=tmp_path)
        assert config["core"]["server"]["port"] == 8080
        assert config["core"]["server"]["host"] == "127.0.0.1"  # default preservat

    def test_only_personality_server_toml(self, tmp_path):
        """Escenari 2: Només personality/server.toml → comportament idèntic a l'actual."""
        _write_toml(
            tmp_path / "personality" / "server.toml",
            '[core.server]\nport = 7777\n'
            '[personality.orchestrator]\nadditional_paths = ["memory"]\n'
        )
        config = load_config(project_root=tmp_path)
        assert config["core"]["server"]["port"] == 7777
        assert config["personality"]["orchestrator"]["additional_paths"] == ["memory"]

    def test_both_deep_merge_root_overrides_personality(self, tmp_path):
        """Escenari 3 (RED gate): Tots dos presents → deep-merge.

        personality/server.toml = BASE, root server.toml = OVERRIDE.
        - Root parcial sobreescriu NOMÉS els seus camps.
        - Camps de personality NO presents al root es MANTENEN.
        """
        _write_toml(
            tmp_path / "personality" / "server.toml",
            '[core.server]\nport = 7777\n'
            '[personality.orchestrator]\nadditional_paths = ["memory", "personality"]\n'
        )
        _write_toml(
            tmp_path / "server.toml",
            '[core.server]\nport = 9999\n'  # Override parcial — NO toca additional_paths
        )
        config = load_config(project_root=tmp_path)
        # Root override guanya al port
        assert config["core"]["server"]["port"] == 9999
        # personality/server.toml ha posat additional_paths; root no el toca → s'ha de mantenir
        assert config["personality"]["orchestrator"]["additional_paths"] == ["memory", "personality"]

    def test_no_config_files_returns_defaults(self, tmp_path):
        """Escenari 4: Cap fitxer → defaults (comportament idèntic actual)."""
        config = load_config(project_root=tmp_path)
        assert config["core"]["server"]["host"] == "127.0.0.1"
        assert config["core"]["server"]["port"] == 9119
        assert "personality" not in config

    def test_invalid_personality_toml_fallback_graceful(self, tmp_path):
        """personality/server.toml invàlid → log error, override continua funcionant."""
        _write_toml(
            tmp_path / "personality" / "server.toml",
            "INVALID TOML CONTENT !!!{}"
        )
        _write_toml(tmp_path / "server.toml", '[core.server]\nport = 9999\n')
        config = load_config(project_root=tmp_path)
        # Override ha de seguir carregant-se malgrat error a personality
        assert config["core"]["server"]["port"] == 9999
        # Default host preservat (personality no es va carregar)
        assert config["core"]["server"]["host"] == "127.0.0.1"

    def test_direct_config_path_with_i18n(self, tmp_path):
        """config_path directe + i18n → es crida i18n.t correctament."""
        from unittest.mock import MagicMock
        config_file = tmp_path / "custom.toml"
        _write_toml(config_file, '[core.server]\nport = 7654\n')
        i18n = MagicMock()
        i18n.t.return_value = "Missatge traduit"
        config = load_config(config_path=config_file, i18n=i18n)
        assert config["core"]["server"]["port"] == 7654
        assert i18n.t.called

    def test_direct_config_path_invalid_toml_with_i18n_error(self, tmp_path):
        """config_path invàlid + i18n → crida i18n.t error branch, retorna defaults."""
        from unittest.mock import MagicMock
        config_file = tmp_path / "bad.toml"
        _write_toml(config_file, "INVALID TOML !!!")
        i18n = MagicMock()
        i18n.t.return_value = "Error traduit"
        config = load_config(config_path=config_file, i18n=i18n)
        # Fallback als defaults
        assert config["core"]["server"]["port"] == 9119
        assert i18n.t.called
