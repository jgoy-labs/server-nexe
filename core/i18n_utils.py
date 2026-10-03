"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/i18n_utils.py
Description: Canonical translate() helper. Unifies the fallback
translation that was reimplemented in helpers.translate, bootstrap._t,
system._t and inline in root.py with inconsistent error handling.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)


def translate(i18n, key: str, fallback: str, **kwargs) -> str:
  """
  Translate a key with fallback support and format parameters.

  Defensive variant (the safest): any error from the i18n manager
  degrades to the formatted fallback, so call sites never propagate
  translation exceptions. Unifies the previous behaviour without regressions.

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
    # AP-G01: diagnostic log without changing the flow (degrades to the formatted fallback)
    logger.debug("translate() degraded to fallback for key '%s'", key, exc_info=True)
    return fallback.format(**kwargs) if kwargs else fallback
