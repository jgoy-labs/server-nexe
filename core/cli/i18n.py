"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/cli/i18n.py
Description: Lightweight i18n helper for CLI messages.
────────────────────────────────────
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.resources import get_translation_path

SUPPORTED_LANGS = ("en-US", "ca-ES", "es-ES")
DEFAULT_LANG = "en-US"

_translations: Dict[str, Dict[str, Any]] = {}
_current_lang: Optional[str] = None


def _normalize_lang(value: str | None) -> Optional[str]:
  if not value:
    return None

  raw = value.strip()
  if not raw:
    return None

  raw = raw.replace("_", "-")
  raw = raw.split(".")[0].split("@")[0]

  base = raw[:2].lower()
  if base == "ca":
    return "ca-ES"
  if base == "es":
    return "es-ES"
  if base == "en":
    return "en-US"

  # Try exact match if provided
  if raw in SUPPORTED_LANGS:
    return raw

  return None


def _default_lang_from_toml() -> Optional[str]:
  try:
    try:
      import tomllib  # py3.11+
    except ImportError:
      import tomli as tomllib  # type: ignore

    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "personality" / "server.toml"
    if not config_path.exists():
      config_path = project_root / "server.toml"

    if not config_path.exists():
      return None

    with open(config_path, "rb") as f:
      data = tomllib.load(f)

    lang = data.get("personality", {}).get("i18n", {}).get("default_language")
    return _normalize_lang(lang)
  except Exception:
    return None


def _select_language() -> str:
  for env_key in ("NEXE_LANG", "NEXE_LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    lang = _normalize_lang(os.environ.get(env_key))
    if lang in SUPPORTED_LANGS:
      return lang

  toml_lang = _default_lang_from_toml()
  if toml_lang in SUPPORTED_LANGS:
    return toml_lang

  return DEFAULT_LANG


def _load_language(lang: str) -> Dict[str, Any]:
  if lang in _translations:
    return _translations[lang]

  data: Dict[str, Any] = {}
  try:
    path = get_translation_path("core.cli", lang, "common")
    if path.exists():
      with open(path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
  except Exception:
    data = {}

  _translations[lang] = data
  return data


def _get_nested(data: Dict[str, Any], key: str) -> Optional[str]:
  current: Any = data
  for part in key.split("."):
    if isinstance(current, dict) and part in current:
      current = current[part]
    else:
      return None
  return current if isinstance(current, str) else None


def t(key: str, fallback: str = "", **kwargs: Any) -> str:
  """
  Translate a CLI key with fallback.

  Args:
    key: Translation key (e.g., "cli.output.modules_title")
    fallback: Fallback string when missing
    **kwargs: Format arguments
  """
  global _current_lang

  if _current_lang is None:
    _current_lang = _select_language()

  data = _load_language(_current_lang)
  value = _get_nested(data, key)

  if value is None and _current_lang != DEFAULT_LANG:
    fallback_data = _load_language(DEFAULT_LANG)
    value = _get_nested(fallback_data, key)

  if value is None:
    value = fallback or key

  try:
    return value.format(**kwargs) if kwargs else value
  except Exception:
    return value
