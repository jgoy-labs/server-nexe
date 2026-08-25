"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/plugins/security/test_g16_cors_ssl_real_source.py
Description: #865 — el check de seguretat web auditava variables fantasma.
             Llegia `NEXE_CORS_ORIGINS`, que NO existeix enlloc del producte
             (grep a tot el repo: només el check i els seus propis tests), i
             `NEXE_SSL_CERT`, quan no hi ha SSL enlloc (`certfile`/`ssl_keyfile`
             = zero aparicions). Resultat: un check que sempre deia «CORS no
             configurat» encara que server.toml el tingués restringit, i que mai
             hauria vist un `cors_origins = ["*"]` de debò.

             La font que MANA és la que aplica `core/middleware.py:setup_cors`:
             `SidecarConfig.cors_origins` en mode sidecar i, si no,
             `config["core"]["server"]["cors_origins"]` de server.toml.

             🔴 DESCARTAT EXPRESSAMENT PER JORDI: cablejar `NEXE_CORS_ORIGINS`
             com a env var real — seria una segona font de veritat, just el que
             #918 acaba de decidir evitar.

             Mutacions que l'han de matar: tornar a llegir l'env var → vermell;
             tornar a posar el check d'SSL → vermell.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plugins.security.checks.web_security_check import WebSecurityCheck


def _project(tmp_path: Path, toml_body: str | None) -> Path:
    if toml_body is not None:
        (tmp_path / "server.toml").write_text(toml_body, encoding="utf-8")
    return tmp_path


def _cors(findings: list) -> list:
    return [f for f in findings if "CORS" in f["title"]]


