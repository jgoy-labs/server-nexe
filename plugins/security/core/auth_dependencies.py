"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/core/auth_dependencies.py
Description: FastAPI dependencies for Nexe authentication with dual-key support.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import HTTPException, Header, Request
from typing import Optional
import os
import ipaddress
from datetime import datetime, timezone
import secrets

from .auth_models import KeyStatus
from .auth_config import load_api_keys, is_dev_mode, get_admin_api_key
from .messages import get_message

try:
  from plugins.observability.prometheus_metrics import (
    record_auth_attempt,
    record_auth_failure,
    update_key_expiry_days,
    update_key_status,
    set_grace_period_active
  )
  METRICS_ENABLED = True
except ImportError:
  METRICS_ENABLED = False
  def record_auth_attempt(*args, **kwargs): pass
  def record_auth_failure(*args, **kwargs): pass
  def update_key_expiry_days(*args, **kwargs): pass
  def update_key_status(*args, **kwargs): pass
  def set_grace_period_active(*args, **kwargs): pass

def _is_loopback_ip(ip: str) -> bool:
  try:
    addr = ipaddress.ip_address(ip)
  except ValueError:
    return False
  return addr.is_loopback

def _update_key_metrics(keys_config) -> None:
  if keys_config.primary:
    if keys_config.primary.expires_at:
      days_remaining = (keys_config.primary.expires_at - datetime.now(timezone.utc)).days
      update_key_expiry_days('primary', days_remaining)
    else:
      update_key_expiry_days('primary', -1)
    update_key_status('primary', keys_config.primary.status.value)
  else:
    update_key_status('primary', 'not_configured')

  if keys_config.secondary:
    if keys_config.secondary.expires_at:
      days_remaining = (keys_config.secondary.expires_at - datetime.now(timezone.utc)).days
      update_key_expiry_days('secondary', days_remaining)
    else:
      update_key_expiry_days('secondary', -1)
    update_key_status('secondary', keys_config.secondary.status.value)
  else:
    update_key_status('secondary', 'not_configured')

  set_grace_period_active(keys_config.secondary and keys_config.secondary.is_valid)


def _check_dev_mode(request: Request, dev_mode: bool) -> str:
  """Bypass auth in dev mode if the request comes from localhost."""
  if dev_mode:
    client_ip = request.client.host if request.client else "unknown"
    allow_remote = os.getenv("NEXE_DEV_MODE_ALLOW_REMOTE", "false").lower() == "true"
    if not allow_remote and not _is_loopback_ip(client_ip):
      raise HTTPException(
        status_code=403,
        detail="DEV mode bypass only allowed from localhost"
      )
    try:
      from plugins.security.security_logger import get_security_logger, SecurityEventType, SecuritySeverity
      security_logger = get_security_logger()
      security_logger.log_event(
        event_type=SecurityEventType.AUTH_SUCCESS,
        severity=SecuritySeverity.WARNING,
        message="DEV MODE: API key bypassed",
        details={"warning": "NOT for production!"}
      )
    except ImportError:
      pass
    return "dev-mode-bypass"
  raise HTTPException(
    status_code=500,
    detail="Server misconfiguration: No valid API key configured"
  )


def _authenticate_primary(x_api_key: str, keys_config, request: Request) -> Optional[str]:
  """Attempt constant-time authentication against the primary API key."""
  if keys_config.primary and keys_config.primary.is_valid:
    if secrets.compare_digest(x_api_key, keys_config.primary.key):
      record_auth_attempt('success', 'primary', request.url.path)
      try:
        from plugins.security.security_logger import get_security_logger, SecurityEventType, SecuritySeverity
        security_logger = get_security_logger()
        security_logger.log_event(
          event_type=SecurityEventType.AUTH_SUCCESS,
          severity=SecuritySeverity.INFO,
          message="Authentication with primary API key",
          details={
            "key_type": "primary",
            "expires_at": keys_config.primary.expires_at.isoformat() if keys_config.primary.expires_at else None
          }
        )
      except ImportError:
        pass
      return x_api_key
  return None


