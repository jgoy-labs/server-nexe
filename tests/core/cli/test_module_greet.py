"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/tests/test_module_greet.py
Description: Tests for the ASCII banner and localised greeting of
             `CLIModule`. Guards the fix for the "NAT 7" residue that
             appeared in the previous banner.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from core.cli.module import CLIModule


@pytest.fixture
def cli():
    return CLIModule()


class TestAsciiArt:

    def test_uses_canonical_nexe_logo(self, cli):
        """`get_ascii_art()` must reuse `NEXE_LOGO` from `output.py`,
        not a duplicate/diverging banner."""
        from core.cli.output import NEXE_LOGO
        art = cli.get_ascii_art()
        assert NEXE_LOGO in art

    def test_no_nat_residue(self, cli):
        """Regression guard: the previous banner formed 'NAT 7'.
        The canonical `server-nexe` logo does not contain the NAT initials."""
        art = cli.get_ascii_art()
        # Flatten to detect the visual form `NAT` (three consecutive blocks
        # that in the obsolete banner formed the letters N-A-T).
        # Simply search for the substring in uppercase:
        assert "NAT" not in art

    def test_contains_module_orchestrator_header(self, cli):
        art = cli.get_ascii_art()
        assert "Module Orchestrator" in art

    def test_returns_multiline_str(self, cli):
        art = cli.get_ascii_art()
        # The canonical logo has 5 lines + title — minimum 5 newlines.
        assert art.count("\n") >= 5


class TestGreet:

    def test_ca_es(self, cli):
        out = cli.greet("Jordi", lang="ca-ES")
        assert "Hola Jordi!" in out
        assert "Benvingut" in out

    def test_es_es(self, cli):
        out = cli.greet("Jordi", lang="es-ES")
        assert "Hola Jordi!" in out
        assert "Bienvenido" in out

    def test_en_us(self, cli):
        out = cli.greet("Jordi", lang="en-US")
        assert "Hello Jordi!" in out
        assert "Welcome" in out

    def test_unknown_lang_falls_back_to_ca(self, cli):
        """A non-existent language falls back to ca-ES without crash."""
        out = cli.greet("Jordi", lang="xx-XX")
        assert "Hola Jordi!" in out
        assert "Benvingut" in out

    def test_env_var_default(self, cli, monkeypatch):
        """If lang is not passed, NEXE_LANG is used."""
        monkeypatch.setenv("NEXE_LANG", "es-ES")
        out = cli.greet("Jordi")
        assert "Bienvenido" in out

    def test_env_var_missing_defaults_to_en(self, cli, monkeypatch):
        monkeypatch.delenv("NEXE_LANG", raising=False)
        out = cli.greet("Jordi")
        assert "Welcome" in out

    def test_greet_includes_ascii_art(self, cli):
        out = cli.greet("Jordi", lang="ca-ES")
        assert "Module Orchestrator" in out
