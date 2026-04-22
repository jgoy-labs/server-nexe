"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/tests/test_i18n.py
Description: Tests del helper `core.cli.i18n.t` — lookup amb fallback,
             interpolació kwargs, cache i comportament davant d'idiomes
             inexistents.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from core.cli import i18n


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """Assegura cache i entorn NEXE_LANG nets per cada test."""
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
        # Claus amb 3 nivells de profunditat resolen correctament.
        out = i18n.t("cli.go.starting_server", lang="ca-ES")
        assert "Iniciant" in out


class TestFallback:

    def test_unknown_lang_falls_back_to_ca(self):
        """Un idioma no existent cau a ca-ES."""
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
        # Missing kwargs → retorna el text cru sense petar.
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
        # Primera càrrega
        assert i18n.t("cli.greetings.hello", lang="ca-ES") == "Hola"
        # Cache clear + canvi d'entorn funciona
        i18n.clear_cache()
        monkeypatch.setenv("NEXE_LANG", "en-US")
        assert i18n.t("cli.greetings.hello") == "Hello"
