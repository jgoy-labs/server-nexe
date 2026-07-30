"""
Test fix B261 (finding #834, P1): uiri/toml destrueix server.toml.

Causa arrel (reproduïda 2026-07-30): el paquet `toml` (uiri 0.10.2) rebutja la
seqüència `\\[` dins d'una multiline basic string i deixa de parsejar a mitja
lectura SENSE aixecar excepció — del server.toml real (39 claus fulla + 12
taules) en retorna 7. Qualsevol load→dump amb uiri (setup-models --apply,
model install, save_config via config_manager) reescrivia el fitxer de 203 a
10 línies i reobria la confabulació del system prompt.

Fix: lectura amb `tomllib` (stdlib) + escriptura amb `tomli_w` via
`core.config.atomic_toml_write` (serialitza abans de tocar disc, backup .bak,
temp + os.replace atòmic al mateix directori).

Gate del pla mestre 1.0.8: round-trip de les 51 claus del server.toml
REAL + igualtat char-a-char dels 6 prompts. Explícitament NO es fa gate de
paritat toml-vs-tomllib (nota del finding).
"""
import re
import shutil
import tomllib
from pathlib import Path

import pytest
import tomli_w

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_TOML = _REPO_ROOT / "personality" / "server.toml"

# Les 12 taules del server.toml canònic (B049 vigila les mortes; aquí les vives).
_EXPECTED_TABLES = {
    ("meta",),
    ("personality",),
    ("personality", "prompt"),
    ("personality", "orchestrator"),
    ("personality", "i18n"),
    ("core",),
    ("core", "server"),
    ("plugins",),
    ("plugins", "modules"),
    ("plugins", "models"),
    ("security",),
    ("security", "encryption"),
}
_PROMPT_KEYS = ("ca_small", "ca_full", "es_small", "es_full", "en_small", "en_full")


def _walk(d: dict, prefix=()):
    """Retorna (taules, fulles) com a conjunts de tuples de camí."""
    tables, leaves = set(), set()
    for k, v in d.items():
        path = prefix + (k,)
        if isinstance(v, dict):
            tables.add(path)
            t, le = _walk(v, path)
            tables |= t
            leaves |= le
        else:
            leaves.add(path)
    return tables, leaves


def _load_real() -> dict:
    with open(_SERVER_TOML, "rb") as f:
        return tomllib.load(f)


class TestRoundTripRealFile:
    """T1 — gate: les 51 claus del fitxer REAL sobreviuen un round-trip."""

    def test_real_file_has_51_keys(self):
        cfg = _load_real()
        tables, leaves = _walk(cfg)
        assert tables == _EXPECTED_TABLES, (
            f"taules inesperades o absents: {tables ^ _EXPECTED_TABLES}"
        )
        assert len(leaves) == 39, f"esperades 39 fulles, trobades {len(leaves)}"
        assert len(tables) + len(leaves) == 51

    def test_round_trip_preserves_everything(self, tmp_path):
        cfg = _load_real()
        out = tmp_path / "server.toml"
        out.write_bytes(tomli_w.dumps(cfg).encode("utf-8"))
        with open(out, "rb") as f:
            cfg2 = tomllib.load(f)
        assert cfg2 == cfg, "el round-trip tomllib→tomli_w→tomllib ha de ser identitat"

    def test_prompts_survive_char_exact(self, tmp_path):
        cfg = _load_real()
        out = tmp_path / "server.toml"
        out.write_bytes(tomli_w.dumps(cfg).encode("utf-8"))
        with open(out, "rb") as f:
            cfg2 = tomllib.load(f)
        for key in _PROMPT_KEYS:
            assert cfg2["personality"]["prompt"][key] == cfg["personality"]["prompt"][key], (
                f"el prompt {key} ha de sobreviure char-a-char"
            )
        # El tret que mata uiri: els prompts contenen la seqüència literal \[
        joined = "".join(cfg["personality"]["prompt"][k] for k in _PROMPT_KEYS)
        assert "\\[" in joined, (
            "el server.toml real ha de contenir \\[ als prompts — si desapareix, "
            "aquest test ja no exercita la causa arrel del #834"
        )


