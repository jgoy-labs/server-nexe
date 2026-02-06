"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/i18n.py
Description: Minimal i18n helper for Web UI module messages.
────────────────────────────────────
"""

from __future__ import annotations

from typing import Any, Optional


def _resolve_i18n():
  try:
    from core.container import get_service
    i18n = get_service("i18n")
    if i18n:
      return i18n
  except Exception:
    pass

  try:
    from personality.i18n import get_i18n
    return get_i18n()
  except Exception:
    return None


def t(key: str, fallback: str = "", **kwargs: Any) -> str:
  i18n = _resolve_i18n()
  if i18n:
    try:
      value = i18n.t(key, **kwargs)
      if value != key:
        return value
    except Exception:
      pass

  if fallback:
    if kwargs:
      try:
        return fallback.format(**kwargs)
      except (KeyError, ValueError):
        return fallback
    return fallback

  return key


__all__ = ["t"]
