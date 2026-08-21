"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_config_catalog.py
Description: D-P — unique config-key catalog (#874).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
from pathlib import Path

import pytest

from core.config_catalog import (
    CATALOG,
    TOML_SECTIONS,
    default_for,
    get_decl,
    is_sensitive,
)
from core.config import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_CONFIG, NexeSettings
from core.loader.protocol import module_config_from_context


REPO = Path(__file__).resolve().parents[2]


class TestCatalogContract:
    def test_ids_and_env_aliases_are_unique(self):
        ids = [k.id for k in CATALOG]
        assert len(ids) == len(set(ids))
        envs = [k.env for k in CATALOG if k.env]
        assert len(envs) == len(set(envs))

    def test_mode_defaults_for_the_keys_that_used_to_diverge(self):
        assert default_for("auto_ingest_knowledge", sidecar=False) is True
        assert default_for("auto_ingest_knowledge", sidecar=True) is False
        assert default_for("qdrant_path") == "storage/vectors"
        assert default_for("env", sidecar=False) == "development"
        assert default_for("env", sidecar=True) == "production"
        assert default_for("server_host") == DEFAULT_HOST
        assert default_for("server_port") == DEFAULT_PORT
        assert DEFAULT_CONFIG["core"]["server"]["host"] == default_for("server_host")
        assert DEFAULT_CONFIG["core"]["server"]["port"] == default_for("server_port")

    def test_secrets_are_marked_and_have_no_value(self):
        for key_id in ("primary_api_key", "admin_api_key", "csrf_secret", "master_key"):
            decl = get_decl(key_id)
            assert decl.sensitive is True
            assert is_sensitive(decl.env)
            assert decl.default in ("", None)

    def test_runtime_born_keys_are_flagged(self):
        for key_id in ("port", "parent_pid", "home", "data_dir"):
            assert get_decl(key_id).runtime is True

    def test_unknown_id_raises(self):
        with pytest.raises(KeyError):
            get_decl("no_such_key")


class TestReadersDrink:
    def test_nexe_settings_list_settings_uses_catalog(self):
        rows = {r["name"]: r for r in NexeSettings.list_settings()}
        auto = rows["NEXE_AUTO_INGEST_KNOWLEDGE"]
        assert auto["default"] is True
        assert auto["default_sidecar"] is False
        assert auto["sensitive"] is False
        key = rows["NEXE_PRIMARY_API_KEY"]
        assert key["sensitive"] is True

    def test_sidecar_standalone_auto_ingest_matches_catalog(self, monkeypatch):
        from core.sidecar_config import SidecarConfig, reset_sidecar_config
        monkeypatch.delenv("NEXE_AUTO_INGEST_KNOWLEDGE", raising=False)
        monkeypatch.delenv("NEXE_SIDECAR", raising=False)
        reset_sidecar_config()
        assert SidecarConfig.from_env().auto_ingest_knowledge is True
        reset_sidecar_config()


class TestNoReconciliation:
    def test_lifespan_does_not_parse_auto_ingest_with_a_literal_default(self):
        import core.lifespan_modules as lm
        text = inspect.getsource(lm.auto_ingest_knowledge)
        assert 'getenv("NEXE_AUTO_INGEST_KNOWLEDGE", "true")' not in text
        assert "if cfg.is_sidecar" not in text
        assert "cfg.auto_ingest_knowledge" in text


class TestModuleConfigShape:
    def test_toml_sections_live_in_the_catalog(self):
        assert "core" in TOML_SECTIONS
        assert "plugins" in TOML_SECTIONS

    def test_protocol_no_longer_sniffs_test_dicts(self):
        src = inspect.getsource(module_config_from_context)
        assert "_TOML_TOP_LEVEL" not in src
        assert module_config_from_context(
            {"config": {"flash_ttl_seconds": 1}}, "memory"
        ) == {}
        assert module_config_from_context(
            {"config": {"memory": {"flash_ttl_seconds": 1}}}, "memory"
        ) == {"flash_ttl_seconds": 1}