class TestProductionReadPath:
    """T2 — mutació-control de LECTURA: el camí de producció llegeix el fitxer sencer.

    Contra HEAD (uiri toml.load): 7 claus fulla → RED.
    """

    def test_config_validator_reads_all_sections(self):
        """El validador ha de VEURE les seccions que existeixen al fitxer real.

        Amb uiri toml la truncació silenciosa feia que [core]/[plugins]/
        [personality.orchestrator] sortissin com a "missing" tot i ser al
        fitxer. (storage sí que pot sortir: B049 la va eliminar de veritat.)
        """
        from personality.module_manager.config_validator import ConfigValidator

        result = ConfigValidator().validate(_SERVER_TOML)
        false_missing = [
            e for e in result.errors
            if ("[core]" in e or "[plugins]" in e or "[personality]" in e
                or "core.server." in e or "plugins.models." in e
                or "personality.orchestrator." in e)
        ]
        assert not false_missing, (
            f"seccions presents al fitxer reportades com a absents (parser truncat): {false_missing}"
        )
        assert not any("Cannot parse TOML" in e for e in result.errors)

    def test_save_config_reload_keeps_51_keys(self, tmp_path):
        """load (tomllib) → save_config → reload: cap clau perduda."""
        from core.config import save_config

        cfg = _load_real()
        out = tmp_path / "server.toml"
        assert save_config(cfg, out)
        with open(out, "rb") as f:
            cfg2 = tomllib.load(f)
        tables, leaves = _walk(cfg2)
        assert len(tables) + len(leaves) == 51, (
            f"save_config ha perdut claus: {len(tables) + len(leaves)}/51"
        )
        assert cfg2 == cfg


class TestAtomicWrite:
    """T3 — el fitxer original és intocable si la serialització peta."""

    def test_backup_created(self, tmp_path):
        from core.config import atomic_toml_write

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)
        original = target.read_bytes()
        atomic_toml_write(target, _load_real())
        bak = tmp_path / "server.toml.bak"
        assert bak.exists(), "atomic_toml_write ha de deixar un .bak del contingut previ"
        assert bak.read_bytes() == original

    def test_serialization_crash_leaves_file_intact(self, tmp_path, monkeypatch):
        import core.config as core_config

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)
        original = target.read_bytes()

        def _boom(*a, **k):
            raise TypeError("injected: unserialisable value")

        monkeypatch.setattr(core_config.tomli_w, "dumps", _boom)
        with pytest.raises(TypeError):
            core_config.atomic_toml_write(target, {"x": object()})
        assert target.read_bytes() == original, (
            "un crash de serialització MAI pot tocar el fitxer original "
            "(el open('w') antic el truncava abans de serialitzar)"
        )
        assert not (tmp_path / "server.toml.tmp").exists(), "cap .tmp residual"

    def test_no_toml_suffix_on_helpers(self, tmp_path):
        """Els residus .bak/.tmp no poden acabar en .toml (globs de manifests)."""
        from core.config import atomic_toml_write

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)
        atomic_toml_write(target, _load_real())
        residues = {p.name for p in tmp_path.iterdir()} - {"server.toml"}
        assert residues == {"server.toml.bak"}
        assert not any(r.endswith(".toml") for r in residues)

    def test_permission_bits_preserved(self, tmp_path):
        """Review #834: os.replace no pot convertir un 0600 en 0644 d'umask."""
        import stat as _stat

        from core.config import atomic_toml_write

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)
        target.chmod(0o600)
        atomic_toml_write(target, _load_real())
        assert _stat.S_IMODE(target.stat().st_mode) == 0o600, (
            "els prompts del producte poden estar protegits 0600 — el save ho ha de respectar"
        )

    def test_writes_through_symlink(self, tmp_path):
        """Review #834: un server.toml symlink s'ha d'escriure A TRAVÉS, no substituir."""
        from core.config import atomic_toml_write

        real = tmp_path / "real-config.toml"
        shutil.copy2(_SERVER_TOML, real)
        link = tmp_path / "server.toml"
        link.symlink_to(real)
        cfg = _load_real()
        cfg["meta"]["version"] = "symlink-test"
        atomic_toml_write(link, cfg)
        assert link.is_symlink(), "el symlink no pot convertir-se en fitxer regular"
        with open(real, "rb") as f:
            assert tomllib.load(f)["meta"]["version"] == "symlink-test", (
                "el contingut nou ha d'arribar al TARGET del symlink"
            )

    def test_backup_false_keeps_precommand_bak(self, tmp_path):
        """Fluxos de doble escriptura: la 2a passa backup=False i el .bak conserva
        l'estat PRE-comanda (no l'intermedi)."""
        from core.config import atomic_toml_write

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)
        original = target.read_bytes()
        first = _load_real()
        first["meta"]["version"] = "intermediate"
        atomic_toml_write(target, first)
        second = _load_real()
        second["meta"]["version"] = "final"
        atomic_toml_write(target, second, backup=False)
        assert (tmp_path / "server.toml.bak").read_bytes() == original


