"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/endpoints/bootstrap.py
Description: Bootstrap authentication system for session initialization

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import ipaddress
import os
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from core.messages import get_message

from core.bootstrap_tokens import create_session_token
from plugins.security.core.auth_dependencies import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bootstrap"])

def _t(request: Request, key: str, fallback: str, **kwargs) -> str:
  """Translate helper with fallback from request.app.state"""
  try:
    i18n = getattr(request.app.state, 'i18n', None)
    if not i18n:
      return fallback.format(**kwargs) if kwargs else fallback
    value = i18n.t(key, **kwargs)
    if value == key:
      return fallback.format(**kwargs) if kwargs else fallback
    return value
  except Exception:
    return fallback.format(**kwargs) if kwargs else fallback

VPN_ALLOWED_IPS = set(
  ip.strip() for ip in os.getenv('NEXE_VPN_ALLOWED_IPS', os.getenv('VPN_ALLOWED_IPS', '')).split(',') if ip.strip()
)

class BootstrapRequest(BaseModel):
  """Request to initialize session with bootstrap token"""
  token: str

class BootstrapResponse(BaseModel):
  """Response with session token after successful initialization"""
  session_token: str
  expires_in: int
  status: str
  message: str
  next_steps: list

class BootstrapInfoResponse(BaseModel):
  """Response with information about bootstrap status"""
  bootstrap_enabled: bool
  mode: str
  token_active: bool
  token_expires_in: Optional[int]
  ssl_enabled: bool

def check_rate_limit(client_ip: str, request: Request) -> None:
  """
  Validate global and per-IP rate limiting.

  Limits:
  - Global: max 10 attempts from ANY IP in 5 minutes
  - Per IP: max 3 attempts from ONE IP in 5 minutes

  Raises:
    HTTPException 429 if limit is exceeded
  """
  from core.bootstrap_tokens import check_bootstrap_rate_limit

  result = check_bootstrap_rate_limit(client_ip, window_seconds=300, global_limit=10, ip_limit=3)

  if result == "global":
    msg = _t(request, "core.server.bootstrap_system_blocked",
      "System blocked: too many global bootstrap attempts")
    logger.error(msg)
    raise HTTPException(
      status_code=429,
      detail="System temporarily blocked. Wait 5 minutes."
    )

  if result == "ip":
    logger.warning("IP %s blocked: too many attempts", client_ip)
    raise HTTPException(
      status_code=429,
      detail="Too many attempts from your IP. Wait 5 minutes."
    )

@router.post("/api/bootstrap", response_model=BootstrapResponse, summary="Initialize session with bootstrap token (development only)")
async def bootstrap_session(
  bootstrap_data: BootstrapRequest,
  request: Request
) -> BootstrapResponse:
  """
  Initialize session with bootstrap token.

  Security:
  - One-time use token generated at startup
  - IP validation (localhost + private networks + VPN whitelist)
  - Rate limiting: 3 attempts/IP + 10 global per 5 min
  - Configurable token TTL
  - Full audit logging
  """
  client_ip = request.client.host if request.client else "unknown"
  token = bootstrap_data.token.strip().upper()

  core_env = os.getenv('NEXE_ENV', 'production').lower()
  if core_env != 'development':
    logger.error("Bootstrap attempt in non-development environment (NEXE_ENV=%s)", core_env)
    raise HTTPException(
      status_code=503,
      detail="Bootstrap not available in this environment"
    )

  # Q3.1 fix: read i18n from app.state instead of passing None (Codex P1 i18n bypass)
  _i18n = getattr(request.app.state, 'i18n', None)

  try:
    if client_ip == "unknown":
      raise HTTPException(status_code=400, detail=get_message(_i18n, "core.bootstrap.invalid_ip"))
    ip_obj = ipaddress.ip_address(client_ip)
    is_local = ip_obj.is_loopback
    is_private = ip_obj.is_private
    is_whitelisted = client_ip in VPN_ALLOWED_IPS

    if not (is_local or is_private or is_whitelisted):
      logger.warning("Bootstrap attempt from non-allowed IP: %s", client_ip)
      raise HTTPException(
        status_code=403,
        detail="Access denied from this IP address"
      )
  except ValueError:
    logger.error("Invalid IP received: %s", client_ip)
    raise HTTPException(status_code=400, detail=get_message(_i18n, "core.bootstrap.invalid_ip"))

  check_rate_limit(client_ip, request)
  
  from core.bootstrap_tokens import validate_master_bootstrap

  if not validate_master_bootstrap(token):
    # Log the failure reason (expired vs invalid vs used)
    from core.bootstrap_tokens import get_bootstrap_token
    info = get_bootstrap_token()
    
    if not info:
      detail = "Server not ready - bootstrap token not initialized"
      status_code = 503
    elif info["used"]:
      detail = "Token already used. Restart server or regenerate token."
      status_code = 403
    elif datetime.now(timezone.utc).timestamp() > info["expires"]:
      detail = "Token expired. Restart server to generate new token."
      status_code = 410
    else:
      detail = "Invalid token. Check the terminal for the correct code."
      status_code = 401
      
    logger.warning("Bootstrap failed from %s: %s", client_ip, detail)
    raise HTTPException(status_code=status_code, detail=detail)

  session_ttl = 900
  session_token = create_session_token(ttl_seconds=session_ttl)

  log_data = {
    "event": "bootstrap_success",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "client_ip": client_ip,
    "user_agent": request.headers.get('user-agent', 'Unknown'),
    "session_token_created": True
  }
  logger.info("Nexe Framework initialized: %s", log_data)

  title = _t(request, "core.server.bootstrap_token_used_title", "TOKEN USED SUCCESSFULLY")
  session_from = _t(request, "core.server.bootstrap_session_from", "Session initialized from: {ip}", ip=client_ip)

  logger.info(
    f"\n+========================================================+\n"
    f"| {title:<52}|\n"
    f"|                            |\n"
    f"| {session_from:<52}|\n"
    f"| {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'):<52}|\n"
    f"|                            |\n"
    f"| Session token sent to client (15 min TTL)       |\n"
    f"| API key NOT exposed                   |\n"
    f"|                            |\n"
    f"+========================================================+"
  )

  msg = _t(request, "core.server.bootstrap_successful", "Bootstrap successful")
  return BootstrapResponse(
    session_token=session_token,
    expires_in=session_ttl,
    status="initialized",
    message=msg,
    next_steps=[
      "1. Use X-Session-Token header for initial requests",
      "2. Generate permanent API key via POST /api/keys/generate",
      "3. The session_token expires in 15 minutes"
    ]
  )

