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
import logging
import os
import ipaddress
from datetime import datetime, timezone
import secrets

from .auth_models import KeyStatus
from .auth_config import load_api_keys, is_dev_mode, get_admin_api_key
from .auth_rate_limit import (
  check_auth_failure_rate_limit,
  record_auth_failure_attempt,
  client_ip,
)
from .messages import get_message

_log = logging.getLogger(__name__)

# Auth metrics hooks. These are no-ops: server-nexe has no Prometheus auth
# instrumentation module yet (the old `plugins.observability.prometheus_metrics`
# import never resolved, so this was always a no-op masquerading behind a dead
# `METRICS_ENABLED` toggle). They stay as module-level callables so call-sites
# and tests can wire/patch them by name when a real metrics backend lands.
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


def presented_api_key(
  x_api_key: Optional[str],
  authorization: Optional[str],
) -> Optional[str]:
  """X-API-Key wins; otherwise Authorization: Bearer (sidecar C25)."""
  if isinstance(x_api_key, str) and x_api_key:
    return x_api_key
  if isinstance(authorization, str) and authorization:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
      return token
  return None


def enforce_failed_auth_rate_limit(request: Request) -> None:
  """429 if this IP already burned the failure window. Call BEFORE compare."""
  ip = client_ip(request)
  if check_auth_failure_rate_limit(ip):
    raise HTTPException(
      status_code=429,
      detail="Too many authentication failures. Try again later.",
    )


def _accept_or_reject_presented_key(
  request: Request,
  presented: Optional[str],
  keys_config,
) -> str:
  """Shared dual-key + expiry check. Counts failures toward the 429 window."""
  enforce_failed_auth_rate_limit(request)
  if not presented:
    record_auth_failure("missing_key")
    record_auth_failure_attempt(client_ip(request))
    _log_failure(request, keys_config)
    _i18n = getattr(request.app.state, "i18n", None)
    raise HTTPException(
      status_code=401,
      detail=get_message(_i18n, "security.auth.missing_key"),
      headers={"WWW-Authenticate": "ApiKey"},
    )
  result = _authenticate_primary(presented, keys_config, request)
  if result:
    return result
  result = _authenticate_secondary(presented, keys_config, request)
  if result:
    return result
  record_auth_failure_attempt(client_ip(request))
  _log_failure(request, keys_config)
  raise HTTPException(
    status_code=401,
    detail="Invalid or expired API key",
    headers={"WWW-Authenticate": "ApiKey"},
  )


async def authenticate_ui_request(
  request: Request,
  x_api_key: Optional[str],
  authorization: Optional[str] = None,
) -> None:
  """Product-path auth (D-I / #883). Same keys as the core, UI fail-closed.

  No key material configured → 503 (never open).
  Configured but expired / wrong → 401.
  Bearer and secondary are accepted. Failures share the core 429 window.
  """
  keys_config = load_api_keys()
  if not keys_config.has_any_key_material:
    _log.error("UI auth requested but no API key configured (FAIL CLOSED)")
    state = getattr(getattr(request, "app", None), "state", None)
    i18n = getattr(state, "i18n", None) if state is not None else None
    raise HTTPException(
      status_code=503,
      detail=get_message(i18n, "webui.auth.no_key_configured")
      if i18n is not None
      else "API key not configured (FAIL CLOSED)",
    )
  _accept_or_reject_presented_key(
    request,
    presented_api_key(x_api_key, authorization),
    keys_config,
  )


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
      ip_address=client_ip(request),
    )
  except Exception as exc:
    # Best-effort: IRONCLAD logger must never turn a 401 into a 500 (B110).
    _log.debug("security logger unavailable for auth failure: %s", exc)


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

  # D-I / #883: same presented-key + 429 window as /ui/chat.
  return _accept_or_reject_presented_key(
    request,
    presented_api_key(x_api_key, authorization),
    keys_config,
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

  # admin_key is a bootstrap key with no expiry by design. BUT get_admin_api_key()
  # returns the primary key by default, so honoring it here when it == primary would
  # re-accept an EXPIRED primary and silently defeat its expiry (A-004). Only honor a
  # DISTINCT bootstrap key (legacy single-field); never the (possibly expired) primary
  # — a valid primary is already handled above via is_valid.
  _primary_key = keys_config.primary.key if keys_config.primary else None
  if admin_key and admin_key != _primary_key and secrets.compare_digest(x_api_key, admin_key):
    return x_api_key

  return None

__all__ = [
  'require_api_key',
  'optional_api_key',
  'authenticate_ui_request',
  'presented_api_key',
]
