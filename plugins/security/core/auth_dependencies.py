"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/auth_dependencies.py
Description: FastAPI dependencies for Nexe authentication with dual-key support.

www.jgoy.net
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

def _get_i18n(request: Request):
  try:
    return getattr(request.app.state, "i18n", None)
  except Exception:
    return None

async def require_api_key(
  request: Request,
  x_api_key: Optional[str] = Header(None, description="Admin API Key")
) -> str:
  """
  FastAPI dependency to validate a required API key
  ✅ Phase 2.1: Dual-key support with expiry validation
  ✅ SECURITY FIX: Fail-closed by default (no bypass without explicit configuration)

  Returns the API key if valid, otherwise HTTPException 401/500

  Usage in routers:

    @router.post("/admin/endpoint")
    async def protected_endpoint(api_key: str = Depends(require_api_key)):
      return {"status": "authenticated"}

  PRODUCTION config (Phase 2.1 dual-key):
    export NEXE_PRIMARY_API_KEY="new-key-here"
    export NEXE_PRIMARY_KEY_EXPIRES="2026-01-10T00:00:00Z"
    export NEXE_SECONDARY_API_KEY="old-key-here"
    export NEXE_SECONDARY_KEY_EXPIRES="2025-10-17T00:00:00Z"

  DEV config (optional, local development only):
    export NEXE_DEV_MODE="true"
  """
  keys_config = load_api_keys()
  dev_mode = is_dev_mode()
  i18n = _get_i18n(request)

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

  if not keys_config.has_any_valid_key:
    if dev_mode:
      client_ip = request.client.host if request.client else "unknown"
      allow_remote = os.getenv("NEXE_DEV_MODE_ALLOW_REMOTE", "false").lower() == "true"
      if not allow_remote and not _is_loopback_ip(client_ip):
        raise HTTPException(
          status_code=403,
          detail=get_message(
            i18n,
            "security.auth.dev_mode_localhost_only",
            fallback="DEV mode bypass only allowed from localhost"
          )
        )
      try:
        from plugins.security_logger import get_security_logger, SecurityEventType, SecuritySeverity
        security_logger = get_security_logger()
        security_logger.log_event(
          event_type=SecurityEventType.AUTH_SUCCESS,
          severity=SecuritySeverity.WARNING,
          message=get_message(i18n, "security.auth.dev_mode_bypass"),
          details={"warning": get_message(i18n, "security.auth.dev_mode_warning")}
        )
      except ImportError:
        pass
      return "dev-mode-bypass"
    else:
      raise HTTPException(
        status_code=500,
        detail=get_message(
          i18n,
          "security.auth.server_misconfigured_no_valid_key",
          fallback="Server misconfiguration: No valid API key configured"
        )
      )

  if not x_api_key:


    record_auth_failure('missing_key')
    raise HTTPException(
      status_code=401,
      detail=get_message(i18n, "security.auth.missing_key"),
      headers={"WWW-Authenticate": "ApiKey"}
    )

  if keys_config.primary and keys_config.primary.is_valid:
    if secrets.compare_digest(x_api_key, keys_config.primary.key):
      record_auth_attempt('success', 'primary', request.url.path)

      try:
        from plugins.security_logger import get_security_logger, SecurityEventType, SecuritySeverity
        security_logger = get_security_logger()
        security_logger.log_event(
          event_type=SecurityEventType.AUTH_SUCCESS,
          severity=SecuritySeverity.INFO,
          message=get_message(i18n, "security.auth.primary_key_auth"),
          details={
            "key_type": "primary",
            "expires_at": keys_config.primary.expires_at.isoformat() if keys_config.primary.expires_at else None
          }
        )
      except ImportError:
        pass
      return x_api_key

  if keys_config.secondary and keys_config.secondary.is_valid:
    if secrets.compare_digest(x_api_key, keys_config.secondary.key):
      record_auth_attempt('success', 'secondary', request.url.path)

      try:
        from plugins.security_logger import get_security_logger, SecurityEventType, SecuritySeverity
        security_logger = get_security_logger()
        security_logger.log_event(
          event_type=SecurityEventType.AUTH_SUCCESS,
          severity=SecuritySeverity.WARNING,
          message=get_message(i18n, "security.auth.secondary_key_auth"),
          details={
            "key_type": "secondary",
            "action_required": get_message(i18n, "security.auth.secondary_key_action_required"),
            "expires_at": keys_config.secondary.expires_at.isoformat() if keys_config.secondary.expires_at else None
          }
        )
      except ImportError:
        pass
      return x_api_key

  failure_reason = "invalid_api_key"
  if keys_config.primary and keys_config.primary.status == KeyStatus.EXPIRED:
    failure_reason = "primary_key_expired"
  if keys_config.secondary and keys_config.secondary.status == KeyStatus.EXPIRED:
    failure_reason = "secondary_key_expired"

  record_auth_failure(failure_reason)

  try:
    from plugins.security_logger import get_security_logger, SecurityEventType, SecuritySeverity
    security_logger = get_security_logger()
    security_logger.log_auth_failure(
      reason=failure_reason,
      ip_address="unknown"
    )
  except ImportError:
    pass

  raise HTTPException(
    status_code=401,
    detail=get_message(
      i18n,
      "security.auth.invalid_or_expired_key",
      fallback="Invalid or expired API key"
    ),
    headers={"WWW-Authenticate": "ApiKey"}
  )

async def optional_api_key(
  x_api_key: Optional[str] = Header(None, description="Optional API Key")
) -> Optional[str]:
  """
  Optional dependency: validate if key is present, but do not block if absent

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
