"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/installer/test_g11b_bundle_launcher.py
Description: #902 — el llançador (`nexe`) i la seva referència (`COMMANDS.md`)
             han d'entrar al bundle del sidecar. El bundle real del 02/08
             (nexe-app/target/sidecar/app/) NO els tenia: build-sidecar.sh els
             excloïa explícitament del rsync, i sense llançador dins el bundle
             ningú pot re-ingestar knowledge/ des d'una instal·lació.

             El gate NO llegeix l'script buscant text: EXECUTA el bloc rsync
             real sobre un arbre de mentida i mira l'ARTEFACTE que en surt —
             que és el que s'envia. Mutació que l'ha de matar: tornar a posar
             `--exclude='/nexe'` → vermell.

             Ubicació: aquest test viu a server-nexe i no a nexe-app perquè
             nexe-app no té suite pytest (ni tests/, ni pytest.ini, ni conftest)
             — allà el gate no el cridaria ningú («gate declarat però no
             executat»). El pont cap al repo germà queda vigilat pel primer
             test de la classe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APP_REPO = REPO.parent / "nexe-app"
SCRIPT = APP_REPO / "scripts" / "build-sidecar.sh"

# Excludes que el bloc rsync porta avui (43 abans de #902, menys /nexe i
# /COMMANDS.md). Control d'abast (§1.7): si algú retalla la denylist, aquest
# número baixa i el gate es queixa sol; si algú n'afegeix una de nova que es
# torni a menjar el llançador, el test funcional de sota es posa vermell.
_MIN_EXCLUDES = 41

# Fitxers que el bundle NO pot portar mai (privacitat / contaminació DEV).
# Es comproven sobre la còpia produïda, no sobre el text de l'script.
_MUST_NOT_SHIP = ("storage/secret.txt", ".env", "tests/test_x.py",
                  "venv/bin/python3", ".git/config", "docs/x.md",
                  "scripts/build.sh", "node_modules/pkg/index.js")

# Fitxers que el bundle SÍ ha de portar (#902 + el que ja hi anava).
_MUST_SHIP = ("nexe", "COMMANDS.md", "core/cli/cli.py", "knowledge/ca/doc.md")


def _extract_rsync_block(text: str) -> str:
    """Retorna el bloc `rsync -a … "$APP_SOURCE_DIR/." "$SIDECAR_DIR/app/"`.

    Es talla per continuació de línia (`\\`), no per número de línia, perquè
    la denylist creix i encongeix a cada release.
    """
    lines = text.splitlines()
    blocks = []
    for start, ln in enumerate(lines):
        if not ln.strip().startswith("rsync -a"):
            continue
        i, block = start, []
        while True:
            block.append(lines[i])
            if not lines[i].rstrip().endswith("\\"):
                break
            i += 1
        blocks.append("\n".join(block))
    # L'script té més d'un rsync (el del PBS a python-runtime/ és un altre):
    # el que ens interessa és el que copia el codi de l'app al bundle.
    app_copy = [b for b in blocks
                if '"$APP_SOURCE_DIR/." "$SIDECAR_DIR/app/"' in b.splitlines()[-1]]
    assert len(app_copy) == 1, (
        f"esperava UN sol rsync que copiï APP_SOURCE_DIR a SIDECAR_DIR/app, "
        f"n'hi ha {len(app_copy)} (de {len(blocks)} blocs rsync): el gate "
        "estaria mesurant una altra cosa"
    )
    return app_copy[0]


def _make_fake_source(root: Path) -> None:
    """Arbre de mentida amb el que ha d'entrar i el que no."""
    for rel in _MUST_SHIP + _MUST_NOT_SHIP:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"contingut de {rel}\n", encoding="utf-8")
    (root / "nexe").chmod(0o755)


