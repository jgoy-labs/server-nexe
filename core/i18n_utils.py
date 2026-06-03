"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/i18n_utils.py
Description: Canonical translate() helper. Unifica la traducció amb
fallback que estava reimplementada a helpers.translate, bootstrap._t,
system._t i inline a root.py amb maneig d'error inconsistent.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)


def translate(i18n, key: str, fallback: str, **kwargs) -> str:
  """
  Translate a key with fallback support and format parameters.

  Variant defensiva (la més segura): qualsevol error de l'i18n manager
  degrada al fallback formatat, de manera que els call-sites mai propaguen
  excepcions de traducció. Unifica el comportament previ sense regressions.

  Args:
    i18n: I18n manager instance (can be None)
    key: Translation key
    fallback: Fallback text if key not found
    **kwargs: Format parameters for string interpolation

  Returns:
    Translated text or fallback (with formatting applied)
  """
  try:
    if not i18n:
      return fallback.format(**kwargs) if kwargs else fallback
    value = i18n.t(key, **kwargs)
    if value == key:
      return fallback.format(**kwargs) if kwargs else fallback
    return value
  except Exception:
    # AP-G01: log diagnòstic sense canviar el flux (degrada al fallback formatat)
    logger.debug("translate() degraded to fallback for key '%s'", key, exc_info=True)
    return fallback.format(**kwargs) if kwargs else fallback
