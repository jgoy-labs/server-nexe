"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/core/auth_utils.py
Description: Utilities for the Nexe authentication system.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import HTTPException, Header
from typing import Optional
import secrets

from .auth_config import get_admin_api_key

def generate_api_key(length: int = 32) -> str:
  """
  Generates a secure API key

  Args:
    length: Key length (default 32 bytes = 64 hex chars)

  Returns:
    Hexadecimal API key

  Usage:
    new_key = generate_api_key()
    print(f"export NEXE_ADMIN_API_KEY='{new_key}'")
  """
  return secrets.token_hex(length)

def verify_api_key(
  x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API Key")
) -> str:
  """
  Verifies an API key and raises 401 if not valid

  ✅ SECURITY FIX: Now raises HTTPException(401) instead of returning False
  This ensures that endpoints with Depends(verify_api_key) are protected.

  Compatible with FastAPI Depends() and manual calls.

  Args:
    x_api_key: API key from the X-API-Key header (automatic with Depends)

  Returns:
    str: The valid API key (if correct)

  Raises:
    HTTPException: 401 if the key is not valid or not configured

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

  if not admin_key:
    raise HTTPException(
      status_code=401,
      detail="API key not configured on server"
    )

  if not x_api_key:
    raise HTTPException(
      status_code=401,
      detail="API key required"
    )

  if not secrets.compare_digest(x_api_key, admin_key):
    raise HTTPException(
      status_code=401,
      detail="Invalid API key"
    )

  return x_api_key

__all__ = [
  'generate_api_key',
  'verify_api_key',
]