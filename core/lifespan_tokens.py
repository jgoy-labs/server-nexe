"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_tokens.py
Description: Bootstrap token generation and display.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Bug 11: handle de la background task de renovacio del bootstrap token.
# Permet cancellar-la net al shutdown del lifespan.
_renewal_task: Optional[asyncio.Task] = None


def generate_bootstrap_token() -> str:
  """
  Generates high entropy bootstrap token.

  Format: Nexe-XXXXXXXXXXXXXXXXXXXX (24 alphanumeric chars)
  Entropy: 128 bits (computationally infeasible to brute force)

  SECURITY CHANGE (2025-11-28):
  - BEFORE: WORD-WORD-NNNNNN (28.5 bits, brute force <1h)
  - NOW: Nexe-{hex(16)} (128 bits, infeasible)

  The token remains relatively easy to copy manually
  but is now cryptographically secure.

  Returns:
    Token en format Nexe-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX (35 chars total)
  """
  random_part = secrets.token_hex(16)
  return f"Nexe-{random_part.upper()}"


def setup_bootstrap_tokens(server_state, _translate) -> None:
  """Generate or retrieve bootstrap token and display if in development mode."""
  bootstrap_ttl = int(os.getenv('NEXE_BOOTSTRAP_TTL', os.getenv('BOOTSTRAP_TTL', '30')))

  # Use persistent DB to share token across workers without overwriting a valid existing one.
  from core.bootstrap_tokens import set_bootstrap_token, get_bootstrap_token

  existing_bootstrap = get_bootstrap_token()
  token_to_display = None

  # If it doesn't exist or has expired, generate a new one
  if not existing_bootstrap or (datetime.now(timezone.utc).timestamp() > existing_bootstrap["expires"]):
    token_to_display = generate_bootstrap_token()
    set_bootstrap_token(token_to_display, ttl_minutes=bootstrap_ttl)
    logger.info("New master bootstrap token generated and persisted")
  else:
    token_to_display = existing_bootstrap["token"]
    logger.info("Using existing master bootstrap token from DB")

  nexe_env = os.getenv('NEXE_ENV', 'production').lower()
  # Bootstrap logic is only relevant in development mode
  bootstrap_display = os.getenv('NEXE_BOOTSTRAP_DISPLAY', 'true').lower() == 'true'

  if nexe_env == "development" and bootstrap_display:
    title = _translate(server_state.i18n, "core.server.bootstrap_token_title",
      "NEXE FRAMEWORK INITIALIZATION CODE")
    from core.config import DEFAULT_HOST, DEFAULT_PORT
    _srv = server_state.config.get("core", {}).get("server", {})
    _nexe_url = os.environ.get(
        "NEXE_API_BASE_URL",
        f"http://{_srv.get('host', DEFAULT_HOST)}:{_srv.get('port', DEFAULT_PORT)}",
    )
    url_msg = _translate(server_state.i18n, "core.server.bootstrap_token_url",
      "URL: {url}", url=_nexe_url)
    expiry_msg = _translate(server_state.i18n, "core.server.bootstrap_token_expiry",
      "Expires in: {minutes} minutes", minutes=bootstrap_ttl)
    copy_msg = _translate(server_state.i18n, "core.server.bootstrap_token_copy_instruction",
      "COPY this code to the browser when prompted")
    single_use_msg = _translate(server_state.i18n, "core.server.bootstrap_token_single_use",
      "This code only works ONCE")

    logger.info(
      f"\n+==================================================================+\n"
      f"|                                  |\n"
      f"| {title:<62}|\n"
      f"|                                  |\n"
      f"|   {token_to_display:<58}|\n"
      f"|                                  |\n"
      f"| {expiry_msg:<62}|\n"
      f"| {url_msg:<62}|\n"
      f"|                                  |\n"
      f"| {copy_msg:<62}|\n"
      f"| {single_use_msg:<62}|\n"
      f"|                                  |\n"
      f"+==================================================================+"
    )

  msg = _translate(server_state.i18n, "core.server.bootstrap_token_generated",
    "Bootstrap token persisted to DB (expires in {minutes} min)", minutes=bootstrap_ttl)
  logger.info(msg)


