"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/i18n/tests/test_i18n_manager.py
Description: Tests per I18nManager. Valida càrrega de traduccions, fallbacks,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from personality.i18n.i18n_manager import I18nManager

class TestI18nManagerInitialization:
  """Tests for I18nManager initialization."""

  def test_init_with_defaults(self):
    """I18nManager should initialize with default values."""
    i18n = I18nManager()

    assert i18n.current_language == "ca-ES"
    assert i18n.fallback_language == "ca-ES"
    assert isinstance(i18n.translations, dict)

  def test_init_with_custom_config_path(self, tmp_path):
    """I18nManager should accept custom config path."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "en-US"
fallback_idioma = "ca-ES"
path_traduccions = "languages"
""")

    i18n = I18nManager(config_path=config_file, base_path=tmp_path)

    assert i18n.current_language == "en-US"
    assert i18n.fallback_language == "ca-ES"

  def test_init_with_missing_config(self):
    """I18nManager should use defaults if config file missing."""
    i18n = I18nManager(config_path=Path("/nonexistent/path.toml"))

    assert i18n.current_language == "ca-ES"
    assert i18n.fallback_language == "ca-ES"

class TestI18nTranslation:
  """Tests for translation functionality."""

  @pytest.fixture
  def i18n_with_translations(self, tmp_path):
    """Create I18nManager with test translations."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "ca-ES"
fallback_idioma = "en-US"
path_traduccions = "languages"
""")

    ca_dir = tmp_path / "languages" / "ca-ES"
    ca_dir.mkdir(parents=True)
    en_dir = tmp_path / "languages" / "en-US"
    en_dir.mkdir(parents=True)

    ca_messages = {
      "greeting": "Hola {name}",
      "module": {
        "start": "Iniciant mòdul",
        "stop": "Aturant mòdul"
      },
      "errors": {
        "not_found": "No trobat: {item}"
      }
    }
    (ca_dir / "messages.json").write_text(json.dumps(ca_messages))

    en_messages = {
      "greeting": "Hello {name}",
      "module": {
        "start": "Starting module",
        "stop": "Stopping module"
      },
      "errors": {
        "not_found": "Not found: {item}",
        "timeout": "Connection timeout"
      }
    }
    (en_dir / "messages.json").write_text(json.dumps(en_messages))

    return I18nManager(config_path=config_file, base_path=tmp_path)

  def test_translate_simple_key(self, i18n_with_translations):
    """Should translate a simple key."""
    result = i18n_with_translations.t("greeting", name="Jordi")
    assert result == "Hola Jordi"

  def test_translate_nested_key(self, i18n_with_translations):
    """Should translate a nested key."""
    result = i18n_with_translations.t("module.start")
    assert result == "Iniciant mòdul"

  def test_translate_with_interpolation(self, i18n_with_translations):
    """Should interpolate variables correctly."""
    result = i18n_with_translations.t("errors.not_found", item="fitxer.txt")
    assert result == "No trobat: fitxer.txt"

  def test_translate_missing_key_returns_key(self, i18n_with_translations):
    """Should return key if translation not found."""
    result = i18n_with_translations.t("nonexistent.key")
    assert result == "nonexistent.key"

  def test_translate_fallback_language(self, i18n_with_translations):
    """Should fallback to secondary language if key missing in primary."""
    result = i18n_with_translations.t("errors.timeout")
    assert result == "Connection timeout"

  def test_translate_missing_interpolation_param(self, i18n_with_translations):
    """Should handle missing interpolation parameters gracefully."""
    result = i18n_with_translations.t("greeting")
    assert "name" in result or result == "greeting"

class TestI18nLanguageManagement:
  """Tests for language switching and management."""

  @pytest.fixture
  def i18n_multilang(self, tmp_path):
    """Create I18nManager with multiple languages."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "ca-ES"
fallback_idioma = "ca-ES"
path_traduccions = "languages"
""")

    for lang in ["ca-ES", "en-US", "es-ES"]:
      lang_dir = tmp_path / "languages" / lang
      lang_dir.mkdir(parents=True)
      messages = {"test": f"Test in {lang}"}
      (lang_dir / "messages.json").write_text(json.dumps(messages))

    return I18nManager(config_path=config_file, base_path=tmp_path)

  def test_get_available_languages(self, i18n_multilang):
    """Should return list of available languages."""
    languages = i18n_multilang.get_available_languages()

    assert "ca-ES" in languages

  def test_set_language_valid(self, i18n_multilang):
    """Should change current language if available."""
    i18n_multilang.t("test")

    if "en-US" in i18n_multilang.get_available_languages():
      result = i18n_multilang.set_language("en-US")
      assert result is True
      assert i18n_multilang.current_language == "en-US"

  def test_set_language_invalid(self, i18n_multilang):
    """Should not change language if not available."""
    result = i18n_multilang.set_language("fr-FR")

    assert result is False
    assert i18n_multilang.current_language == "ca-ES"

  def test_has_translation_exists(self, i18n_multilang):
    """Should return True for existing translations."""
    assert i18n_multilang.has_translation("test") is True

  def test_has_translation_missing(self, i18n_multilang):
    """Should return False for missing translations."""
    assert i18n_multilang.has_translation("nonexistent.key") is False

