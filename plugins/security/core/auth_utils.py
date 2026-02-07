"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/auth_utils.py
Description: Utilities for the Nexe authentication system.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import HTTPException, Header
from typing import Optional
import secrets

from .auth_config import get_admin_api_key, is_dev_mode
from .messages import get_message

def _resolve_i18n() -> Optional[object]:
  try:
    from core.container import get_service
    return get_service("i18n")
  except Exception:
    return None

def generate_api_key(length: int = 32) -> str:
  """
  Generate a secure API key.

  Args:
    length: Key length (default 32 bytes = 64 hex chars)

  Returns:
    Hexadecimal API key

  Usage:
    new_key = generate_api_key()
    print(f"export NEXE_PRIMARY_API_KEY='{new_key}'")
  """
  return secrets.token_hex(length)

def verify_api_key(
  x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API Key")
) -> str:
  """
  Verify an API key and raise 401 if it is invalid.

  ✅ SECURITY FIX: Now raises HTTPException(401) instead of returning False
  This ensures endpoints with Depends(verify_api_key) are protected.

  Compatible with FastAPI Depends() and manual calls.

  Args:
    x_api_key: API key from X-API-Key header (automatic with Depends)

  Returns:
    str: The valid API key (if correct)

  Raises:
    HTTPException: 401 if the key is invalid or not configured

  Usage:
    @router.get("/protected")
    async def protected(_: str = Depends(verify_api_key)):
      return {"data": "secret"}

    try:
      verify_api_key("my-api-key")
    except HTTPException:
      pass
  """
  admin_key = get_admin_api_key()
  i18n = _resolve_i18n()

  if not admin_key:
    raise HTTPException(
      status_code=401,
      detail=get_message(
        i18n,
        "security.auth.key_not_configured",
        fallback="API key not configured on server"
      )
    )

  if not x_api_key:
    raise HTTPException(
      status_code=401,
      detail=get_message(
        i18n,
        "security.auth.missing_key",
        fallback="API key required"
      )
    )

  if not secrets.compare_digest(x_api_key, admin_key):
    raise HTTPException(
      status_code=401,
      detail=get_message(
        i18n,
        "security.auth.invalid_key",
        fallback="Invalid API key"
      )
    )

  return x_api_key

__all__ = [
  'generate_api_key',
  'verify_api_key',
]