def regenerate_bootstrap_token(ttl_minutes: int = 30) -> str:
  """Generate i emmagatzema un nou master bootstrap token a la DB.

  Bug 11: usat per la background task d'auto-renovacio i pels tests.
  Retorna el nou token.
  """
  from core.bootstrap_tokens import set_bootstrap_token

  new_token = generate_bootstrap_token()
  set_bootstrap_token(new_token, ttl_minutes=ttl_minutes)
  logger.info("Bootstrap token regenerated (expires in %d min)", ttl_minutes)
  return new_token


# Fix Consultor passada 1 — Finding 4: backoffs per al retry exponencial
# quan la regeneracio del token falla (p.ex. disc ple). Abans el loop
# esperava l'interval_seconds complet (>5 min) i el token expirava.
_BOOTSTRAP_RETRY_BACKOFFS = (1, 5, 30)  # segons


async def _bootstrap_token_renewal_loop(interval_seconds: int, ttl_minutes: int):
  """Loop background que renova el token cada `interval_seconds`.

  Bug 11: solucio (b) — background task que regenera el token abans
  que expiri, evitant la mala UX d'haver de reiniciar el servidor.

  Fix Consultor passada 1 — Finding 4: si la regeneracio falla, no
  esperem l'interval sencer; apliquem retry exponencial (1s, 5s, 30s)
  abans de tornar al cicle normal.
  """
  try:
    while True:
      await asyncio.sleep(interval_seconds)
      try:
        regenerate_bootstrap_token(ttl_minutes=ttl_minutes)
      except asyncio.CancelledError:
        raise
      except Exception as e:  # noqa: BLE001 — defensive: no aturar el loop
        logger.error("Bootstrap token regeneration failed: %s", e)
        recovered = False
        for delay in _BOOTSTRAP_RETRY_BACKOFFS:
          await asyncio.sleep(delay)
          try:
            regenerate_bootstrap_token(ttl_minutes=ttl_minutes)
            logger.info(
              "Bootstrap token recovered after %ds", delay
            )
            recovered = True
            break
          except asyncio.CancelledError:
            raise
          except Exception as e2:  # noqa: BLE001
            logger.warning(
              "Bootstrap token retry after %ds failed: %s", delay, e2
            )
        if not recovered:
          logger.error(
            "Bootstrap token renewal: all retries exhausted, "
            "will try again in %ds", interval_seconds,
          )
  except asyncio.CancelledError:
    logger.info("Bootstrap token renewal loop cancelled")
    raise


def start_bootstrap_token_renewal(ttl_minutes: int = 30, interval_seconds: Optional[int] = None) -> asyncio.Task:
  """Arrencar la background task de renovacio (Bug 11).

  Args:
    ttl_minutes: TTL del token nou (default 30)
    interval_seconds: cada quants segons regenerar (default = (ttl-5)*60)

  Returns:
    L'asyncio.Task creada (es guarda tambe en variable de modul).
  """
  global _renewal_task
  if interval_seconds is None:
    # Renovar 5 min abans d'expirar perque mai hi hagi finestra sense token
    interval_seconds = max(60, (ttl_minutes - 5) * 60)

  if _renewal_task is not None and not _renewal_task.done():
    logger.warning("Bootstrap token renewal task already running — replacing")
    _renewal_task.cancel()

  _renewal_task = asyncio.create_task(
    _bootstrap_token_renewal_loop(interval_seconds, ttl_minutes),
    name="bootstrap_token_renewal",
  )
  logger.info(
    "Bootstrap token auto-renewal started (every %ds, ttl=%dmin)",
    interval_seconds, ttl_minutes,
  )
  return _renewal_task


async def stop_bootstrap_token_renewal() -> None:
  """Cancel·lar la background task de renovacio i esperar net (Bug 11)."""
  global _renewal_task
  if _renewal_task is None:
    return
  if _renewal_task.done():
    _renewal_task = None
    return
  _renewal_task.cancel()
  try:
    await _renewal_task
  except asyncio.CancelledError:
    pass
  except Exception as e:  # noqa: BLE001
    logger.error("Error stopping bootstrap token renewal task: %s", e)
  finally:
    _renewal_task = None
  logger.info("Bootstrap token renewal task stopped")