class TestI18nStatistics:
  """Tests for translation statistics."""

  @pytest.fixture
  def i18n_with_stats(self, tmp_path):
    """Create I18nManager for stats testing."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "ca-ES"
fallback_idioma = "ca-ES"
path_traduccions = "languages"
""")

    ca_dir = tmp_path / "languages" / "ca-ES"
    ca_dir.mkdir(parents=True)
    messages = {
      "key1": "Value 1",
      "key2": "Value 2",
      "nested": {
        "key3": "Value 3",
        "key4": "Value 4"
      }
    }
    (ca_dir / "messages.json").write_text(json.dumps(messages))

    return I18nManager(config_path=config_file, base_path=tmp_path)

  def test_get_translation_stats(self, i18n_with_stats):
    """Should return correct translation counts."""
    stats = i18n_with_stats.get_translation_stats()

    assert "ca-ES" in stats
    assert stats["ca-ES"] == 4

class TestI18nReload:
  """Tests for translation reloading."""

  def test_reload_translations(self, tmp_path):
    """Should reload translations successfully."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "ca-ES"
fallback_idioma = "ca-ES"
path_traduccions = "languages"
""")

    lang_dir = tmp_path / "languages" / "ca-ES"
    lang_dir.mkdir(parents=True)
    (lang_dir / "messages.json").write_text('{"key": "original"}')

    i18n = I18nManager(config_path=config_file, base_path=tmp_path)
    assert i18n.t("key") == "original"

    (lang_dir / "messages.json").write_text('{"key": "modified"}')

    result = i18n.reload_translations()
    assert result is True

    assert i18n.t("key") == "modified"

class TestI18nLazyLoading:
  """Tests for lazy loading behavior."""

  def test_translations_not_loaded_until_needed(self, tmp_path):
    """Should not load translations until first t() call."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("")

    i18n = I18nManager(config_path=config_file, base_path=tmp_path)

    assert i18n._translations_loaded is False

    i18n.t("any.key")

    assert i18n._translations_loaded is True

class TestI18nEdgeCases:
  """Tests for edge cases and error handling."""

  def test_empty_translation_file(self, tmp_path):
    """Should handle empty translation file."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "ca-ES"
path_traduccions = "languages"
""")

    lang_dir = tmp_path / "languages" / "ca-ES"
    lang_dir.mkdir(parents=True)
    (lang_dir / "messages.json").write_text("{}")

    i18n = I18nManager(config_path=config_file, base_path=tmp_path)
    result = i18n.t("any.key")

    assert result == "any.key"

  def test_invalid_json_file(self, tmp_path):
    """Should handle invalid JSON gracefully."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "ca-ES"
path_traduccions = "languages"
""")

    lang_dir = tmp_path / "languages" / "ca-ES"
    lang_dir.mkdir(parents=True)
    (lang_dir / "messages.json").write_text("not valid json {")

    i18n = I18nManager(config_path=config_file, base_path=tmp_path)
    result = i18n.t("any.key")
    assert result == "any.key"

  def test_meta_section_ignored(self, tmp_path):
    """Should ignore _meta section in translation files."""
    config_file = tmp_path / "server.toml"
    config_file.write_text("""
[personality.location]
idioma_principal = "ca-ES"
path_traduccions = "languages"
""")

    lang_dir = tmp_path / "languages" / "ca-ES"
    lang_dir.mkdir(parents=True)
    messages = {
      "_meta": {"version": "1.0", "author": "test"},
      "key": "value"
    }
    (lang_dir / "messages.json").write_text(json.dumps(messages))

    i18n = I18nManager(config_path=config_file, base_path=tmp_path)

    assert i18n.t("_meta.version") == "_meta.version"
    assert i18n.t("key") == "value"