def _authenticate_secondary(x_api_key: str, keys_config, request: Request) -> Optional[str]:
  """Attempt constant-time authentication against the secondary (deprecated) key."""
  if keys_config.secondary and keys_config.secondary.is_valid:
    if secrets.compare_digest(x_api_key, keys_config.secondary.key):
      record_auth_attempt('success', 'secondary', request.url.path)
      try:
        from plugins.security.security_logger import get_security_logger, SecurityEventType, SecuritySeverity
        security_logger = get_security_logger()
        security_logger.log_event(
          event_type=SecurityEventType.AUTH_SUCCESS,
          severity=SecuritySeverity.WARNING,
          message="Authentication with secondary API key (deprecated)",
          details={
            "key_type": "secondary",
            "action_required": "MIGRATE TO PRIMARY KEY",
            "expires_at": keys_config.secondary.expires_at.isoformat() if keys_config.secondary.expires_at else None
          }
        )
      except ImportError:
        pass
      return x_api_key
  return None


def _log_failure(request: Request, keys_config) -> None:
  """Record an authentication failure to metrics and the IRONCLAD security log."""
  failure_reason = "invalid_api_key"
  if keys_config.primary and keys_config.primary.status == KeyStatus.EXPIRED:
    failure_reason = "primary_key_expired"
  if keys_config.secondary and keys_config.secondary.status == KeyStatus.EXPIRED:
    failure_reason = "secondary_key_expired"

  record_auth_failure(failure_reason)

  try:
    from plugins.security.security_logger import get_security_logger
    security_logger = get_security_logger()
    security_logger.log_auth_failure(
      reason=failure_reason,
      ip_address=request.client.host if request.client else "unknown"
    )
  except ImportError:
    pass


async def require_api_key(
  request: Request,
  x_api_key: Optional[str] = Header(None, description="Admin API Key"),
  authorization: Optional[str] = Header(None, description="Bearer token (sidecar fallback)")
) -> str:
  """
  FastAPI Dependency to validate mandatory API key.
  Dual-key support with expiry validation.
  Fail-closed by default (no bypass without explicit configuration).

  Returns the API key if valid, otherwise HTTPException 401/500

  Usage in routers:

    @router.post("/admin/endpoint")
    async def protected_endpoint(api_key: str = Depends(require_api_key)):
      return {"status": "authenticated"}

  Configuration (dual-key recommended):
    NEXE_PRIMARY_API_KEY, NEXE_PRIMARY_KEY_EXPIRES
    NEXE_SECONDARY_API_KEY, NEXE_SECONDARY_KEY_EXPIRES

  Configuration (legacy, single field):
    NEXE_ADMIN_API_KEY

  Dev mode (optional):
    NEXE_DEV_MODE=true
  """
  keys_config = load_api_keys()
  dev_mode = is_dev_mode()

  _update_key_metrics(keys_config)

  if not keys_config.has_any_valid_key:
    return _check_dev_mode(request, dev_mode)

  # Sidecar fallback: accept Authorization: Bearer <key> when X-API-Key is absent
  if not x_api_key and authorization:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
      x_api_key = token

  if not x_api_key:
    record_auth_failure('missing_key')
    # Q3.1 fix: read i18n from app.state instead of None (security fix)
    _i18n = getattr(request.app.state, 'i18n', None)
    raise HTTPException(
      status_code=401,
      detail=get_message(_i18n, "security.auth.missing_key"),
      headers={"WWW-Authenticate": "ApiKey"}
    )

  result = _authenticate_primary(x_api_key, keys_config, request)
  if result:
    return result

  result = _authenticate_secondary(x_api_key, keys_config, request)
  if result:
    return result

  _log_failure(request, keys_config)
  raise HTTPException(
    status_code=401,
    detail="Invalid or expired API key",
    headers={"WWW-Authenticate": "ApiKey"}
  )

async def optional_api_key(
  x_api_key: Optional[str] = Header(None, description="Optional API Key")
) -> Optional[str]:
  """
  Optional dependency: validates key if present, but does not block if absent

  Returns the API key if valid, None if absent/invalid

  Usage:
    @router.get("/endpoint")
    async def flexible_endpoint(api_key: Optional[str] = Depends(optional_api_key)):
      if api_key:
        return {"data": "sensitive"}
      else:
        return {"data": "public"}
  """

  keys_config = load_api_keys()
  admin_key = get_admin_api_key()
  dev_mode = is_dev_mode()

  if dev_mode and not admin_key:
    return None

  if not x_api_key:
    return None

  if keys_config.primary and keys_config.primary.is_valid:
    if secrets.compare_digest(x_api_key, keys_config.primary.key):
      return x_api_key

  if keys_config.secondary and keys_config.secondary.is_valid:
    if secrets.compare_digest(x_api_key, keys_config.secondary.key):
      return x_api_key

  if admin_key and secrets.compare_digest(x_api_key, admin_key):
    return x_api_key

  return None

__all__ = [
  'require_api_key',
  'optional_api_key',
]
