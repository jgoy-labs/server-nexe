"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/auth.py
Description: Centralized Nexe authentication system with API key support.

www.jgoy.net
────────────────────────────────────
"""

from .auth_models import (
  KeyStatus,
  ApiKeyData,
  ApiKeyConfig,
)

from .auth_config import (
  parse_datetime_or_none,
  load_api_keys,
  get_admin_api_key,
  is_dev_mode,
  ADMIN_API_KEY,
  DEV_MODE,
)

from .auth_dependencies import (
  require_api_key,
  optional_api_key,
)

from .auth_utils import (
  generate_api_key,
  verify_api_key,
)

__all__ = [
  'KeyStatus',
  'ApiKeyData',
  'ApiKeyConfig',

  'parse_datetime_or_none',
  'load_api_keys',
  'get_admin_api_key',
  'is_dev_mode',
  'ADMIN_API_KEY',
  'DEV_MODE',

  'require_api_key',
  'optional_api_key',

  'generate_api_key',
  'verify_api_key',
]

__version__ = "3.0.0"
__author__ = "J.Goy + Nexe Team"
