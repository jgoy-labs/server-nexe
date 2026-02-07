"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/i18n/__init__.py
Description: Package marker for the internationalization system. Exports I18nManager (base)

www.jgoy.net
────────────────────────────────────
"""

from .i18n_manager import I18nManager
from .modular_i18n import ModularI18nManager

I18n = I18nManager

_global_i18n = None

class I18nHelper:
  """Helper wrapper for compatibility with standalone functions."""

  def __init__(self, manager: I18nManager):
    self._manager = manager

  def t(self, key: str, fallback: str = "", **kwargs) -> str:
    """
    Translate with automatic fallback.

    Args:
      key: Translation key (e.g. "loaders.csv.not_found")
      fallback: Default text if translation is missing
      **kwargs: Parameters for interpolation

    Returns:
      str: Translated text or fallback
    """
    try:
      value = self._manager.t(key, **kwargs)
      if value != key:
        return value
    except (KeyError, Exception):
      if fallback and kwargs:
        try:
          return fallback.format(**kwargs)
        except (KeyError, ValueError):
          return fallback
      return fallback or key

    if fallback and kwargs:
      try:
        return fallback.format(**kwargs)
      except (KeyError, ValueError):
        return fallback
    return fallback or key

def get_i18n() -> I18nHelper:
  """
  Return the global I18nHelper instance.

  Useful for standalone functions that do not have access to self._t().
  Uses a singleton pattern for performance.

  Returns:
    I18nHelper: Helper with fallback support

  Example:
    >>> from personality.i18n import get_i18n
    >>> error = get_i18n().t("module.error", "Error: {msg}", msg="test")
  """
  global _global_i18n
  if _global_i18n is None:
    _global_i18n = I18nHelper(I18nManager())
  return _global_i18n
