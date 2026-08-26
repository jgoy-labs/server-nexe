"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/modules/test_960_translated_catalogs_and_guard.py
Description: #960 — the en-US and es-ES catalogs under core/modules/languages/
            were byte-for-byte copies of the Catalan ones, `_meta.language:
            "ca-ES"` included (md5-verified 23/08/2026). Decision (Jordi,
            26/08/2026): translate them for real, option (a).

            Two things must now hold, and the g12 gate covers neither on its
            own: the catalogs must really BE translated (a copy with only the
            _meta flipped would serve Catalan to an English user — the exact
            regression #920's guard exists to stop), and that guard must keep
            biting even though no mislabelled catalog is left in the tree to
            bite (the g12 test that used to exercise it now skips).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_LANGS = _REPO / "core" / "modules" / "languages"

# Values that are configuration, not prose: TOML key names and filenames the
# loader matches literally. Translating "module" -> "módulo" would break
# manifest parsing silently, so they are identical across languages BY DESIGN.
_LITERAL_KEYS = {
    "paths.manifests_dir",
    "files.manifest_toml",
    "files.module_manifest_format",
    "manifest.default.version",
    "manifest.default.enabled",
    "manifest.keys.module",
    "manifest.keys.version",
    "manifest.keys.enabled",
}


def _flatten(data: dict, prefix: str = "") -> dict:
    out = {}
    for key, value in data.items():
        if key == "_meta":
            continue
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, dotted))
        else:
            out[dotted] = value
    return out


def _catalogs(language: str):
    return sorted((_LANGS / language).glob("messages_*.json"))


_TRANSLATED = [lang for lang in ("en-US", "es-ES") if (_LANGS / lang).is_dir()]


@pytest.mark.parametrize("language", _TRANSLATED)
class TestCatalogsAreReallyTranslated:
    def test_meta_declares_its_own_directory(self, language):
        for catalog in _catalogs(language):
            declared = json.loads(catalog.read_text(encoding="utf-8"))["_meta"]["language"]
            assert declared == language, (
                f"{catalog.name} sits in {language}/ but declares {declared!r} — "
                f"the loader will refuse it and the user gets the fallback"
            )

    def test_no_catalog_is_still_a_copy_of_the_catalan(self, language):
        """The heart of #960: flipping _meta without translating would pass the
        loader's guard and serve Catalan to someone who asked for something else.

        Measured by SHARE, not by zero matches: a handful of strings really are
        identical across these languages ("Total errors: {count}" is the same
        sentence in Catalan and English), and demanding a difference there would
        only push someone to write worse English. A copy-paste scores 100%.
        """
        for catalog in _catalogs(language):
            ca = _flatten(json.loads((_LANGS / "ca-ES" / catalog.name).read_text(encoding="utf-8")))
            other = _flatten(json.loads(catalog.read_text(encoding="utf-8")))
            prose = [
                key for key, value in ca.items()
                if key not in _LITERAL_KEYS and isinstance(value, str) and len(value) > 3
            ]
            assert prose, f"{catalog.name} has no prose to compare — check the fixture"
            identical = [key for key in prose if other.get(key) == ca[key]]
            share = len(identical) / len(prose)
            assert share < 0.10, (
                f"{len(identical)}/{len(prose)} strings ({share:.0%}) in "
                f"{language}/{catalog.name} are still the Catalan text — that is a "
                f"copy, not a translation. First few: {identical[:5]}"
            )

    def test_the_key_set_matches_the_catalan_exactly(self, language):
        """A translation that drops keys degrades to the fallback for those keys
        only — the worst kind of half-broken, because everything looks fine."""
        for catalog in _catalogs(language):
            ca = set(_flatten(json.loads((_LANGS / "ca-ES" / catalog.name).read_text(encoding="utf-8"))))
            other = set(_flatten(json.loads(catalog.read_text(encoding="utf-8"))))
            assert ca == other, (
                f"{language}/{catalog.name}: missing={sorted(ca - other)[:5]} "
                f"extra={sorted(other - ca)[:5]}"
            )

    def test_configuration_literals_were_not_translated(self, language):
        """`manifest.keys.module` is the literal TOML key the parser looks for."""
        catalog = _LANGS / language / "messages_module_manager.json"
        data = _flatten(json.loads(catalog.read_text(encoding="utf-8")))
        ca = _flatten(json.loads((_LANGS / "ca-ES" / catalog.name).read_text(encoding="utf-8")))
        for key in _LITERAL_KEYS:
            if key in ca:
                assert data[key] == ca[key], (
                    f"{key} is configuration, not prose — translating it breaks the loader"
                )


class TestTheMislabelledGuardStillBites:
    """#920's guard no longer refuses anything in-tree, so the g12 test that
    exercised it now skips. Without this, deleting the guard would go unnoticed
    until the next copy-pasted catalog shipped the wrong language to a user."""

    def _manager(self):
        from personality.i18n.i18n_manager import I18nManager

        return I18nManager()

    def test_a_catalog_declaring_another_language_is_refused(self):
        mgr = self._manager()
        assert mgr._catalog_is_for(
            Path("messages_x.json"), {"_meta": {"language": "ca-ES"}}, "en-US"
        ) is False

    def test_a_catalog_declaring_its_own_language_is_served(self):
        mgr = self._manager()
        assert mgr._catalog_is_for(
            Path("messages_x.json"), {"_meta": {"language": "en-US"}}, "en-US"
        ) is True

    @pytest.mark.parametrize("data", [{}, {"_meta": {}}, {"_meta": "not-a-dict"}])
    def test_declaring_nothing_is_not_declaring_the_wrong_thing(self, data):
        """Six catalogs in the repo ship no _meta.language and must keep loading."""
        mgr = self._manager()
        assert mgr._catalog_is_for(Path("messages_x.json"), data, "en-US") is True
