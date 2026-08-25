"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/installer/test_g20_privacy_gate_by_nature.py
Description: #930 — el privacy gate deia «✅ net» amb 26 KB de material intern
             dins el bundle. Reproduït el 24/08 executant el bloc rsync real
             sobre DEV: `_tmp/_diari_mc028.md`, `_tmp/mc028-turing-material.md`,
             `findings.db` i QUATRE fitxers a
             `plugins/web_ui_module/ui/uploads/` — i el gate, verd.

             La causa és la mateixa dues vegades: el build filtra per DENYLIST
             i el gate també ENUMERA. Enumerar prohibits no pot tancar això,
             perquè el següent fitxer intern que algú creï tampoc serà a la
             llista. Els quatre uploads ho demostren: ningú els havia enumerat
             mai, i els va trobar comparar el bundle amb el REPOSITORI.

             El gate pregunta ara «això és producte?» en comptes de «és una de
             les coses dolentes conegudes?». Aquests controls l'executen de
             veritat sobre arbres fabricats, i vigilen que el build el segueixi
             cridant amb el repo font: sense aquell argument, la comprovació
             per naturalesa no corre i el gate torna a ser el d'abans.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APP_REPO = REPO.parent / "nexe-app"
GATE = APP_REPO / "scripts" / "verify-privacy-gate.sh"
BUILD = APP_REPO / "scripts" / "build-sidecar.sh"

_needs_sibling = pytest.mark.skipif(
    not APP_REPO.is_dir(),
    reason="el repo germà nexe-app no és present (clon OSS de server-nexe sol)",
)
_needs_posix = pytest.mark.skipif(
    sys.platform.startswith("win") or shutil.which("git") is None,
    reason="el gate és un script POSIX i necessita git",
)


def _fake_repo(root: Path, tracked: dict[str, str]) -> None:
    """Un repo git de mentida amb uns quants fitxers versionats."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)  # nosec B603 B607
    for rel, content in tracked.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)  # nosec B603 B607
    subprocess.run(  # nosec B603 B607
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=root, check=True,
    )


def _run_gate(app_dir: Path, source_repo: Path | None = None):
    args = ["bash", str(GATE), str(app_dir)]
    if source_repo is not None:
        args.append(str(source_repo))
    return subprocess.run(args, capture_output=True, text=True)  # nosec B603 B607


@_needs_sibling
@_needs_posix
class TestG20TheGateAsksWhetherItIsProduct:

    def test_it_catches_a_file_the_repo_does_not_track(self, tmp_path):
        """El cas de #930, i el de qualsevol fitxer que encara no existeix."""
        repo = tmp_path / "repo"
        _fake_repo(repo, {"core/app.py": "codi\n"})
        app = tmp_path / "app"
        (app / "core").mkdir(parents=True)
        (app / "core" / "app.py").write_text("codi\n", encoding="utf-8")
        (app / "_tmp").mkdir()
        (app / "_tmp" / "diari_intern.md").write_text("notes internes\n", encoding="utf-8")

        proc = _run_gate(app, repo)

        assert proc.returncode == 1, (
            f"#930: material intern dins el bundle i el gate diu que està net:\n{proc.stdout}"
        )
        assert "_tmp/diari_intern.md" in proc.stderr

    def test_it_catches_a_user_document_in_uploads(self, tmp_path):
        """El cas que ningú havia enumerat: uploads/ és on van els documents."""
        repo = tmp_path / "repo"
        _fake_repo(repo, {"plugins/web_ui_module/ui/index.html": "<html></html>\n"})
        app = tmp_path / "app"
        uploads = app / "plugins" / "web_ui_module" / "ui" / "uploads"
        uploads.mkdir(parents=True)
        (app / "plugins" / "web_ui_module" / "ui" / "index.html").write_text(
            "<html></html>\n", encoding="utf-8")
        (uploads / "factura_client.pdf").write_text("dades del client\n", encoding="utf-8")

        proc = _run_gate(app, repo)

        assert proc.returncode == 1, (
            "un document d'usuari dins el bundle ha de tombar el build"
        )
        assert "factura_client.pdf" in proc.stderr

    def test_a_clean_bundle_passes(self, tmp_path):
        """Control invers: no s'hi val bloquejar-ho tot."""
        repo = tmp_path / "repo"
        _fake_repo(repo, {"core/app.py": "codi\n", "knowledge/ca/doc.md": "doc\n"})
        app = tmp_path / "app"
        for rel in ("core/app.py", "knowledge/ca/doc.md"):
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("codi\n" if rel.endswith(".py") else "doc\n", encoding="utf-8")

        proc = _run_gate(app, repo)

        assert proc.returncode == 0, f"un bundle net no pot fallar:\n{proc.stderr}"

    def test_declared_build_artefacts_are_allowed(self, tmp_path):
        """Els artefactes que hi posa el propi build no són intrusos."""
        repo = tmp_path / "repo"
        _fake_repo(repo, {"core/app.py": "codi\n"})
        app = tmp_path / "app"
        (app / "core").mkdir(parents=True)
        (app / "core" / "app.py").write_text("codi\n", encoding="utf-8")
        (app / "app.py").write_text("entry point\n", encoding="utf-8")
        (app / ".fastembed_cache").mkdir()
        (app / ".fastembed_cache" / "model.onnx").write_text("pes\n", encoding="utf-8")
        (app / "knowledge" / ".embeddings").mkdir(parents=True)
        (app / "knowledge" / ".embeddings" / "ca.npz").write_text("vectors\n", encoding="utf-8")

        proc = _run_gate(app, repo)

        assert proc.returncode == 0, (
            f"els artefactes declarats del build han de poder viatjar:\n{proc.stderr}"
        )

    def test_without_the_source_repo_the_check_does_not_run(self, tmp_path):
        """Documenta el límit: sense repo font, el gate torna a enumerar.

        Per això el control de sota vigila que el build SEMPRE l'hi passi.
        """
        repo = tmp_path / "repo"
        _fake_repo(repo, {"core/app.py": "codi\n"})
        app = tmp_path / "app"
        (app / "_tmp").mkdir(parents=True)
        (app / "_tmp" / "diari_intern.md").write_text("notes\n", encoding="utf-8")

        assert _run_gate(app).returncode == 0
        assert _run_gate(app, repo).returncode == 1


