"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/i18n/__init__.py
Description: Package marker per sistema d'internacionalització. Exporta I18nManager (base)

www.jgoy.net
────────────────────────────────────
"""

from .i18n_manager import I18nManager
from .modular_i18n import ModularI18nManager

I18n = I18nManager

_global_i18n = None

class I18nHelper:
  """Helper wrapper per compatibilitat amb funcions standalone."""

  def __init__(self, manager: I18nManager):
    self._manager = manager

  def t(self, key: str, fallback: str = "", **kwargs) -> str:
    """
    Tradueix amb fallback automàtic.

    Args:
      key: Clau de traducció (e.g. "loaders.csv.not_found")
      fallback: Text per defecte si no hi ha traducció
      **kwargs: Paràmetres per interpolació

    Returns:
      str: Text traduït o fallback
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
  Retorna instància global de I18nHelper.

  Útil per funcions standalone que no tenen accés a self._t().
  Usa singleton pattern per performance.

  Returns:
    I18nHelper: Helper amb suport per fallback

  Example:
    >>> from personality.i18n import get_i18n
    >>> error = get_i18n().t("module.error", "Error: {msg}", msg="test")
  """
  global _global_i18n
  if _global_i18n is None:
    _global_i18n = I18nHelper(I18nManager())
  return _global_i18n