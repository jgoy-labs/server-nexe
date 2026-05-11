"""
Tests per personality/i18n/modular_i18n.py
Covers uncovered lines: 47-48, 62-64, 107, 123-125, 140, 148,
155-156, 172, 178-182, 186-188, 192-198, 202-215, 219-241.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from personality.i18n.modular_i18n import ModularI18nManager


@pytest.fixture
def i18n_setup(tmp_path):
    """Create a basic i18n setup with config and translation files."""
    config_file = tmp_path / "personality" / "server.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("""
[personality.i18n]
default_language = "en-US"
fallback_language = "ca-ES"
""")

    # Create en-US translations
    en_dir = tmp_path / "languages" / "en-US"
    en_dir.mkdir(parents=True)
    (en_dir / "messages_server_core.json").write_text(json.dumps({
        "server_core": {
            "startup": {"ready": "Server ready"},
            "errors": {"timeout": "Timeout error"}
        }
    }))

    # Create ca-ES translations (fallback)
    ca_dir = tmp_path / "languages" / "ca-ES"
    ca_dir.mkdir(parents=True)
    (ca_dir / "messages_server_core.json").write_text(json.dumps({
        "server_core": {
            "startup": {"ready": "Servidor preparat"},
            "only_catalan": {"msg": "Només en català"}
        }
    }))

    return config_file, tmp_path


class TestModularI18nInit:
    def test_init_with_valid_config(self, i18n_setup):
        """Lines 34-41: normal initialization."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        assert mgr.current_language == "en-US"
        assert mgr.fallback_language == "ca-ES"

    def test_init_config_not_found_uses_defaults(self, tmp_path):
        """Lines 47-48: config_path not found -> uses core.config fallback."""
        with patch("personality.i18n.modular_i18n.ModularI18nManager._find_config_path",
                   return_value=Path(tmp_path / "nonexistent.toml")):
            mgr = ModularI18nManager(config_path=Path("/nonexistent/path.toml"),
                                      base_path=tmp_path)
        assert mgr.current_language == "en-US"

    def test_load_config_exception(self, tmp_path):
        """Lines 62-64: exception during config load -> defaults."""
        config_file = tmp_path / "server.toml"
        config_file.write_text("invalid toml {{{{")
        with patch("personality.i18n.modular_i18n.ModularI18nManager._find_config_path",
                   return_value=config_file):
            mgr = ModularI18nManager(config_path=config_file, base_path=tmp_path)
        assert mgr.current_language == "en-US"
        assert mgr.fallback_language == "en-US"


class TestTranslation:
    def test_translate_existing_key(self, i18n_setup):
        """Line 145: successful translation."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr.t("server_core.startup.ready")
        assert result == "Server ready"

    def test_translate_missing_key_returns_key(self, i18n_setup):
        """Line 150-151: translation not found returns key."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr.t("nonexistent.component.key")
        assert result == "nonexistent.component.key"

    def test_translate_single_part_key_returns_key(self, i18n_setup):
        """Line 140: key with < 2 parts returns key."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr.t("singlekey")
        assert result == "singlekey"

    def test_translate_fallback_language(self, i18n_setup):
        """Line 148: fallback to secondary language."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        # Load ca-ES translations for fallback
        ca_dir = base_path / "languages" / "ca-ES"
        mgr.translations["ca-ES"] = {}
        with open(ca_dir / "messages_server_core.json", 'r') as f:
            data = json.load(f)
        mgr.translations["ca-ES"]["server_core"] = data["server_core"]
        result = mgr.t("server_core.only_catalan.msg")
        assert result == "Només en català"

    def test_translate_with_format_kwargs(self, i18n_setup):
        """Lines 153-154: translation with format interpolation."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        mgr.translations["en-US"] = {"test": {"msg": "Hello {name}"}}
        result = mgr.t("test.msg", name="World")
        assert result == "Hello World"

    def test_translate_format_error_returns_raw(self, i18n_setup):
        """Lines 155-156: format error returns raw translation."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        mgr.translations["en-US"] = {"test": {"msg": "Hello {name}"}}
        # Don't pass required kwarg
        result = mgr.t("test.msg")
        assert result == "Hello {name}"


class TestGetTranslation:
    def test_language_not_found(self, i18n_setup):
        """Line 160-161: language not in translations."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr._get_translation("fr-FR", "comp", ["key"])
        assert result is None

    def test_component_not_found(self, i18n_setup):
        """Line 163-164: component not in translations."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr._get_translation("en-US", "nonexistent", ["key"])
        assert result is None

    def test_path_not_found(self, i18n_setup):
        """Line 172: key path not found in component dict."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr._get_translation("en-US", "server_core", ["nonexistent"])
        assert result is None

    def test_non_string_result_returns_none(self, i18n_setup):
        """Line 174: result is not a string -> None."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        # server_core.startup is a dict, not a string
        result = mgr._get_translation("en-US", "server_core", ["startup"])
        assert result is None


