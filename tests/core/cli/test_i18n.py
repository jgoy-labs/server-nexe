"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/tests/test_i18n.py
Description: Tests for the `core.cli.i18n.t` helper — lookup with fallback,
             kwargs interpolation, cache and behaviour with non-existent
             languages.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from core.cli import i18n


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """Ensure clean cache and NEXE_LANG environment for each test."""
    monkeypatch.delenv("NEXE_LANG", raising=False)
    i18n.clear_cache()
    yield
    i18n.clear_cache()


class TestBasicLookup:

    def test_known_key_ca(self):
        assert i18n.t("cli.greetings.hello", lang="ca-ES") == "Hola"

    def test_known_key_es(self):
        assert i18n.t("cli.greetings.hello", lang="es-ES") == "Hola"

    def test_known_key_en(self):
        assert i18n.t("cli.greetings.hello", lang="en-US") == "Hello"

    def test_nested_key(self):
        # Keys with 3 levels of depth resolve correctly.
        out = i18n.t("cli.go.starting_server", lang="ca-ES")
        assert "Iniciant" in out


class TestFallback:

    def test_unknown_lang_falls_back_to_ca(self):
        """A non-existent language falls back to ca-ES."""
        assert i18n.t("cli.greetings.hello", lang="xx-XX") == "Hola"

    def test_unknown_key_returns_default(self):
        out = i18n.t("cli.does.not.exist", default="DEF")
        assert out == "DEF"

    def test_unknown_key_no_default_returns_key(self):
        out = i18n.t("cli.does.not.exist")
        assert out == "cli.does.not.exist"


class TestInterpolation:

    def test_kwargs_formatted(self):
        out = i18n.t("cli.version_banner", lang="en-US", version="1.0.3-beta")
        assert out == "Nexe CLI v1.0.3-beta"

    def test_kwargs_missing_does_not_crash(self):
        # Missing kwargs → return raw text without crashing.
        out = i18n.t("cli.version_banner", lang="en-US")
        assert "{version}" in out


class TestEnvLang:

    def test_env_var_used_when_no_param(self, monkeypatch):
        monkeypatch.setenv("NEXE_LANG", "es-ES")
        i18n.clear_cache()
        assert i18n.t("cli.go.starting_server") == "Iniciando Nexe Server..."

    def test_param_overrides_env(self, monkeypatch):
        monkeypatch.setenv("NEXE_LANG", "es-ES")
        i18n.clear_cache()
        assert i18n.t("cli.go.starting_server", lang="en-US") == "Starting Nexe Server..."


class TestCache:

    def test_clear_cache_allows_reload(self, monkeypatch):
        # First load
        assert i18n.t("cli.greetings.hello", lang="ca-ES") == "Hola"
        # Cache clear + environment change works
        i18n.clear_cache()
        monkeypatch.setenv("NEXE_LANG", "en-US")
        assert i18n.t("cli.greetings.hello") == "Hello"


class TestMC047I18nIntegrity:
    """Guards for the MC-047 dead-code removal: the orphan `module_ok` strings
    (which named the deleted `CLIModule`) were dropped, while the live keys the
    deletion had to PRESERVE must still resolve in all three languages."""

    _LANGS = ("ca-ES", "es-ES", "en-US")

    def test_all_common_json_still_valid(self):
        """The hand edits left every common.json as parseable JSON."""
        import json
        from pathlib import Path

        lang_dir = Path(i18n.__file__).parent / "languages"
        for lang in self._LANGS:
            with (lang_dir / lang / "common.json").open(encoding="utf-8") as f:
                data = json.load(f)  # raises if invalid
            assert "cli" in data

    def test_module_ok_removed_in_all_langs(self):
        """The orphan `module_ok` keys (both occurrences) no longer resolve:
        `t()` returns the raw key when a key is absent. Mutation-proof: re-add
        `module_ok` to any common.json and this turns red."""
        for lang in self._LANGS:
            assert (
                i18n.t("cli.health_checks.basic_functionality.module_ok", lang=lang)
                == "cli.health_checks.basic_functionality.module_ok"
            )
            assert (
                i18n.t("cli.check.module_ok", lang=lang)
                == "cli.check.module_ok"
            )

    def test_sibling_keys_not_over_deleted(self):
        """The keys adjacent to the removed `module_ok` must still resolve —
        guards against over-deletion during the surgical edit."""
        for lang in self._LANGS:
            assert (
                i18n.t("cli.health_checks.basic_functionality.methods_ok", lang=lang)
                != "cli.health_checks.basic_functionality.methods_ok"
            )
            assert i18n.t("cli.check.methods_ok", lang=lang) != "cli.check.methods_ok"
            assert i18n.t("cli.check.config_ok", lang=lang) != "cli.check.config_ok"

    def test_preserved_greetings_resolve(self):
        """`cli.greetings.*` are LIVE i18n fixtures (used by this module's own
        tests) — the dead-code sweep must not have touched them."""
        assert i18n.t("cli.greetings.hello", lang="ca-ES") == "Hola"
        assert i18n.t("cli.greetings.welcome", lang="en-US").strip() != ""
        assert i18n.t("cli.greetings.welcome", lang="en-US") != "cli.greetings.welcome"
