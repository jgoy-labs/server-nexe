"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/cli/test_g11_cli_env_lang.py
Description: #902 — `./nexe knowledge ingest` ha d'indexar en la MATEIXA llengua
             que serveix el servidor. El servidor carrega `.env` a l'arrencada
             (core/server/runner.py:30); el CLI no ho feia i llegia NEXE_LANG
             només de l'entorn del procés, caient a "en" mentre el `.env` de la
             instal·lació deia `ca` → knowledge/ s'indexava a la llengua
             equivocada (i el bundle, des de #902, ja porta el llançador).

             Gate: amb `.env` que diu NEXE_LANG=ca i SENSE NEXE_LANG a
             l'entorn del procés, la ruta resolta ha de ser knowledge/ca.
             Mutació que ha de matar-lo: tornar a `os.getenv("NEXE_LANG", "en")`
             sec (sense llegir el `.env`) → vermell.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from core.cli.cli import _resolve_knowledge_path, app


@pytest.fixture(autouse=True)
def _isolated_environ():
    """`load_dotenv` escriu a `os.environ` DIRECTAMENT — monkeypatch no ho desfà.

    Sense aquesta restauració, el NEXE_LANG del `.env` de prova es quedaria
    enganxat al procés de pytest i contaminaria qualsevol test posterior que
    llegeixi la llengua (mutació d'estat process-wide per un test aliè).
    """
    _before = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(_before)


def _project(tmp_path: Path, env_body: str | None, *langs: str) -> Path:
    """Munta un project_root de mentida: `.env` opcional + knowledge/<lang>/."""
    if env_body is not None:
        (tmp_path / ".env").write_text(env_body, encoding="utf-8")
    for lang in langs:
        (tmp_path / "knowledge" / lang).mkdir(parents=True)
    return tmp_path


class TestG11KnowledgeLangFromDotenv:
    """#902: la llengua d'ingesta surt del `.env` quan l'entorn no la diu."""

    def test_dotenv_lang_wins_over_the_en_default(self, tmp_path, monkeypatch):
        """El cas del defecte: instal·lació en català, CLI sense NEXE_LANG."""
        monkeypatch.delenv("NEXE_LANG", raising=False)
        root = _project(tmp_path, "NEXE_LANG=ca\n", "ca", "en")

        assert _resolve_knowledge_path(root) == root / "knowledge" / "ca", (
            "#902: el CLI ha ignorat el .env i ha indexat en la llengua per defecte"
        )

    def test_process_environment_still_wins_over_the_dotenv(self, tmp_path, monkeypatch):
        """`load_dotenv` NO sobreescriu: qui exporta NEXE_LANG mana (el llançador
        del bundle i el Tauri parent ho fan). El `.env` només omple el buit."""
        monkeypatch.setenv("NEXE_LANG", "es")
        root = _project(tmp_path, "NEXE_LANG=ca\n", "ca", "es")

        assert _resolve_knowledge_path(root) == root / "knowledge" / "es"

    def test_without_dotenv_and_without_env_it_is_english(self, tmp_path, monkeypatch):
        """Comportament previ intacte quan no hi ha `.env`."""
        monkeypatch.delenv("NEXE_LANG", raising=False)
        root = _project(tmp_path, None, "en", "ca")

        assert _resolve_knowledge_path(root) == root / "knowledge" / "en"

    def test_missing_language_subdir_falls_back_to_knowledge_root(self, tmp_path, monkeypatch):
        """Instal·lacions antigues (knowledge/ pla, sense subdirectori de llengua)
        han de continuar ingerint — el `.env` no els pot trencar la ruta."""
        monkeypatch.delenv("NEXE_LANG", raising=False)
        root = tmp_path
        (root / ".env").write_text("NEXE_LANG=ca\n", encoding="utf-8")
        (root / "knowledge").mkdir()

        assert _resolve_knowledge_path(root) == root / "knowledge"

    def test_a_dotenv_without_the_key_does_not_break_resolution(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEXE_LANG", raising=False)
        root = _project(tmp_path, "NEXE_PRIMARY_API_KEY=x\n", "en")

        assert _resolve_knowledge_path(root) == root / "knowledge" / "en"


class TestG11CommandUsesTheResolver:
    """El comand real ha de fer servir el resolutor — si en manté una segona
    lectura pròpia de NEXE_LANG, el `.env` torna a quedar sense efecte."""

    def test_ingest_command_reports_the_resolved_path(self, tmp_path, monkeypatch):
        """Conduït pel comand real (`nexe knowledge ingest`): el path que
        imprimeix quan no existeix és EL QUE torna el resolutor, no un altre."""
        target = tmp_path / "knowledge" / "ca"
        monkeypatch.setattr(
            "core.cli.cli._resolve_knowledge_path", lambda _root: target
        )

        result = CliRunner().invoke(app, ["knowledge", "ingest"])

        assert result.exit_code == 0, result.output
        assert str(target) in result.output, (
            "el comand no fa servir la ruta que resol _resolve_knowledge_path"
        )