@_needs_sibling
class TestG20TheBuildKeepsAskingByNature:
    """Un gate que existeix però que el build crida a mitges no protegeix res."""

    def test_the_build_runs_the_gate_with_the_source_repo(self):
        text = BUILD.read_text(encoding="utf-8")
        assert '"$SCRIPT_DIR/verify-privacy-gate.sh" "$SIDECAR_DIR/app" "$APP_SOURCE_DIR"' in text, (
            "#930: el build ja no passa el repo font al privacy gate — la "
            "comprovació per naturalesa deixa de córrer i el gate torna a ser "
            "una denylist"
        )

    def test_the_gate_runs_before_the_build_generates_anything(self):
        """L'ordre és el que fa exacta la mesura: rsync → gate → artefactes."""
        text = BUILD.read_text(encoding="utf-8")
        gate_by_nature = text.index('"$SIDECAR_DIR/app" "$APP_SOURCE_DIR"')
        first_artefact = text.index('FASTEMBED_STAGING="$SIDECAR_DIR/app/.fastembed_cache"')
        assert gate_by_nature < first_artefact, (
            "el gate per naturalesa ha de córrer ABANS que el build comenci a "
            "posar artefactes dins app/, o necessitarà una llista d'excepcions "
            "— que és l'enumeració que #930 va demostrar que no tanca res"
        )

    def test_the_build_no_longer_copies_the_internal_material(self):
        """Defensa en profunditat: el gate caça, però el build no ho ha de copiar."""
        text = BUILD.read_text(encoding="utf-8")
        for pattern in ("--exclude='/_tmp'", "--exclude='/findings.db'",
                        "--exclude='/plugins/web_ui_module/ui/uploads/**'"):
            assert pattern in text, f"#930: el rsync ha perdut {pattern}"

    def test_the_windows_path_excludes_the_same_things(self):
        """Paritat declarada per l'script: les dues branques diuen el mateix."""
        text = BUILD.read_text(encoding="utf-8")
        start = text.index('cp -R "$APP_SOURCE_DIR/." "$SIDECAR_DIR/app/"')
        prune = text[start:text.index("Windows copy+prune done", start)]
        assert "_tmp" in prune and "findings.db" in prune, (
            "#930 arreglat a macOS i viu a Windows: el prune ha de treure el mateix"
        )
        assert "plugins/web_ui_module/ui/uploads" in prune, (
            "el camí Windows no buida el directori d'uploads"
        )