@router.post("/api/regenerate-bootstrap", summary="Regenerate expired or used bootstrap token (localhost only)")
async def regenerate_bootstrap(request: Request) -> Dict[str, str]:
  """
  Regenerate bootstrap token if the previous one has been used.

  Security: ONLY accessible from localhost (127.0.0.1, ::1)
  """
  client_ip = request.client.host if request.client else "unknown"

  from core.config import get_localhost_aliases
  if client_ip not in get_localhost_aliases():
    logger.warning("Regeneration attempt from %s", client_ip)
    raise HTTPException(
      status_code=403,
      detail="Only allowed from localhost"
    )

  from core.bootstrap_tokens import set_bootstrap_token, get_bootstrap_token
  from core.lifespan_tokens import generate_bootstrap_token

  current_info = get_bootstrap_token()
  if current_info and not current_info["used"] and datetime.now(timezone.utc).timestamp() < current_info["expires"]:
    raise HTTPException(
      status_code=400,
      detail="Current token still active and not used yet"
    )

  bootstrap_ttl = int(os.getenv('NEXE_BOOTSTRAP_TTL', os.getenv('BOOTSTRAP_TTL', '30')))
  new_token = generate_bootstrap_token()
  
  set_bootstrap_token(new_token, ttl_minutes=bootstrap_ttl)

  title = _t(request, "core.server.bootstrap_token_regenerated_title", "NEW INITIALIZATION TOKEN GENERATED")
  expiry = _t(request, "core.server.bootstrap_token_expiry", "Expires in: {minutes} minutes", minutes=bootstrap_ttl)

  logger.info(
    f"\n╔════════════════════════════════════════════════════════╗\n"
    f"║ {title:<52}║\n"
    f"║                            ║\n"
    f"║   {new_token:<48}║\n"
    f"║                            ║\n"
    f"║ {expiry:<52}║\n"
    f"║                            ║\n"
    f"╚════════════════════════════════════════════════════════╝"
  )

  log_msg = _t(request, "core.server.bootstrap_token_regenerated_log", "Token regenerated from {ip}", ip=client_ip)
  logger.info(log_msg)

  return {
    "status": "regenerated",
    "message": "New token generated. Check terminal."
  }

@router.get(
  "/api/bootstrap/info",
  response_model=BootstrapInfoResponse,
  summary="Bootstrap system status (requires API key in production)",
  dependencies=[Depends(require_api_key)],
)
async def bootstrap_info(request: Request) -> BootstrapInfoResponse:
  """
  Return information about bootstrap status.

  Bug 22 (security): previously public, now requires X-API-Key.
  In dev mode (`NEXE_DEV_MODE=true` from loopback) auth is auto-bypassed,
  so the front-end installer flow on localhost continues to work.

  Returns:
    BootstrapInfoResponse with complete bootstrap system status
  """
  from core.bootstrap_tokens import get_bootstrap_token
  from datetime import datetime

  core_env = os.getenv('NEXE_ENV', 'production').lower()
  bootstrap_enabled = (core_env == 'development')

  info = get_bootstrap_token()

  if not info:
    mode = "first_install"
    token_active = False
    token_expires_in = None
  elif info["used"]:
    mode = "production"
    token_active = False
    token_expires_in = None
  else:
    mode = "development"
    now_ts = datetime.now(timezone.utc).timestamp()
    
    if now_ts > info["expires"]:
      token_active = False
      token_expires_in = None
    else:
      token_active = True
      remaining_time = info["expires"] - now_ts
      token_expires_in = max(0, int(remaining_time))

  ssl_enabled = (request.url.scheme == "https")

  logger.debug(
    "📊 Bootstrap info request: enabled=%s, mode=%s, token_active=%s, ssl=%s",
    bootstrap_enabled, mode, token_active, ssl_enabled
  )

  return BootstrapInfoResponse(
    bootstrap_enabled=bootstrap_enabled,
    mode=mode,
    token_active=token_active,
    token_expires_in=token_expires_in,
    ssl_enabled=ssl_enabled
  )