class TestRegisterComponent:
    def test_register_translations(self, i18n_setup):
        """Lines 178-182: register component translations."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        mgr.register_component_translations("custom", {"key": "value"})
        assert "custom" in mgr.translations["en-US"]
        assert mgr.translations["en-US"]["custom"]["key"] == "value"

    def test_register_creates_language_dict(self, i18n_setup):
        """Lines 178-179: creates language dict if missing."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        mgr.translations.clear()
        mgr.register_component_translations("comp", {"k": "v"})
        assert "en-US" in mgr.translations


class TestAvailableComponents:
    def test_get_available_components(self, i18n_setup):
        """Lines 186-188: returns list of components."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        comps = mgr.get_available_components()
        assert isinstance(comps, list)

    def test_get_available_components_empty(self, i18n_setup):
        """Line 188: no components -> empty list."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        mgr.translations.clear()
        assert mgr.get_available_components() == []


class TestReload:
    def test_reload_success(self, i18n_setup):
        """Lines 192-196: successful reload."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr.reload_translations()
        assert result is True

    def test_reload_failure(self, i18n_setup):
        """Lines 197-198: reload failure returns False."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        with patch.object(mgr, '_discover_and_load_translations',
                          side_effect=RuntimeError("fail")):
            result = mgr.reload_translations()
        assert result is False


class TestHasTranslation:
    def test_has_translation_true(self, i18n_setup):
        """Lines 202-210: existing translation."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr.has_translation("server_core.startup.ready")
        assert result is True

    def test_has_translation_false(self, i18n_setup):
        """Lines 214-215: missing translation."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr.has_translation("nonexistent.key")
        assert result is False

    def test_has_translation_single_part_false(self, i18n_setup):
        """Lines 203-204: single part key returns False."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        result = mgr.has_translation("singlekey")
        assert result is False

    def test_has_translation_fallback(self, i18n_setup):
        """Lines 212-213: check fallback language."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        # Add ca-ES translation for fallback
        mgr.translations["ca-ES"] = {"test": {"msg": "Hola"}}
        result = mgr.has_translation("test.msg")
        # If not found in en-US, checks ca-ES
        if "test" not in mgr.translations.get("en-US", {}):
            assert result is True


class TestGetStats:
    def test_get_stats(self, i18n_setup):
        """Lines 219-241: translation stats."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        stats = mgr.get_stats()
        assert stats["current_language"] == "en-US"
        assert stats["fallback_language"] == "ca-ES"
        assert "total_keys" in stats
        assert isinstance(stats["components"], int)

    def test_get_stats_counts_keys(self, i18n_setup):
        """Lines 219-239: count_keys counts nested keys."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)
        mgr.translations["en-US"] = {
            "comp": {"a": "val1", "nested": {"b": "val2", "c": "val3"}}
        }
        stats = mgr.get_stats()
        assert stats["total_keys"]["en-US"]["comp"] == 3


class TestLoadTranslationFile:
    def test_load_file_with_prefix(self, tmp_path, i18n_setup):
        """Lines 103-107: file with messages_ prefix."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)

        test_file = tmp_path / "messages_mycomp.json"
        test_file.write_text(json.dumps({"key": "value"}))
        result = mgr._load_translation_file(test_file)
        assert result is True
        assert "mycomp" in mgr.translations["en-US"]

    def test_load_file_without_prefix(self, tmp_path, i18n_setup):
        """Line 107: file without messages_ prefix."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)

        test_file = tmp_path / "custom.json"
        test_file.write_text(json.dumps({"key": "value"}))
        result = mgr._load_translation_file(test_file)
        assert result is True
        assert "custom" in mgr.translations["en-US"]

    def test_load_file_error_returns_false(self, tmp_path, i18n_setup):
        """Lines 123-125: error loading file."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)

        test_file = tmp_path / "bad.json"
        test_file.write_text("not json {{")
        result = mgr._load_translation_file(test_file)
        assert result is False

    def test_load_file_with_meta_removed(self, tmp_path, i18n_setup):
        """Lines 112-113: _meta section removed."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)

        test_file = tmp_path / "messages_test.json"
        test_file.write_text(json.dumps({
            "_meta": {"version": "1.0"},
            "key": "value"
        }))
        result = mgr._load_translation_file(test_file)
        assert result is True

    def test_load_file_with_prefix_in_data(self, tmp_path, i18n_setup):
        """Lines 115-116: prefix key found in data."""
        config_file, base_path = i18n_setup
        mgr = ModularI18nManager(config_path=config_file, base_path=base_path)

        test_file = tmp_path / "messages_mycomp.json"
        test_file.write_text(json.dumps({
            "mycomp": {"nested_key": "nested_value"}
        }))
        result = mgr._load_translation_file(test_file)
        assert result is True
        assert mgr.translations["en-US"]["mycomp"]["nested_key"] == "nested_value"
