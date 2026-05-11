"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/i18n/__init__.py
Description: Package marker for the internationalization system. Exports I18nManager (base)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import threading

from .i18n_manager import I18nManager
from .modular_i18n import ModularI18nManager

__all__ = ["I18nManager", "ModularI18nManager", "I18n", "I18nHelper"]

I18n = I18nManager

_global_i18n = None
_global_i18n_lock = threading.Lock()

class I18nHelper:
  """Helper wrapper for compatibility with standalone functions."""

  def __init__(self, manager: I18nManager):
    self._manager = manager

  def t(self, key: str, fallback: str = "", **kwargs) -> str:
    """
    Translate with automatic fallback.

    Args:
      key: Translation key (e.g. "loaders.csv.not_found")
      fallback: Default text if no translation exists
      **kwargs: Interpolation parameters

    Returns:
      str: Translated text or fallback
    """
    try:
      return self._manager.t(key, **kwargs)
    except (KeyError, Exception):
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
  Uses singleton pattern for performance with double-checked locking
  to avoid race conditions in async/multi-thread environments.

  Returns:
    I18nHelper: Helper with fallback support

  Example:
    >>> from personality.i18n import get_i18n
    >>> error = get_i18n().t("module.error", "Error: {msg}", msg="test")
  """
  global _global_i18n
  if _global_i18n is None:
    with _global_i18n_lock:
      if _global_i18n is None:
        _global_i18n = I18nHelper(I18nManager())
  return _global_i18n