def _run_rsync_block(tmp_path: Path) -> Path:
    """Executa el bloc rsync REAL de l'script i torna el directori `app/`."""
    src = tmp_path / "src"
    dst = tmp_path / "sidecar"
    src.mkdir()
    (dst / "app").mkdir(parents=True)
    _make_fake_source(src)

    block = _extract_rsync_block(SCRIPT.read_text(encoding="utf-8"))
    script = (
        'set -euo pipefail\n'
        f'APP_SOURCE_DIR="{src}"\n'
        f'SIDECAR_DIR="{dst}"\n'
        f'{block}\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)  # nosec B603 B607: bash from PATH, script built from the repo's own build file
    assert proc.returncode == 0, f"el bloc rsync ha petat:\n{proc.stdout}\n{proc.stderr}"
    return dst / "app"


_needs_sibling = pytest.mark.skipif(
    not APP_REPO.is_dir(),
    reason="el repo germà nexe-app no és present (clon OSS de server-nexe sol)",
)
_needs_rsync = pytest.mark.skipif(
    shutil.which("rsync") is None or sys.platform.startswith("win"),
    reason="el bloc mesurat és el POSIX; a Windows l'script fa copy+prune (test de paritat a part)",
)


class TestG11bBundleShipsTheLauncher:

    def test_the_build_script_is_where_the_gate_expects_it(self):
        """Si el repo germà hi és, l'script ha d'existir: si algú el mou o el
        rebateja, el gate es quedaria mut per skip i ningú ho sabria."""
        if not APP_REPO.is_dir():
            pytest.skip("el repo germà nexe-app no és present")
        assert SCRIPT.is_file(), (
            f"nexe-app existeix però {SCRIPT} no: el gate de #902 quedaria sense res a mesurar"
        )

    @_needs_sibling
    @_needs_rsync
    def test_the_produced_bundle_carries_the_launcher(self, tmp_path):
        """#902, sobre l'ARTEFACTE: `app/nexe` i `app/COMMANDS.md` hi són."""
        app = _run_rsync_block(tmp_path)

        assert (app / "nexe").is_file(), (
            "#902: el bundle produït no porta el llançador `nexe` "
            "(sense ell no es pot re-ingestar knowledge/ des d'una instal·lació)"
        )
        assert (app / "COMMANDS.md").is_file(), (
            "#902: el bundle produït no porta COMMANDS.md (la referència del llançador)"
        )

    @_needs_sibling
    @_needs_rsync
    def test_the_launcher_keeps_its_executable_bit(self, tmp_path):
        """Un llançador sense permís d'execució és un llançador que no llança."""
        app = _run_rsync_block(tmp_path)
        import os
        assert os.access(app / "nexe", os.X_OK), (
            "#902: `nexe` ha arribat al bundle sense bit d'execució"
        )

    @_needs_sibling
    @_needs_rsync
    def test_privacy_denylist_still_bites(self, tmp_path):
        """Fer entrar el llançador no pot obrir la porta a res més."""
        app = _run_rsync_block(tmp_path)
        colats = [rel for rel in _MUST_NOT_SHIP if (app / rel).exists()]
        assert not colats, f"el bundle produït porta el que no ha de portar: {colats}"

    @_needs_sibling
    @_needs_rsync
    def test_the_rest_of_the_app_still_ships(self, tmp_path):
        """Control invers: la còpia continua duent el codi i knowledge/."""
        app = _run_rsync_block(tmp_path)
        for rel in ("core/cli/cli.py", "knowledge/ca/doc.md"):
            assert (app / rel).is_file(), f"el bundle produït ha perdut {rel}"

    @_needs_sibling
    def test_the_denylist_has_not_been_trimmed(self):
        """Control d'abast (§1.7): la denylist no pot encongir en silenci."""
        block = _extract_rsync_block(SCRIPT.read_text(encoding="utf-8"))
        n = block.count("--exclude=")
        assert n >= _MIN_EXCLUDES, (
            f"la denylist del rsync ha baixat a {n} excludes (mínim registrat "
            f"{_MIN_EXCLUDES}): algú n'ha tret una — revisa què s'hi ha colat"
        )


class TestG11bWindowsPathParity:
    """L'script declara «denylist parity with rsync» al camí Windows (copy+prune).
    Si el prune de Windows continua esborrant el llançador, #902 queda arreglat
    a mitges: el bundle Windows seguiria sortint sense `COMMANDS.md`."""

    @_needs_sibling
    def test_windows_prune_does_not_delete_what_rsync_now_ships(self):
        text = SCRIPT.read_text(encoding="utf-8")
        start = text.index('cp -R "$APP_SOURCE_DIR/." "$SIDECAR_DIR/app/"')
        prune = text[start:text.index("Windows copy+prune done", start)]
        tokens = prune.replace("\\\n", " ").split()
        for name in ("nexe", "COMMANDS.md"):
            assert name not in tokens, (
                f"#902: el camí Windows continua esborrant `{name}` del bundle "
                "(el rsync ja no ho fa: les dues branques han de dir el mateix)"
            )

    @_needs_sibling
    def test_windows_prune_still_removes_the_private_stuff(self):
        """Control d'abast del test de sobre: no s'hi val buidar el prune."""
        text = SCRIPT.read_text(encoding="utf-8")
        start = text.index('cp -R "$APP_SOURCE_DIR/." "$SIDECAR_DIR/app/"')
        prune = text[start:text.index("Windows copy+prune done", start)]
        tokens = prune.replace("\\\n", " ").split()
        # `venv` NO hi és a posta: el prune de Windows esborra `.venv` i
        # `.test_venv` però no `venv` (el rsync sí que l'exclou). És una
        # divergència REAL de la denylist, anterior a #902 i fora del seu abast
        # — queda reportada, no la tapa aquest gate.
        for name in ("storage", ".env", "tests", ".venv", ".git", "docs", "scripts"):
            assert name in tokens, (
                f"el prune de Windows ja no esborra `{name}`: la paritat de "
                "privacitat amb el rsync s'ha trencat"
            )


# ─── #902, segona meitat: el llançador ha de VIATJAR i ha d'ARRENCAR ───────────
#
# Els controls de sobre executen el bloc rsync real, però sobre un arbre sintètic
# que ES FABRICA el llançador (`_make_fake_source` escriu `nexe` i li posa el bit
# d'execució). Per això no van poder veure que `nexe` estava a `.gitignore:32` ni
# que dins el bundle no arrencava: un control que llegeix el directori de treball
# mesura la màquina de qui el corre, no el repositori.

_needs_git = pytest.mark.skipif(
    not (REPO / ".git").exists(),
    reason="sense .git no hi ha repositori a mesurar (tarball, no clon)",
)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO,  # nosec B603 B607: git from PATH, fixed args
                          capture_output=True, text=True)


