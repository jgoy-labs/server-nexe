"""
Helpers for resolving i18n tokens and modular translations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .modular_i18n import ModularI18nManager

_modular_i18n: Optional[ModularI18nManager] = None


def get_modular_i18n(
    config_path: Optional[Path] = None,
    base_path: Optional[Path] = None,
) -> ModularI18nManager:
    """Return a cached ModularI18nManager instance."""
    global _modular_i18n
    if _modular_i18n is None:
        _modular_i18n = ModularI18nManager(config_path=config_path, base_path=base_path)
    return _modular_i18n


def _format_fallback(fallback: str, key: str, **kwargs) -> str:
    if fallback:
        try:
            return fallback.format(**kwargs)
        except (KeyError, ValueError):
            return fallback
    return key


def t_modular(key: str, fallback: str = "", **kwargs) -> str:
    """Translate with ModularI18nManager and fallback formatting."""
    try:
        text = get_modular_i18n().t(key, **kwargs)
        if text == key:
            return _format_fallback(fallback, key, **kwargs)
        return text
    except Exception:
        return _format_fallback(fallback, key, **kwargs)


def resolve_i18n_string(value: Any, i18n: Optional[ModularI18nManager] = None) -> Any:
  """Resolve strings in the form i18n:key|fallback to translated text."""
  if not isinstance(value, str):
    return value
  if not value.startswith("i18n:"):
    return value

    token = value[len("i18n:") :]
    key = token
    fallback = ""
    if "|" in token:
        key, fallback = token.split("|", 1)

    key = key.strip()
    fallback = fallback.strip()

    if not key:
        return fallback or value

    manager = i18n or get_modular_i18n()
    try:
        text = manager.t(key) if manager else key
    except Exception:
        text = key

    if text == key:
        return fallback or key

  return text


def resolve_i18n_tree(value: Any, i18n: Optional[ModularI18nManager] = None) -> Any:
  """Recursively resolve i18n tokens inside dicts/lists."""
  if isinstance(value, dict):
    return {k: resolve_i18n_tree(v, i18n) for k, v in value.items()}
  if isinstance(value, list):
    return [resolve_i18n_tree(v, i18n) for v in value]
  return resolve_i18n_string(value, i18n)
