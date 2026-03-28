"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_tokens.py
Description: Bootstrap token generation and display.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import secrets
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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
    _srv = server_state.config.get("core", {}).get("server", {})
    _nexe_url = os.environ.get("NEXE_API_BASE_URL", f"http://{_srv.get('host', '127.0.0.1')}:{_srv.get('port', 9119)}")
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