def _launcher_as_it_travels() -> str:
    """El llançador TAL COM VIATJA: el blob de git, mai el fitxer del disc."""
    proc = _git("show", ":nexe")
    assert proc.returncode == 0, (
        "#902: `git show :nexe` no torna res — el llançador no és a l'índex de git"
    )
    return proc.stdout


def _fake_python(path: Path) -> None:
    """Un `python3` que no fa res més que dir amb què l'han cridat."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/bash\n"
        'echo "PY:$0"\n'
        'echo "ARGS:$*"\n'
        'echo "PYTHONPATH:${PYTHONPATH:-}"\n'
        'echo "PYTHONHOME:${PYTHONHOME:-}"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_launcher(where: Path, *args: str) -> subprocess.CompletedProcess:
    """Planta el llançador VERSIONAT a `where` i l'executa de veritat."""
    where.mkdir(parents=True, exist_ok=True)
    launcher = where / "nexe"
    launcher.write_text(_launcher_as_it_travels(), encoding="utf-8")
    launcher.chmod(0o755)
    return subprocess.run([str(launcher), *args],  # nosec B603: script written from the repo's own blob
                          capture_output=True, text=True)


def _said(proc: subprocess.CompletedProcess) -> dict:
    """El que el `python3` fals ha vist, amb els paths RESOLTS.

    El llançador passa `$DIR/../venv/...` tal qual (i fa bé: no li toca
    normalitzar res); qui compara és qui ha de resoldre.
    """
    out = {}
    for line in proc.stdout.splitlines():
        clau, _, valor = line.partition(":")
        out[clau] = valor
    return out


def _same(valor: str, esperat: Path) -> bool:
    return bool(valor) and Path(valor).resolve() == esperat.resolve()


class TestG11bTheLauncherTravels:
    """Que HI SIGUI: el build copia del directori de treball, no de git."""

    @_needs_git
    def test_the_launcher_is_versioned(self):
        assert _git("ls-files", "--error-unmatch", "nexe").returncode == 0, (
            "#902: `nexe` no està versionat. El build el copia del directori de "
            "treball, o sigui que qui tingui el seu local obté un bundle amb "
            "llançador i UN CLON NET EL TREU SENSE, en silenci"
        )

    @_needs_git
    def test_no_rule_ignores_the_launcher(self):
        """`--no-index` NO és decoració: sense ell aquest control no pot fallar.

        `git check-ignore` a seques no considera ignorat un fitxer que ja és a
        l'índex, o sigui que amb `nexe` versionat tornaria a dir «no ignorat»
        encara que algú reposés la regla — mesurat el 24/08. La regla i l'índex
        són dues coses: mentre totes dues no divergeixin ningú se n'adona, i el
        dia que algú faci `git rm --cached` el forat de #902 torna sencer.
        """
        proc = _git("check-ignore", "--no-index", "-v", "nexe")
        assert proc.returncode != 0, (
            f"#902: una regla torna a ignorar el llançador ({proc.stdout.strip()}): "
            "avui encara viatja perquè és a l'índex, però el primer `git rm --cached` "
            "el treu del bundle en silenci"
        )


def _section_start(text: str, header: str) -> int:
    """Índex de la capçalera de secció REAL (a principi de línia), no d'una
    menció dins un comentari."""
    match = re.search(rf"^{re.escape(header)}", text, re.M)
    assert match, f"{header} no és al .gitoss-sync: l'inventari ha canviat de format"
    return match.start()


