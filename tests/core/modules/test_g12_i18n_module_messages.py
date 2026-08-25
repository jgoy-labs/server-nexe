"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/modules/test_g12_i18n_module_messages.py
Description: G12 gate (#920) — the 15 translation catalogs under
    core/modules/languages/ must actually reach get_message().

    Measured on 23/08/2026, before the fix: a real I18nManager built the way
    ModuleManager builds it, with NEXE_LANG=ca-ES, loaded ZERO components and
    get_message(i18n, "init.started") answered "ModuleManager initialized" —
    English, from FALLBACK_MESSAGES. Two causes, both had to be aligned:

      1. THE PATH — _load_module_translations looked for a literal `location/`
         subdirectory under a per-module folder. The real layout is flat:
         <package>/languages/<lang>/messages_<component>.json. And the bases it
         scanned hung off base_path (= personality/), so core/modules/ was never
         reached at all.
      2. THE PREFIX — get_message asks for short keys (`init.started`) while the
         catalogs nest them under their component (`module_manager.init.started`),
         which is the format I18nManager.t() documents.

    Rule §1.7: the catalogs, the languages and the keys are all DISCOVERED. A
    gate that checked `init.started` alone would leave 14 files unguarded, so
    every string key every catalog declares is checked, in every language.

    Mutation targets (both mandatory, one per cause):
      1. undo the path alignment -> RED
      2. undo the prefix alignment, leaving the path good -> RED

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import os
from pathlib import Path

import pytest

from core.modules.messages import FALLBACK_MESSAGES, get_message

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_DIR = REPO_ROOT / "core" / "modules" / "languages"

# Measured on 23/08/2026: 3 languages x 4 catalogs actually loaded.
# `module_manager.json` is NOT counted: it does not match the `messages_*.json`
# contract the loaders use, so nothing reads it (reported to the Director).
MIN_LANGUAGES = 3
MIN_CATALOGS_PER_LANGUAGE = 4

# The component every FALLBACK_MESSAGES key belongs to. Measured, not guessed:
# all 34 keys resolve under this component in all three languages.
MODULE_MANAGER_COMPONENT = "module_manager"


def _discover_languages() -> list:
    """Discover the language directories that ship catalogs."""
    return sorted(d.name for d in CATALOG_DIR.iterdir()
                  if d.is_dir() and any(d.glob("messages_*.json")))


def _discover_catalogs(language: str) -> list:
    """Discover the catalog files a language ships, the way the loaders glob them."""
    return sorted((CATALOG_DIR / language).glob("messages_*.json"))


def _flatten(data: dict, trail: str = "") -> dict:
    """Flatten a catalog into dotted keys, keeping only translatable strings.

    Non-string leaves (`manifest.default.enabled` is a bool) are dropped: they
    are configuration values, not messages, and I18nManager.t() only ever
    returns strings.
    """
    flat = {}
    for name, value in data.items():
        if name == "_meta":
            continue
        key = f"{trail}.{name}" if trail else name
        if isinstance(value, dict):
            flat.update(_flatten(value, key))
        elif isinstance(value, str):
            flat[key] = value
    return flat


def _declared_language(path: Path):
    """The language a catalog claims in _meta, or None when it claims nothing."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("_meta", {}).get("language")


def _servable_catalogs(language: str) -> list:
    """Catalogs a correct loader may serve for `language`.

    A catalog that DECLARES another language is a mislabelled copy and must not
    be served. One that declares nothing is not making a claim, so it loads —
    six catalogs in the repo have no _meta.language and must keep working.
    """
    return [c for c in _discover_catalogs(language)
            if _declared_language(c) in (None, language)]


def _catalog_strings(language: str) -> dict:
    """Every translatable key a language declares: {component: {dotted key: text}}."""
    catalogs = {}
    for path in _servable_catalogs(language):
        component = path.stem[len("messages_"):]
        data = json.loads(path.read_text(encoding="utf-8"))
        # The loaders unwrap a top-level key equal to the component, if present.
        inner = data[component] if component in data else data
        catalogs[component] = _flatten(inner)
    return catalogs


def _real_i18n(language: str):
    """Build the real I18nManager the way ModuleManager builds it.

    core/modules/module_manager.py does `I18nManager(cfg, cfg.parent)` with the
    real server.toml — no doubles, no pre-loaded catalog. The language is forced
    on the instance afterwards because _load_config() reads it from server.toml
    (`idioma_principal`), so NEXE_LANG alone cannot steer it; the gate has to
    cover all three catalogs, not just the configured one.
    """
    from core.config import find_config_path
    from personality.i18n.i18n_manager import I18nManager

    config_path = find_config_path() or REPO_ROOT / "personality" / "server.toml"
    i18n = I18nManager(config_path, config_path.parent)
    i18n.current_language = language
    i18n.fallback_language = language
    i18n.translations = {}
    i18n._translations_loaded = False
    return i18n


def test_discovery_scope_control():
    """Scope control (§1.7): the gate goes red on its own if the discovery shrinks."""
    assert CATALOG_DIR.is_dir(), f"catalog directory is gone: {CATALOG_DIR}"

    languages = _discover_languages()
    assert len(languages) >= MIN_LANGUAGES, (
        f"discovery found {len(languages)} languages ({languages}), fewer than the "
        f"{MIN_LANGUAGES} measured on 23/08/2026 — someone narrowed it."
    )
    for language in languages:
        catalogs = _discover_catalogs(language)
        assert len(catalogs) >= MIN_CATALOGS_PER_LANGUAGE, (
            f"{language} ships {len(catalogs)} catalogs, fewer than the "
            f"{MIN_CATALOGS_PER_LANGUAGE} measured: {[c.name for c in catalogs]}"
        )

    covered = set(_catalog_strings("ca-ES").get(MODULE_MANAGER_COMPONENT, {}))
    uncovered = {k for k, v in FALLBACK_MESSAGES.items() if isinstance(v, str)} - covered
    assert not uncovered, (
        f"these FALLBACK_MESSAGES keys have no translation to check against: "
        f"{sorted(uncovered)}. The gate would silently stop guarding them."
    )


def test_init_started_is_catalan_and_not_english(monkeypatch):
    """#920, the exact case in the finding: NEXE_LANG=ca-ES must not answer in English."""
    monkeypatch.setenv("NEXE_LANG", "ca-ES")
    i18n = _real_i18n("ca-ES")

    expected = _catalog_strings("ca-ES")[MODULE_MANAGER_COMPONENT]["init.started"]
    english = FALLBACK_MESSAGES["init.started"]
    actual = get_message(i18n, "init.started")

    assert actual != english, (
        f"get_message returned the English fallback ({english!r}) with NEXE_LANG=ca-ES. "
        f"The catalog says {expected!r} and nothing reached it."
    )
    assert actual == expected, (
        f"get_message returned {actual!r}; the ca-ES catalog declares {expected!r}"
    )


@pytest.mark.parametrize("language", _discover_languages())
def test_every_declared_key_reaches_get_message(language):
    """Every string key of every discovered catalog must come back translated.

    Checking one key would leave the other 14 files unguarded (§1.7), so this
    walks the whole catalog set: ~200 keys per language.

    #946: a language whose catalogs are ALL mislabelled copies of another
    (each declares a different _meta.language, per #920) has zero servable
    catalogs — walking zero keys must not read as a pass. That would look
    identical to broken code silently serving nothing in that language.
    """
    catalogs = _catalog_strings(language)
    total_keys = sum(len(entries) for entries in catalogs.values())
    if total_keys == 0:
        # Skip only for the KNOWN #920 reason — every discovered catalog
        # declares a different language. Any other cause of zero keys walked
        # (e.g. a loader/flatten bug emptying ca-ES itself, even if `catalogs`
        # still has component keys with empty bodies) must fail loudly, not
        # look like this accepted case.
        discovered = _discover_catalogs(language)
        mislabelled = [c for c in discovered if _declared_language(c) not in (None, language)]
        if not discovered or len(mislabelled) != len(discovered):
            pytest.fail(
                f"{language} walks ZERO translation keys, but NOT for the known "
                f"#920 reason: {len(discovered)} catalogs discovered, "
                f"{len(mislabelled)} mislabelled as another language. "
                f"Investigate — this is not the case the skip below is written for."
            )
        pytest.skip(
            f"{language} has no servable catalog today (#920: all "
            f"{len(discovered)} discovered catalogs declare a different "
            f"_meta.language) — not a pass, nothing was walked. Once "
            f"{language} ships real catalogs this must go back to asserting."
        )

    i18n = _real_i18n(language)

    broken = {}
    for component, entries in catalogs.items():
        for key, expected in entries.items():
            actual = i18n.t(f"{component}.{key}")
            if actual != expected:
                broken[f"{component}.{key}"] = {"got": actual, "want": expected}

    assert not broken, (
        f"{len(broken)} declared translations do not reach I18nManager.t() in "
        f"{language}; first few: {dict(list(broken.items())[:5])}"
    )


@pytest.mark.parametrize("language", _discover_languages())
def test_module_manager_fallback_keys_are_translated(language):
    """The short keys the module manager really asks for must resolve, in every language."""
    i18n = _real_i18n(language)
    catalog = _catalog_strings(language).get(MODULE_MANAGER_COMPONENT)
    if catalog is None:
        pytest.skip(
            f"{language} ships no servable module_manager catalog: its copy declares "
            f"another language and the loader must refuse it (see the guard test)"
        )

    untranslated = {}
    for key, fallback in FALLBACK_MESSAGES.items():
        if not isinstance(fallback, str) or key not in catalog:
            continue
        actual = get_message(i18n, key)
        if actual != catalog[key]:
            untranslated[key] = {"got": actual, "want": catalog[key]}

    assert not untranslated, (
        f"{len(untranslated)} keys still answer with the English fallback in {language}: "
        f"{dict(list(untranslated.items())[:5])}"
    )


@pytest.mark.parametrize("language", _discover_languages())
def test_a_catalog_declaring_another_language_is_never_served(language):
    """A mislabelled copy must not be served — the user gets the fallback instead.

    core/modules/languages/{en-US,es-ES}/ are byte-for-byte copies of the ca-ES
    catalogs, `_meta.language: "ca-ES"` included (verified with md5, 23/08/2026).
    Before #920 was fixed nothing reached the user and they got the English
    fallback; a fix that starts serving those copies would hand Catalan to
    someone who asked for English. That is a regression, not a fix.

    Discovered, not listed: whichever catalogs declare another language.

    Mutation: drop the guard from the loader -> this turns RED for en-US and
    es-ES, saying they answer in Catalan.
    """
    mislabelled = [c for c in _discover_catalogs(language)
                   if _declared_language(c) not in (None, language)]
    if not mislabelled:
        pytest.skip(f"{language} ships no mislabelled catalog to guard against")

    i18n = _real_i18n(language)
    served = set(i18n.translations.get(language, {}))
    i18n._ensure_translations_loaded()
    served = set(i18n.translations.get(language, {}))

    leaked = sorted(c.stem[len("messages_"):] for c in mislabelled
                    if c.stem[len("messages_"):] in served)
    assert not leaked, (
        f"{language} is being served {leaked}, whose catalogs declare "
        f"{sorted({_declared_language(c) for c in mislabelled})}. A user asking for "
        f"{language} would read another language; the fallback is the honest answer."
    )


def test_english_still_falls_back_to_english():
    """The concrete regression: en-US must not start answering in Catalan.

    Not a paraphrase of the test above: this one drives get_message() end to end,
    the way the module manager calls it, and pins the exact string the user reads.
    """
    i18n = _real_i18n("en-US")
    english = FALLBACK_MESSAGES["init.started"]
    catalan = _flatten(
        json.loads((CATALOG_DIR / "ca-ES" / "messages_module_manager.json")
                   .read_text(encoding="utf-8"))
    )["init.started"]

    actual = get_message(i18n, "init.started")
    assert actual != catalan, (
        f"a user with NEXE_LANG=en-US is being served Catalan ({actual!r}). "
        f"The en-US catalog is a copy of the Catalan one and must be refused."
    )
    assert actual == english, (
        f"en-US should fall back to {english!r}, got {actual!r}"
    )