class TestCliWritesAreAtomic:
    """T4 — setup-models --apply i model install escriuen via atomic_toml_write."""

    def test_setup_models_apply_uses_atomic_writer(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        import core.config as core_config
        import core.cli.cli as cli_mod

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)

        calls = []
        real_writer = core_config.atomic_toml_write

        def spy(path, data, **kw):
            calls.append(Path(path))
            return real_writer(path, data, **kw)

        # setup_models fa `from core.config import atomic_toml_write` en temps de
        # crida → parchejar la font és suficient perquè l'spy vegi l'escriptura.
        monkeypatch.setattr(core_config, "atomic_toml_write", spy)
        monkeypatch.setattr(cli_mod, "get_repo_root", lambda: tmp_path)
        monkeypatch.setattr(cli_mod, "BASE_CONFIG_RELATIVE", "server.toml")
        # En màquines MLX el --apply encadena l'auto-descàrrega del model:
        # stub OFFLINE obligatori o el test es penja baixant GB de HuggingFace.
        import huggingface_hub

        monkeypatch.setattr(
            huggingface_hub, "snapshot_download", lambda **kw: None, raising=False
        )

        runner = CliRunner()
        result = runner.invoke(cli_mod.setup_models, ["--apply"])
        assert result.exit_code == 0, result.output
        assert calls and calls[0] == target, "l'escriptura ha d'anar via atomic_toml_write"

        # El repro del finding: després d'--apply, les claus segueixen sent 51.
        with open(target, "rb") as f:
            cfg = tomllib.load(f)
        tables, leaves = _walk(cfg)
        assert len(tables) + len(leaves) >= 51, (
            f"--apply ha reduït el server.toml a {len(tables) + len(leaves)} claus "
            "(el #834 en deixava 10 línies)"
        )
        for key in _PROMPT_KEYS:
            assert cfg["personality"]["prompt"][key], f"prompt {key} perdut per --apply"

    def test_setup_models_apply_write_error_exits_nonzero(self, tmp_path, monkeypatch):
        """Review #834 (major): un error d'ESCRIPTURA de config no pot sortir
        amb exit 0 disfressat d'error de descàrrega."""
        from click.testing import CliRunner
        import core.config as core_config
        import core.cli.cli as cli_mod

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)

        def _disc_ple(path, data, **kw):
            raise OSError(28, "No space left on device (injected)")

        monkeypatch.setattr(core_config, "atomic_toml_write", _disc_ple)
        monkeypatch.setattr(cli_mod, "get_repo_root", lambda: tmp_path)
        monkeypatch.setattr(cli_mod, "BASE_CONFIG_RELATIVE", "server.toml")
        import huggingface_hub

        monkeypatch.setattr(
            huggingface_hub, "snapshot_download", lambda **kw: None, raising=False
        )
        result = CliRunner().invoke(cli_mod.setup_models, ["--apply"])
        assert result.exit_code != 0, (
            f"error d'escriptura amb exit 0 (output: {result.output})"
        )


class TestI18nCollateral:
    """T5 — col·lateral #834: la config i18n es llegeix sencera malgrat \\[ als prompts."""

    def test_modular_i18n_reads_real_section(self, tmp_path):
        from personality.i18n.modular_i18n import ModularI18nManager

        target = tmp_path / "server.toml"
        shutil.copy2(_SERVER_TOML, target)
        mgr = ModularI18nManager(config_path=target, base_path=tmp_path)
        i18n_cfg = mgr.config.get("personality", {}).get("i18n", {})
        assert i18n_cfg, (
            "amb uiri toml el parser moria abans de [personality.i18n] i la secció "
            "no existia mai (col·lateral del #834)"
        )
        assert mgr.current_language == i18n_cfg["default_language"]


def test_tripwire_no_uiri_toml_imports():
    """Cap `import toml` (uiri) al source tree — tomllib/tomli_w són els únics permesos.

    Cobreix també tests/ i els .py d'arrel: el venv de dev encara TÉ uiri toml
    instal·lat, així que un import residual funcionaria en local i petaria
    només en instal·lacions netes — el tripwire és la protecció real.
    """
    offenders = []
    pattern = re.compile(r"^\s*(import toml\b(?!lib)|from toml\b(?!lib)[ .])", re.M)
    candidates = list(_REPO_ROOT.glob("*.py"))
    for root in ("core", "personality", "plugins", "installer", "tests", "scripts", "dev-tools"):
        if (_REPO_ROOT / root).is_dir():
            candidates.extend((_REPO_ROOT / root).rglob("*.py"))
    for path in candidates:
        if "venv" in path.parts or "node_modules" in path.parts or "worktrees" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert not offenders, f"imports d'uiri toml residuals: {offenders}"
