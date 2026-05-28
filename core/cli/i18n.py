"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/i18n.py
Description: Internationalisation helper for Central CLI messages.
             Reads translations from `core/cli/languages/{lang}/common.json`
             without depending on `personality/i18n/I18nManager` (which may not
             be available in early CLI startup contexts).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_LANG_DIR = Path(__file__).parent / "languages"
_FALLBACK_LANG = "ca-ES"

# Cache per loaded language — avoids reading the JSON on every call.
_cache: Dict[str, Dict[str, Any]] = {}


def _load(lang_code: str) -> Dict[str, Any]:
    """Load (with cache) the `common.json` for the requested language."""
    if lang_code in _cache:
        return _cache[lang_code]
    path = _LANG_DIR / lang_code / "common.json"
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    _cache[lang_code] = data
    return data


def _resolve_lang(lang: Optional[str]) -> str:
    """Determine the active language: explicit param > NEXE_LANG > fallback en-US."""
    return lang or os.getenv("NEXE_LANG", "en-US")  # type: ignore[return-value]  # FP: mypy or-narrowing limitation; os.getenv(name, default=str) returns str, so Optional[str] or str is always str


def _lookup(data: Dict[str, Any], key: str) -> Optional[str]:
    """Traverse dot-separated keys (`cli.greetings.welcome`) within the dict."""
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node if isinstance(node, str) else None


def t(key: str, lang: Optional[str] = None, default: Optional[str] = None, **kwargs: Any) -> str:
    """
    Return the translated text for `key` interpolating `**kwargs` with `str.format`.

    Flow:
    1. Try the requested language (param or `NEXE_LANG`).
    2. If the key or language does not exist, fall back to `ca-ES`.
    3. If still not found, return `default` (or the key itself if not provided).

    Does not raise — CLI messages must never crash due to i18n.

    Args:
      key: dot-style key such as `cli.go.starting`.
      lang: language code. If None, obtained from `NEXE_LANG` or `ca-ES`.
      default: text to return if the key does not exist. Default: the key.
      **kwargs: values to interpolate with `str.format`.

    Returns:
      The localised text (or the default/key if no translation is found).
    """
    lang_code = _resolve_lang(lang)
    text = _lookup(_load(lang_code), key)
    if text is None and lang_code != _FALLBACK_LANG:
        text = _lookup(_load(_FALLBACK_LANG), key)
    if text is None:
        text = default if default is not None else key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            # Failed interpolation — return raw text to avoid hiding the problem.
            return text
    return text


def clear_cache() -> None:
    """Clear the translation cache (useful for tests that monkeypatch NEXE_LANG)."""
    _cache.clear()


__all__ = ["t", "clear_cache"]
