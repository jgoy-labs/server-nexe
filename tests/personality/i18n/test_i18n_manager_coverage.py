"""
Tests for uncovered lines in personality/i18n/i18n_manager.py.
Targets: 31 lines missing
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import json


@pytest.fixture(autouse=True)
def _no_nexe_lang_override(monkeypatch):
    """#931: these tests control current_language via a fabricated server.toml.
    A real NEXE_LANG (dev's own .env, loaded once per process by python-dotenv)
    would now override it — I18nManager honours NEXE_LANG since #931's fix —
    making results depend on whoever's environment runs the suite."""
    monkeypatch.delenv("NEXE_LANG", raising=False)


class TestI18nManagerInit:

    def test_init_with_valid_config(self, tmp_path):
        config = tmp_path / "server.toml"
        config.write_text("""
[personality]
[personality.i18n]
default_language = "en-US"
fallback_language = "ca-ES"
translations_path = "languages"
""")
        from personality.i18n.i18n_manager import I18nManager
        mgr = I18nManager(config_path=config, base_path=tmp_path)
        assert mgr.current_language == "en-US"
        assert mgr.fallback_language == "ca-ES"

    def test_init_config_not_found(self, tmp_path):
        """Lines 61-64: config file doesn't exist."""
        from personality.i18n.i18n_manager import I18nManager
        with patch("core.config.find_config_path", return_value=tmp_path / "nonexistent.toml"):
            mgr = I18nManager(config_path=tmp_path / "nonexistent.toml", base_path=tmp_path)
            assert mgr.current_language is not None

    def test_init_config_parse_error(self, tmp_path):
        """Lines 61-64: config file can't be parsed."""
        config = tmp_path / "server.toml"
        config.write_text("invalid {{ toml")
        from personality.i18n.i18n_manager import I18nManager
        mgr = I18nManager(config_path=config, base_path=tmp_path)
        assert mgr.current_language is not None


class TestTranslations:

    @pytest.fixture
    def mgr_with_translations(self, tmp_path):
        # Create language files
        lang_dir = tmp_path / "languages" / "en-US"
        lang_dir.mkdir(parents=True)
        messages = {"greeting": {"hello": "Hello {name}"}, "simple": "Simple text"}
        (lang_dir / "messages.json").write_text(json.dumps(messages))

        # Create fallback language
        fb_dir = tmp_path / "languages" / "ca-ES"
        fb_dir.mkdir(parents=True)
        fb_messages = {"catala": "Hola", "greeting": {"hello": "Hola {name}"}}
        (fb_dir / "messages.json").write_text(json.dumps(fb_messages))

        config = tmp_path / "server.toml"
        config.write_text(f"""
[personality]
[personality.i18n]
default_language = "en-US"
fallback_language = "ca-ES"
translations_path = "languages"
""")
        from personality.i18n.i18n_manager import I18nManager
        return I18nManager(config_path=config, base_path=tmp_path)

    def test_translate_existing_key(self, mgr_with_translations):
        result = mgr_with_translations.t("greeting.hello", name="World")
        assert result == "Hello World"

    def test_translate_missing_key_returns_key(self, mgr_with_translations):
        result = mgr_with_translations.t("nonexistent.key")
        assert result == "nonexistent.key"

    def test_translate_fallback_language(self, mgr_with_translations):
        """Lines 161-163: fallback to ca-ES."""
        result = mgr_with_translations.t("catala")
        assert result == "Hola"

    def test_translate_format_error(self, mgr_with_translations):
        """Lines 172-173: format error returns raw."""
        result = mgr_with_translations.t("simple", missing_kwarg="val")
        assert result == "Simple text"

    def test_has_translation_true(self, mgr_with_translations):
        assert mgr_with_translations.has_translation("greeting.hello") is True

    def test_has_translation_false(self, mgr_with_translations):
        assert mgr_with_translations.has_translation("nonexistent") is False

    def test_has_translation_fallback(self, mgr_with_translations):
        """Lines 215-216: check fallback language."""
        assert mgr_with_translations.has_translation("catala") is True


class TestLanguageManagement:

    def test_set_language_valid(self, tmp_path):
        from personality.i18n.i18n_manager import I18nManager
        config = tmp_path / "server.toml"
        config.write_text('[personality]\n[personality.location]\n')

        mgr = I18nManager(config_path=config, base_path=tmp_path)
        mgr.translations["en-US"] = {"key": "val"}
        mgr._translations_loaded = True

        result = mgr.set_language("en-US")
        assert result is True
        assert mgr.current_language == "en-US"

    def test_set_language_invalid(self, tmp_path):
        from personality.i18n.i18n_manager import I18nManager
        config = tmp_path / "server.toml"
        config.write_text('[personality]\n[personality.location]\n')

        mgr = I18nManager(config_path=config, base_path=tmp_path)
        mgr._translations_loaded = True
        result = mgr.set_language("xx-XX")
        assert result is False

    def test_get_available_languages(self, tmp_path):
        from personality.i18n.i18n_manager import I18nManager
        config = tmp_path / "server.toml"
        config.write_text('[personality]\n[personality.location]\n')

        mgr = I18nManager(config_path=config, base_path=tmp_path)
        mgr.translations = {"ca-ES": {}, "en-US": {}}
        mgr._translations_loaded = True
        langs = mgr.get_available_languages()
        assert "ca-ES" in langs

    def test_reload_translations(self, tmp_path):
        from personality.i18n.i18n_manager import I18nManager
        config = tmp_path / "server.toml"
        config.write_text('[personality]\n[personality.location]\n')
        mgr = I18nManager(config_path=config, base_path=tmp_path)
        result = mgr.reload_translations()
        assert result is True

    def test_get_translation_stats(self, tmp_path):
        from personality.i18n.i18n_manager import I18nManager
        config = tmp_path / "server.toml"
        config.write_text('[personality]\n[personality.location]\n')

        mgr = I18nManager(config_path=config, base_path=tmp_path)
        mgr.translations = {"ca-ES": {"key": "val", "nested": {"a": "b"}}}
        mgr._translations_loaded = True
        stats = mgr.get_translation_stats()
        assert "ca-ES" in stats
        assert stats["ca-ES"] == 2


class TestLoadModuleTranslations:

    def test_load_module_translations(self, tmp_path):
        """#920: the catalog layout is <module>/languages/<lang>/messages_<component>.json.

        This fixture used to build a ``location/`` level that does not exist
        anywhere in the repo, so the test passed while the loader found nothing
        in production — an inverted assert that fixed the bug in place. The
        component name now comes from the FILE name, not the directory.
        """
        from personality.i18n.i18n_manager import I18nManager
        # Create module with translations
        mod_dir = tmp_path / "plugins" / "moduls" / "test_mod"
        lang_dir = mod_dir / "languages" / "en-US"
        lang_dir.mkdir(parents=True)
        (lang_dir / "messages_test_mod.json").write_text(json.dumps({"mod_key": "mod_val"}))

        config = tmp_path / "server.toml"
        config.write_text('[personality]\n[personality.location]\n')

        mgr = I18nManager(config_path=config, base_path=tmp_path)
        mgr.translations["en-US"] = {}
        mgr._load_module_translations(tmp_path / "plugins" / "moduls", "en-US")
        assert "test_mod" in mgr.translations["en-US"]

    def test_load_module_translations_with_meta(self, tmp_path):
        """The reserved ``_meta`` key is filtered out of a module catalog.

        Layout updated with #920 (see the sibling test): no ``location/`` level,
        and the component comes from ``messages_<component>.json``.
        """
        from personality.i18n.i18n_manager import I18nManager
        mod_dir = tmp_path / "plugins" / "moduls" / "test_mod"
        lang_dir = mod_dir / "languages" / "en-US"
        lang_dir.mkdir(parents=True)
        (lang_dir / "messages_test_mod.json").write_text(json.dumps({"_meta": {}, "key": "val"}))

        config = tmp_path / "server.toml"
        config.write_text('[personality]\n[personality.location]\n')

        mgr = I18nManager(config_path=config, base_path=tmp_path)
        mgr.translations["en-US"] = {}
        mgr._load_module_translations(tmp_path / "plugins" / "moduls", "en-US")

        loaded = mgr.translations["en-US"]["test_mod"]
        # The reserved "_meta" key must be stripped during load...
        assert "_meta" not in loaded
        # ...while real keys are loaded intact.
        assert loaded["key"] == "val"