@pytest.fixture(autouse=True)
def _no_ghost_env(monkeypatch):
    """Les variables fantasma no han de decidir res — ni quan hi són."""
    monkeypatch.delenv("NEXE_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("NEXE_SSL_CERT", raising=False)
    monkeypatch.delenv("NEXE_ENV", raising=False)


class TestG16CorsReadsTheRealSource:

    def test_restricted_server_toml_is_not_reported(self, tmp_path):
        """#865: CORS restringit a la font real i cap fantasma a l'entorn →
        el check ha de callar. Abans deia «CORS origins not configured»."""
        root = _project(tmp_path, '[core.server]\ncors_origins = ["https://example.com"]\n')

        findings = WebSecurityCheck(project_root=root).run()

        assert not _cors(findings), (
            f"#865: CORS està restringit a server.toml i el check el reporta igual: {_cors(findings)}"
        )

    def test_a_real_wildcard_is_reported_high(self, tmp_path):
        """L'altra cara: obert de debò a la font real → HIGH.
        L'env var «segura» no pot tapar-ho (era el forat de #865)."""
        root = _project(tmp_path, '[core.server]\ncors_origins = ["*"]\n')

        with patch.dict("os.environ", {"NEXE_CORS_ORIGINS": "https://segur.example"}):
            findings = WebSecurityCheck(project_root=root).run()

        hits = _cors(findings)
        assert hits, "#865: CORS obert a la font real i el check no el veu"
        assert hits[0]["severity"] == "HIGH", hits

    def test_no_origins_configured_is_reported_medium(self, tmp_path):
        root = _project(tmp_path, '[core.server]\ncors_origins = []\n')

        hits = _cors(WebSecurityCheck(project_root=root).run())

        assert hits and hits[0]["severity"] == "MEDIUM", hits

    def test_sidecar_config_wins_like_setup_cors_does(self, tmp_path):
        """Paritat amb `core/middleware.py:setup_cors`: en mode sidecar mana
        SidecarConfig, no server.toml. Si el check mirés només el TOML, diria
        «obert» d'una instal·lació Tauri perfectament restringida."""
        root = _project(tmp_path, '[core.server]\ncors_origins = ["*"]\n')
        cfg = MagicMock()
        cfg.is_sidecar = True
        cfg.cors_origins = ["tauri://localhost", "http://localhost:1420"]

        with patch("core.sidecar_config.get_sidecar_config", return_value=cfg):
            findings = WebSecurityCheck(project_root=root).run()

        assert not _cors(findings), (
            f"#865: en mode sidecar mana SidecarConfig i el check mira una altra cosa: {_cors(findings)}"
        )


    def test_a_broken_sidecar_config_does_not_blind_the_check(self, tmp_path):
        """§1.8: si `get_sidecar_config()` peta, el check no es pot quedar cec —
        cau a server.toml, igual que fa `setup_cors` amb el seu try/except."""
        root = _project(tmp_path, '[core.server]\ncors_origins = ["*"]\n')

        with patch("core.sidecar_config.get_sidecar_config",
                   side_effect=RuntimeError("sidecar config boom")):
            hits = _cors(WebSecurityCheck(project_root=root).run())

        assert hits and hits[0]["severity"] == "HIGH", (
            "amb SidecarConfig trencat el check ha deixat de veure el CORS obert"
        )


class TestG16SslCheckIsRetired:

    # Directoris de codi de producte (allowlist, vegeu el docstring de sota).
    PRODUCT_DIRS = ("core", "memory", "plugins", "personality", "installer", "scripts")

    def test_production_without_a_certificate_says_nothing(self, tmp_path):
        """#865: no hi ha SSL al producte (local-first, loopback) i el check
        n'exigia un en producció. Retirat."""
        root = _project(tmp_path, '[core.server]\ncors_origins = ["https://example.com"]\n')

        with patch.dict("os.environ", {"NEXE_ENV": "production"}):
            findings = WebSecurityCheck(project_root=root).run()

        assert not [f for f in findings if "SSL" in f["title"]], findings

    def test_the_repo_really_has_no_ssl_surface(self):
        """El motiu de retirar-lo, mesurat aquí i no en un comentari: si algú
        introdueix SSL de debò, aquest test cau i obliga a repensar el check.

        Es mira amb una ALLOWLIST dels directoris de producte, no amb una
        denylist de caches: una denylist sempre acaba tenint un forat (el
        primer intent d'aquest gate mesurava `InstallNexe.app` i `.mypy_cache`,
        que porten CPython i tipus de tercers). El control d'abast de sota
        vigila que l'allowlist no s'encongeixi en silenci.
        """
        import subprocess
        root = Path(__file__).resolve().parents[3]
        targets = [d for d in self.PRODUCT_DIRS if (root / d).is_dir()]
        out = subprocess.run(  # nosec B603 B607: grep from PATH over the repo itself
            ["grep", "-rIl", "--exclude-dir=__pycache__",
             "-e", "ssl_keyfile", "-e", "ssl_certfile", "-e", "certfile", *targets],
            capture_output=True, text=True, cwd=str(root),
        )
        assert not out.stdout.strip(), (
            "el producte ja té superfície SSL: el check retirat a #865 s'ha de "
            f"repensar, no ressuscitar tal qual.\n{out.stdout}"
        )

    def test_the_ssl_scan_still_covers_the_product(self):
        """Control d'abast: si algú retalla PRODUCT_DIRS o mou el codi, el gate
        de sobre passaria per no mirar res.

        Descobert del repositori, no comparat contra si mateix (#932): un
        llindar (`>= 5 de 6`) — o fins i tot una igualtat contra
        `PRODUCT_DIRS` — toleren que la pròpia llista s'encongeixi, perquè
        `present` es calcula FILTRANT `PRODUCT_DIRS`: numerador i denominador
        es mouen junts i cap mida ni cap comparació interna ho detecta.
        La font real: quins directoris de primer nivell porten codi Python
        VERSIONAT (`git ls-files`), exclosos els que no són producte per
        naturalesa (tests, CI, eines de dev) — no per nom, mateix esperit que
        l'allowlist de sota."""
        import subprocess
        root = Path(__file__).resolve().parents[3]
        NOT_PRODUCT = {"tests", ".github", "dev-tools"}
        out = subprocess.run(  # nosec B603 B607: git from PATH over the repo itself
            ["git", "ls-files", "--", "*.py"],
            capture_output=True, text=True, cwd=str(root),
        )
        tracked_py_dirs = {
            line.split("/", 1)[0] for line in out.stdout.splitlines() if "/" in line
        }
        missing = (tracked_py_dirs - NOT_PRODUCT) - set(self.PRODUCT_DIRS)
        assert not missing, (
            f"codi Python versionat fora de l'escaneig SSL: {missing} "
            f"(PRODUCT_DIRS={self.PRODUCT_DIRS})"
        )


class TestG16TheRestOfTheCheckSurvives:
    """Control d'abast (§1.7): no s'hi val buidar el check per posar-lo verd."""

    def test_the_other_two_checks_still_report(self, tmp_path):
        root = _project(tmp_path, '[core.server]\ncors_origins = ["https://example.com"]\n')

        titles = [f["title"].lower() for f in WebSecurityCheck(project_root=root).run()]

        assert any("detector" in t for t in titles), titles
        assert any("sanitizer" in t for t in titles), titles
