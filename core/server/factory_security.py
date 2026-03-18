"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/server/factory_security.py
Description: Security Setup and Validation for Nexe Server Factory.

www.jgoy.net · https://server-nexe.org
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

def validate_production_security(i18n: Any, config: Any = None) -> None:
  """
  Validate production security requirements (module allowlist).

  Uses core.config.get_module_allowlist() as single source of truth.

  Raises:
    ValueError: If NEXE_APPROVED_MODULES is not set in production mode

  Args:
    i18n: I18n manager
    config: Configuration dictionary (optional, for server.toml environment mode)
  """
  from core.config import get_module_allowlist

  core_env = os.getenv("NEXE_ENV", "development").lower()
  # Also check server.toml config for environment mode
  config_mode = config.get("core", {}).get("environment", {}).get("mode", "").lower() if config else ""
  is_production = core_env == "production" or config_mode == "production"
  approved_modules = os.getenv("NEXE_APPROVED_MODULES", "").strip()

  try:
    allowlist = get_module_allowlist()
  except ValueError:
    error_msg = translate(
      i18n,
      "core.server.security.production_no_allowlist",
      "SECURITY ERROR: NEXE_APPROVED_MODULES is required in production mode.\n"
      "Please set NEXE_APPROVED_MODULES environment variable with a comma-separated list of approved modules.\n"
      "Example: export NEXE_APPROVED_MODULES='security,observability,rag'"
    )
    logger.error(error_msg)
    raise ValueError(error_msg)

  if allowlist is not None:
    logger.info(translate(i18n, "core.server.security.production_allowlist_active",
               "Production mode: Module allowlist active ({modules})", modules=approved_modules))
  elif core_env == "staging":
    logger.warning(translate(i18n, "core.server.security.staging_no_allowlist_warning",
                "Staging mode without NEXE_APPROVED_MODULES - all discovered modules will be loaded"))
  else:
    logger.debug(translate(i18n, "core.server.security.development_no_allowlist",
              "Development mode: All discovered modules allowed (no allowlist)"))

__all__ = ['setup_security_logger', 'validate_production_security']