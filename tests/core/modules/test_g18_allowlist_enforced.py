"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/modules/test_g18_allowlist_enforced.py
Description: #934 — l'allowlist de mòduls es podia anul·lar SENCERA sense que
             cap test caigués. Mutació reproduïda el 24/08 sobre
             `_configure_plugin_allowlist` (`effective_allowlist = None`
             incondicional): tests/core/modules/ + els fitxers del repo que
             parlen d'allowlist → **437 passed**, cap vermell.

             Per què cap el caçava: els tests d'allowlist que hi havia miren
             l'estat d'un `module_manager` que sovint no existeix (skip) o
             comproven que un mòdul inventat no és a la llista de carregats —
             cap no exercita la funció que DECIDEIX.

             Aquest gate la fa decidir. I hi entra per `_configure_plugin_allowlist()`
             a posta: fabricar l'`allowlist_config` a mà deixaria fora justament la
             línia on vivia el defecte (premissa fabricada, §5.3).

             Mutacions que l'han de matar: anul·lar l'allowlist a la config,
             treure el bloc de validació de `_check_plugin_security`, o deixar
             que el nom de core module doni confiança sense verificar el path.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.modules.core_modules import get_core_modules
from core.modules.plugin_loader import PluginLoaderMixin
from core.modules.types import SecurityCheckContext
from personality.data.models import ModuleState

REPO = Path(__file__).resolve().parents[3]


class _Loader(PluginLoaderMixin):
    """El mínim que `_configure_plugin_allowlist` necessita del ModuleManager."""

    def __init__(self, config: dict | None = None):
        self.config_manager = SimpleNamespace(get_config=lambda: config or {})


class _SecurityLogger:
    def __init__(self):
        self.rejected = []

    def log_module_rejected(self, module_name: str, reason: str):
        self.rejected.append((module_name, reason))


def _decide(loader: _Loader, name: str, path, *, project_root=REPO, app=None):
    """Recorre el camí sencer: configurar l'allowlist → decidir sobre un mòdul."""
    config = loader._configure_plugin_allowlist()
    config["project_root"] = project_root
    info = SimpleNamespace(enabled=True, state=ModuleState.LOADED, path=path)
    ctx = SecurityCheckContext(
        app=app or SimpleNamespace(state=SimpleNamespace()),
        module_name=name,
        module_info=info,
        allowlist_config=config,
    )
    return loader._check_plugin_security(ctx), info


@pytest.fixture
def allowlist(monkeypatch):
    """Una allowlist REAL i estreta: només `web_ui_module` hi és aprovat."""
    monkeypatch.setenv("NEXE_ENV", "production")
    monkeypatch.setenv("NEXE_APPROVED_MODULES", "web_ui_module")
    return _Loader()


class TestG18TheAllowlistActuallyRejects:

    def test_a_module_outside_the_allowlist_is_rejected(self, allowlist):
        ok, info = _decide(allowlist, "hacker_module_12345", REPO / "plugins" / "hacker_module_12345")

        assert ok is False, (
            "#934: un mòdul que NO és a l'allowlist ha passat la comprovació de "
            "seguretat — l'allowlist no s'està aplicant"
        )
        assert info.enabled is False, "el mòdul rebutjat ha de quedar deshabilitat"
        assert info.state == ModuleState.DISABLED, "i el seu estat ho ha de dir"

    def test_an_approved_module_is_admitted(self, allowlist):
        """Control invers: no s'hi val bloquejar-ho tot per posar-se verd."""
        ok, info = _decide(allowlist, "web_ui_module", REPO / "plugins" / "web_ui_module")

        assert ok is True, "un mòdul aprovat ha de passar"
        assert info.enabled is True

    def test_the_rejection_reaches_the_security_logger(self, allowlist):
        """Un rebuig que no deixa rastre no es pot auditar després."""
        logger = _SecurityLogger()
        app = SimpleNamespace(state=SimpleNamespace(security_logger=logger))

        _decide(allowlist, "hacker_module_12345", REPO / "plugins" / "hacker_module_12345", app=app)

        assert logger.rejected, "#934: el rebuig no ha arribat al security_logger"
        assert logger.rejected[0][0] == "hacker_module_12345"


class TestG18CoreTrustIsPathVerified:
    """WS4-01: el nom de core module no dóna confiança; el path canònic sí."""

    def test_a_core_module_at_its_canonical_path_is_admitted(self, allowlist):
        """`security` no és a l'allowlist d'aquest test i tot i així ha d'entrar."""
        assert "security" in get_core_modules()

        ok, _ = _decide(allowlist, "security", REPO / "plugins" / "security")

        assert ok is True, (
            "un mòdul intern al seu path canònic ha d'entrar encara que "
            "l'allowlist explícita no el nomeni"
        )

    def test_a_directory_named_like_a_core_module_elsewhere_is_rejected(self, allowlist, tmp_path):
        """El mateix nom, plantat en un altre lloc: no hereta la confiança."""
        impostor = tmp_path / "plugins" / "security"
        impostor.mkdir(parents=True)

        ok, info = _decide(allowlist, "security", impostor)

        assert ok is False, (
            "WS4-01: un directori que només ES DIU com un mòdul core ha heretat "
            "la seva confiança des de fora del path canònic"
        )
        assert info.state == ModuleState.DISABLED


class TestG18TheNoAllowlistPathIsDeliberate:
    """Sense allowlist tot passa — i això és volgut, no el defecte de #934."""

    def test_development_without_an_allowlist_loads_everything(self, monkeypatch):
        # `NEXE_ENV=development` tot sol NO basta: get_module_allowlist fa
        # `sidecar_is_prod or raw_env_is_prod`, i el singleton de SidecarConfig
        # vota production. És fail-closed i està bé; per mesurar el camí de
        # desenvolupament cal fer callar les DUES fonts.
        monkeypatch.setenv("NEXE_ENV", "development")
        monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
        import core.sidecar_config as sidecar
        monkeypatch.setattr(sidecar, "get_sidecar_config",
                            lambda: SimpleNamespace(is_production=False))

        config = _Loader()._configure_plugin_allowlist()

        assert config["effective_allowlist"] is None, (
            "sense allowlist configurada el loader carrega tot el que descobreix: "
            "és el camí de desenvolupament, i per això #934 necessitava un gate "
            "sobre el camí en què SÍ que n'hi ha"
        )

    def test_production_refuses_to_run_without_an_allowlist(self, monkeypatch):
        """Control d'abast del test de sobre: a producció no s'hi arriba."""
        monkeypatch.setenv("NEXE_ENV", "production")
        monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)

        with pytest.raises(ValueError, match="NEXE_APPROVED_MODULES"):
            _Loader()._configure_plugin_allowlist()
