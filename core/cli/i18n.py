"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/i18n.py
Description: Helper d'internacionalització pels missatges del CLI Central.
             Llegeix les traduccions de `core/cli/languages/{lang}/common.json`
             sense dependre de `personality/i18n/I18nManager` (que pot no
             estar disponible en contextos d'arrencada primerenca del CLI).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_LANG_DIR = Path(__file__).parent / "languages"
_FALLBACK_LANG = "ca-ES"

# Cache per idioma carregat — evita llegir el JSON a cada crida.
_cache: Dict[str, Dict[str, Any]] = {}


def _load(lang_code: str) -> Dict[str, Any]:
    """Carrega (amb cache) el `common.json` de l'idioma sol·licitat."""
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
    """Determina l'idioma actiu: param explícit > NEXE_LANG > fallback ca-ES."""
    return lang or os.getenv("NEXE_LANG", _FALLBACK_LANG)


def _lookup(data: Dict[str, Any], key: str) -> Optional[str]:
    """Recorre claus separades per punts (`cli.greetings.welcome`) dins del dict."""
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
    Retorna el text traduït per `key` interpolant `**kwargs` amb `str.format`.

    Fluxe:
    1. Prova l'idioma sol·licitat (param o `NEXE_LANG`).
    2. Si no existeix la clau o l'idioma, cau a `ca-ES`.
    3. Si tampoc, retorna `default` (o la pròpia clau si no es passa).

    No fa raise — els missatges del CLI no han de petar mai per culpa d'i18n.

    Args:
      key: clau estil `cli.go.starting`.
      lang: codi d'idioma. Si és None, s'obté de `NEXE_LANG` o `ca-ES`.
      default: text per retornar si la clau no existeix. Defecte: la clau.
      **kwargs: valors per interpolar amb `str.format`.

    Returns:
      El text localitzat (o el default/clau si no hi ha traducció).
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
            # Interpolació fallida — retorna el text cru per no amagar el problema.
            return text
    return text


def clear_cache() -> None:
    """Buida el cache de traduccions (útil per tests que monkeypatchen NEXE_LANG)."""
    _cache.clear()


__all__ = ["t", "clear_cache"]
