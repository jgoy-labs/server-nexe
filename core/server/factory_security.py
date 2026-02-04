"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/factory_security.py
Description: Security Setup and Validation for Nexe Server Factory.

www.jgoy.net
────────────────────────────────────
"""

import logging
import os
from fastapi import FastAPI
from pathlib import Path
from typing import Any

from .helpers import translate

logger = logging.getLogger(__name__)

def setup_security_logger(app: FastAPI, project_root: Path, i18n: Any) -> None:
  """
  Initialize SecurityLogger (SIEM) for the application.

  Args:
    app: FastAPI application
    project_root: Project root path
    i18n: I18n manager
  """
  from plugins.security_logger import SecurityEventLogger

  logs_base = project_root / "storage" / "system-logs" / "security"
  app.state.security_logger = SecurityEventLogger(log_dir=logs_base)
  logger.info(translate(i18n, "core.server.security_logger_initialized",
             "SecurityLogger initialized (SIEM logging active)"))

def validate_production_security(i18n: Any) -> None:
  """
  Validate production security requirements (module allowlist).

  Raises:
    ValueError: If NEXE_APPROVED_MODULES is not set in production mode

  Args:
    i18n: I18n manager
  """
  core_env = os.getenv("NEXE_ENV", "development").lower()
  approved_modules = os.getenv("NEXE_APPROVED_MODULES", "").strip()

  if core_env == "production":
    if not approved_modules:
      error_msg = translate(
        i18n,
        "core.server.security.production_no_allowlist",
        "SECURITY ERROR: NEXE_APPROVED_MODULES is required in production mode.\n"
        "Please set NEXE_APPROVED_MODULES environment variable with a comma-separated list of approved modules.\n"
        "Example: export NEXE_APPROVED_MODULES='security,observability,rag'"
      )
      logger.error(error_msg)
      raise ValueError(error_msg)
    logger.info(translate(i18n, "core.server.security.production_allowlist_active",
               "Production mode: Module allowlist active ({modules})", modules=approved_modules))
  elif core_env == "staging":
    if not approved_modules:
      logger.warning(translate(i18n, "core.server.security.staging_no_allowlist_warning",
                  "Staging mode without NEXE_APPROVED_MODULES - all discovered modules will be loaded"))
  else:
    if not approved_modules:
      logger.debug(translate(i18n, "core.server.security.development_no_allowlist",
                "Development mode: All discovered modules allowed (no allowlist)"))

__all__ = ['setup_security_logger', 'validate_production_security']