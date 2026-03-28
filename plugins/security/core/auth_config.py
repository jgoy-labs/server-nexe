"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/core/auth_config.py
Description: Configuration functions for Nexe authentication system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from datetime import datetime
from typing import Optional
import os

from .auth_models import ApiKeyData, ApiKeyConfig

def parse_datetime_or_none(value: Optional[str]) -> Optional[datetime]:
  """Parse ISO datetime string or return None."""
  if not value:
    return None

  try:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))
  except (ValueError, AttributeError):
    return None

def load_api_keys() -> ApiKeyConfig:
  """
  Load API key configuration from environment variables.

  Supports dual-key rotation with expiry timestamps:
  - NEXE_PRIMARY_API_KEY: Active key
  - NEXE_PRIMARY_KEY_EXPIRES: ISO datetime (optional)
  - NEXE_SECONDARY_API_KEY: Grace period key (optional)
  - NEXE_SECONDARY_KEY_EXPIRES: ISO datetime (optional)

  Backward compatibility:
  - NEXE_ADMIN_API_KEY: Falls back to primary if new vars not set

  Returns:
    ApiKeyConfig with primary/secondary keys

  Example:
    export NEXE_PRIMARY_API_KEY="abc123..."
    export NEXE_PRIMARY_KEY_EXPIRES="2026-01-10T00:00:00Z"
    export NEXE_SECONDARY_API_KEY="old-key..."
    export NEXE_SECONDARY_KEY_EXPIRES="2025-10-17T00:00:00Z"
  """
  primary_key = os.getenv("NEXE_PRIMARY_API_KEY", "")
  primary_expires = parse_datetime_or_none(os.getenv("NEXE_PRIMARY_KEY_EXPIRES"))
  primary_created = parse_datetime_or_none(os.getenv("NEXE_PRIMARY_KEY_CREATED"))

  secondary_key = os.getenv("NEXE_SECONDARY_API_KEY", "")
  secondary_expires = parse_datetime_or_none(os.getenv("NEXE_SECONDARY_KEY_EXPIRES"))
  secondary_created = parse_datetime_or_none(os.getenv("NEXE_SECONDARY_KEY_CREATED"))

  if not primary_key:
    primary_key = os.getenv("NEXE_ADMIN_API_KEY", "")

  primary = ApiKeyData(
    key=primary_key,
    expires_at=primary_expires,
    created_at=primary_created
  ) if primary_key else None

  secondary = ApiKeyData(
    key=secondary_key,
    expires_at=secondary_expires,
    created_at=secondary_created
  ) if secondary_key else None

  return ApiKeyConfig(primary=primary, secondary=secondary)

def get_admin_api_key() -> str:
  """
  Get admin API key from environment (dynamic, supports rotation)

  Prioritizes NEXE_PRIMARY_API_KEY over NEXE_ADMIN_API_KEY for
  compatibility with dual-key rotation system.

  Returns:
    Admin API key or empty string if not configured
  """
  config = load_api_keys()
  if config.primary and config.primary.key:
    return config.primary.key
  return ""

def is_dev_mode() -> bool:
  """
  Check if development mode is enabled (dynamic)

  SECURITY: DEV_MODE is BLOCKED when NEXE_ENV=production to prevent
  accidental authentication bypass in production deployments.

  Returns:
    True if NEXE_DEV_MODE="true" AND NEXE_ENV != "production", False otherwise
  """
  is_production = os.getenv("NEXE_ENV", "development").lower() == "production"
  dev_mode_requested = os.getenv("NEXE_DEV_MODE", "false").lower() == "true"

  if is_production and dev_mode_requested:
    import logging
    logger = logging.getLogger(__name__)
    logger.error(
      "SECURITY BLOCK: DEV_MODE cannot be enabled in production! "
      "NEXE_DEV_MODE=true is ignored when NEXE_ENV=production"
    )
    return False

  return dev_mode_requested


__all__ = [
  'parse_datetime_or_none',
  'load_api_keys',
  'get_admin_api_key',
  'is_dev_mode',
]