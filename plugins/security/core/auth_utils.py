"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/auth_utils.py
Description: Utilitats per al sistema d'autenticació Nexe.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import HTTPException, Header
from typing import Optional
import secrets

from .auth_config import get_admin_api_key, is_dev_mode

def generate_api_key(length: int = 32) -> str:
  """
  Genera una API key segura

  Args:
    length: Longitud de la key (default 32 bytes = 64 hex chars)

  Returns:
    API key hexadecimal

  Usage:
    new_key = generate_api_key()
    print(f"export NEXE_ADMIN_API_KEY='{new_key}'")
  """
  return secrets.token_hex(length)

def verify_api_key(
  x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API Key")
) -> str:
  """
  Verifica una API key i llença 401 si no és vàlida

  ✅ SECURITY FIX: Ara llença HTTPException(401) en lloc de retornar False
  Això garanteix que endpoints amb Depends(verify_api_key) estan protegits.

  Compatible amb FastAPI Depends() i crides manuals.

  Args:
    x_api_key: API key del header X-API-Key (automàtic amb Depends)

  Returns:
    str: La API key vàlida (si correcta)

  Raises:
    HTTPException: 401 si la key no és vàlida o no configurada

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