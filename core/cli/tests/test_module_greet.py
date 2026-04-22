"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/tests/test_module_greet.py
Description: Tests per al banner ASCII i la salutació localitzada de
             `CLIModule`. Guarden el fix pel residu "NAT 7" que
             apareixia al banner anterior.

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
        """`get_ascii_art()` ha de reutilitzar `NEXE_LOGO` de `output.py`,
        no un banner duplicat/divergent."""
        from core.cli.output import NEXE_LOGO
        art = cli.get_ascii_art()
        assert NEXE_LOGO in art

    def test_no_nat_residue(self, cli):
        """Regression guard: el banner anterior formava 'NAT 7'.
        El logo canònic `server-nexe` no conté les sigles NAT."""
        art = cli.get_ascii_art()
        # Aplanem per detectar la forma visual `NAT` (tres blocs consecutius
        # que al banner obsolet formaven les lletres N-A-T).
        # Simplement buscar la subcadena en majúscules:
        assert "NAT" not in art

    def test_contains_module_orchestrator_header(self, cli):
        art = cli.get_ascii_art()
        assert "Module Orchestrator" in art

    def test_returns_multiline_str(self, cli):
        art = cli.get_ascii_art()
        # El logo canònic té 5 línies + títol — mínim 5 salts de línia.
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
        """Un idioma inexistent cau a ca-ES sense crash."""
        out = cli.greet("Jordi", lang="xx-XX")
        assert "Hola Jordi!" in out
        assert "Benvingut" in out

    def test_env_var_default(self, cli, monkeypatch):
        """Si no es passa lang, s'usa NEXE_LANG."""
        monkeypatch.setenv("NEXE_LANG", "es-ES")
        out = cli.greet("Jordi")
        assert "Bienvenido" in out

    def test_env_var_missing_defaults_to_ca(self, cli, monkeypatch):
        monkeypatch.delenv("NEXE_LANG", raising=False)
        out = cli.greet("Jordi")
        assert "Benvingut" in out

    def test_greet_includes_ascii_art(self, cli):
        out = cli.greet("Jordi", lang="ca-ES")
        assert "Module Orchestrator" in out
