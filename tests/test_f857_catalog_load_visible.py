"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_f857_catalog_load_visible.py
Description: #857 — the wizard used to fall back to an EMPTY catalog in silence.
             ``ModelCatalog.load()`` chained two ``try?`` (bundle, then dev path)
             and returned an empty catalog at the end, and each tier decoded with
             ``try? ... ?? []``. Both failure modes reached the user as the same
             thing: a picker with no models, which reads as "nothing fits your
             machine" instead of "the catalog is missing or broken".

             Measured on the 31/07 smoke (``swift run`` with no models.json next
             to the binary) and reproduced against both versions of the file:

               old code, tier_16 present but not a list → tier16=0, no error
               new code, same input                     → corrupt, "Path: tier_16"

             These tests read the real Swift source — same approach as the other
             wizard gates: they catch the regression without a Swift toolchain in
             the loop, and without re-implementing the logic in Python.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
from pathlib import Path

SWIFT_DIR = (
    Path(__file__).resolve().parent.parent
    / "installer" / "swift-wizard" / "Sources" / "InstallNexe"
)

TIER_KEYS = ["tier8", "tier16", "tier24", "tier32", "tier48", "tier64"]


def _source(name: str) -> str:
    return (SWIFT_DIR / name).read_text()


def test_f857_tier_decoding_does_not_swallow_a_corrupt_tier():
    """A tier that is PRESENT but does not decode must raise, not become [].

    This is the half of #857 that loses data without emptying the picker: with
    ``try? c.decode(...) ?? []`` a single malformed tier drops its models and
    every other tier still loads, so the list looks plausible and is wrong.
    A tier that is simply ABSENT stays legitimate — not every build ships every
    tier — which is why the fix guards on ``contains`` rather than decoding
    everything unconditionally.
    """
    src = _source("ModelCatalog.swift")
    decoder_init = src.split("init(from decoder: Decoder) throws {", 1)
    assert len(decoder_init) == 2, (
        "#857: no trobo l'inicialitzador Decodable de ModelCatalog — "
        "si s'ha reanomenat, aquest gate s'ha d'actualitzar amb ell."
    )
    body = decoder_init[1].split("\n    }", 1)[0]

    assert "try?" not in body, (
        "#857: l'inicialitzador Decodable torna a usar `try?` — un tier corrupte "
        "es perdria en silenci i el picker ensenyaria una llista incompleta que "
        "sembla correcta. Vegeu el mutant mesurat: tier_16 no-llista → tier16=0."
    )
    assert "c.contains(" in body, (
        "#857: cal distingir un tier ABSENT (legítim → []) d'un tier PRESENT que "
        "no decodifica (corrupció → error). Sense el guard `contains`, o es perd "
        "informació o falla un catàleg vàlid sense tier_48/tier_64."
    )


def test_f857_load_reports_why_instead_of_returning_empty():
    """Loading must return a reason on failure, not a silently empty catalog."""
    src = _source("ModelCatalog.swift")

    assert "func loadOrFail() -> Result<ModelCatalog, LoadFailure>" in src, (
        "#857: falta `loadOrFail()` — el carregador ha de poder dir PER QUÈ ha "
        "fallat; un `ModelCatalog` buit no distingeix 'no hi és' de 'està trencat'."
    )
    for case in ("case notFound", "case unreadable", "case corrupt"):
        assert case in src, (
            f"#857: falta el cas `{case}` a LoadFailure. Els tres modes de fallada "
            "arribaven a l'usuari com el mateix picker buit; separar-los és el fix."
        )

    # The old shape: two optional-try chains ending in `return empty`.
    assert not re.search(r"return\s+empty\b", src), (
        "#857: ha tornat el `return empty` mut al final de la càrrega — és "
        "exactament el camí que va deixar el picker buit sense error al smoke."
    )


def test_f857_engine_surfaces_the_failure():
    """The engine must publish the failure so the UI has something to show."""
    src = _source("InstallerEngine.swift")

    assert "@Published var catalogError: String?" in src, (
        "#857: `InstallerEngine` ha de publicar l'error del catàleg; sense estat "
        "publicat, la vista no té res a pintar i tornem al buit silenciós."
    )
    assert "loadOrFail()" in src, (
        "#857: `loadCatalog()` ha de passar per `loadOrFail()`; si torna a cridar "
        "un carregador que empassa els errors, la resta del fix és decoratiu."
    )
    assert "case .failure" in src, (
        "#857: `loadCatalog()` ha de gestionar explícitament el cas de fallada."
    )


def test_f857_picker_shows_the_reason():
    """The failure has to reach the screen, in the three shipped languages.

    Sixth appearance of the characteristic defect (31/07): the tier tabs had the
    translations and painted hardcoded strings anyway. A banner wired to a key
    that no language defines would fail the same way — visible in review, empty
    on screen.
    """
    picker = _source("ModelPickerView.swift")
    assert "engine.catalogError" in picker, (
        "#857: `ModelPickerView` no llegeix `catalogError` — l'usuari continua "
        "veient una llista buida sense explicació."
    )
    assert 't("model_catalog_error")' in picker, (
        "#857: el banner ha de passar per `t()`, no per text encastat."
    )

    translations = _source("Translations.swift")
    occurrences = translations.count('"model_catalog_error"')
    assert occurrences == 3, (
        f"#857: la clau `model_catalog_error` surt {occurrences} cops a "
        "Translations.swift i n'hi ha d'haver 3 (ca/es/en). Una clau que falta "
        "en una llengua deixa el banner mut precisament a qui no llegeix anglès."
    )