class TestG11bTheLauncherReachesThePublicClone:
    """Tercera capa: viatjar al bundle no serveix si no arriba al públic.

    `.gitoss-sync` és l'inventari que decideix què pot pujar a GitHub, i tenia
    `nexe` a `[[exclude]]` sota «Binaris i builds» — el mateix error que el
    `.gitignore`, una capa més amunt. Versionat a DEV i exclòs de la publicació,
    un clon de GitHub hauria seguit produint un bundle sense llançador: #902
    arreglat a casa i viu a fora. Trobat el 24/08 creuant els fitxers de la
    sessió amb l'inventari.
    """

    @_needs_git
    def test_the_publication_inventory_does_not_exclude_the_launcher(self):
        # El tall ha de ser la SECCIÓ real, no la primera menció: la capçalera
        # del fitxer explica el format i ja escriu «[[exclude]]» dins un
        # comentari. Tallar per allà agafava el fitxer sencer i el control
        # denunciava la línia legítima de [sync] (mesurat 24/08).
        text = (REPO / ".gitoss-sync").read_text(encoding="utf-8")
        exclude = text[_section_start(text, "[[exclude]]"):]
        actives = [ln.strip() for ln in exclude.splitlines()
                   if ln.strip().startswith('"')]

        assert '"nexe",' not in actives, (
            "#902: el llançador torna a estar a [[exclude]] del .gitoss-sync — "
            "no arribaria mai al clon públic, i allà el bundle tornaria a sortir "
            "sense llançador"
        )

    @_needs_git
    def test_the_publication_inventory_lists_the_launcher(self):
        """No n'hi ha prou amb no excloure'l: la llista és una ALLOWLIST."""
        text = (REPO / ".gitoss-sync").read_text(encoding="utf-8")
        sync = text[:_section_start(text, "[[exclude]]")]

        assert '"nexe",' in sync, (
            "#902: `nexe` no consta a [sync].files del .gitoss-sync; l'inventari "
            "és una allowlist, o sigui que el que no hi surt no es publica"
        )


class TestG11bTheLauncherRuns:
    """Que ARRENQUI: el gate d'abans mirava que el fitxer hi fos, no que llancés."""

    def test_it_runs_in_the_bundle_layout(self, tmp_path):
        """Dins el sidecar el codi viu a `app/` i el venv és el seu germà."""
        sidecar = tmp_path / "sidecar"
        _fake_python(sidecar / "venv" / "bin" / "python3")
        (sidecar / "python-runtime").mkdir(parents=True)

        proc = _run_launcher(sidecar / "app", "knowledge", "ingest")

        assert proc.returncode == 0, (
            f"#902: el llançador no arrenca dins el bundle:\n{proc.stderr}"
        )
        vist = _said(proc)
        assert _same(vist.get("PY", ""), sidecar / "venv" / "bin" / "python3"), (
            f"#902: ha cridat un Python que no és el del bundle: {vist.get('PY')}"
        )
        assert vist.get("ARGS") == "-m core.cli knowledge ingest", (
            f"#902: els arguments de l'usuari no arriben al CLI: {vist.get('ARGS')}"
        )
        assert _same(vist.get("PYTHONPATH", "").split(":")[0], sidecar / "app"), (
            f"#902: el codi de l'app no encapçala el PYTHONPATH: {vist.get('PYTHONPATH')}"
        )
        assert _same(vist.get("PYTHONHOME", ""), sidecar / "python-runtime"), (
            "#902: sense PYTHONHOME, si el `home=` relatiu del pyvenv.cfg falla "
            f"el sidecar cau al Python del sistema: {vist.get('PYTHONHOME')}"
        )

    def test_it_runs_in_the_dev_layout(self, tmp_path):
        """Control invers: fer-lo arrencar al bundle no pot trencar el repo."""
        repo = tmp_path / "repo"
        _fake_python(repo / "venv" / "bin" / "python3")
        # Un venv germà que NO ha de guanyar mai al del repo.
        _fake_python(tmp_path / "venv" / "bin" / "python3")

        proc = _run_launcher(repo, "status")

        assert proc.returncode == 0, f"el llançador ha deixat d'arrencar a DEV:\n{proc.stderr}"
        vist = _said(proc)
        assert _same(vist.get("PY", ""), repo / "venv" / "bin" / "python3"), (
            f"a DEV ha de manar el venv del repo, no el germà: {vist.get('PY')}"
        )
        assert not vist.get("PYTHONHOME"), (
            f"a DEV no s'ha d'exportar cap PYTHONHOME: {vist.get('PYTHONHOME')}"
        )

    def test_it_fails_loudly_when_there_is_no_python(self, tmp_path):
        """El mode de fallada de #902 va ser el SILENCI, no l'error."""
        proc = _run_launcher(tmp_path / "enlloc", "knowledge", "ingest")

        assert proc.returncode != 0, (
            f"sense Python enlloc, el llançador ha de fallar:\n{proc.stdout}"
        )
        assert "no trobo el Python" in proc.stderr, (
            f"ha fallat sense dir per què (el silenci és el defecte de #902):\n{proc.stderr}"
        )
