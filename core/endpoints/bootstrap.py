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
from core.i18n_utils import translate

from core.bootstrap_tokens import create_session_token
from plugins.security.core.auth_dependencies import require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bootstrap"])

def _t(request: Request, key: str, fallback: str, **kwargs) -> str:
  """Translate helper with fallback from request.app.state"""
  # the resolution + error handling lives in core.i18n_utils.translate.
  # getattr stays inside the try via translate (defensive), but here
  # access to request.app.state can also fail, so we cover it too.
  try:
    i18n = getattr(request.app.state, 'i18n', None)
  except Exception:
    i18n = None
  return translate(i18n, key, fallback, **kwargs)

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

def _validate_bootstrap_env() -> None:
  """Raise 503 if NEXE_ENV is not 'development'."""
  # el guard try/except viu ara a resolve_core_env (sidecar_config).
  # Mantenim raw env per distingir "development" de valors no-produccio com
  # "staging"/"test" que han de bloquejar bootstrap.
  from core.sidecar_config import resolve_core_env
  core_env = resolve_core_env('production', '_validate_bootstrap_env', logger)
  if core_env != 'development':
    logger.error("Bootstrap attempt in non-development environment (NEXE_ENV=%s)", core_env)
    raise HTTPException(status_code=503, detail="Bootstrap not available in this environment")


def _validate_bootstrap_ip(client_ip: str, i18n) -> None:
  """Raise HTTPException if client IP is not allowed."""
  try:
    if client_ip == "unknown":
      raise HTTPException(status_code=400, detail=get_message(i18n, "core.bootstrap.invalid_ip"))
    ip_obj = ipaddress.ip_address(client_ip)
    if not (ip_obj.is_loopback or ip_obj.is_private or client_ip in VPN_ALLOWED_IPS):
      logger.warning("Bootstrap attempt from non-allowed IP: %s", client_ip)
      raise HTTPException(status_code=403, detail="Access denied from this IP address")
  except ValueError:
    logger.error("Invalid IP received: %s", client_ip)
    raise HTTPException(status_code=400, detail=get_message(i18n, "core.bootstrap.invalid_ip"))


def _validate_bootstrap_token(token: str, client_ip: str) -> None:
  """Validate the bootstrap token, raise HTTPException with specific reason on failure."""
  from core.bootstrap_tokens import validate_master_bootstrap
  if validate_master_bootstrap(token):
    return

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


@router.post("/api/bootstrap", response_model=BootstrapResponse, summary="Initialize session with bootstrap token (development only)", operation_id="bootstrap_session")
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
  # B-001: no .upper() — the stored token keeps its mixed-case 'Nexe-' prefix
  # (generate_bootstrap_token) and the SQL lookup is case-sensitive (BINARY),
  # so uppercasing the input would never match a valid token.
  token = bootstrap_data.token.strip()

  _validate_bootstrap_env()

  # Q3.1 fix: read i18n from app.state instead of passing None (security fix)
  _i18n = getattr(request.app.state, 'i18n', None)
  _validate_bootstrap_ip(client_ip, _i18n)
  check_rate_limit(client_ip, request)
  _validate_bootstrap_token(token, client_ip)

  session_ttl = int(os.getenv("NEXE_SESSION_TTL", "900"))
  session_token = create_session_token(ttl_seconds=session_ttl)

  log_data = {
    "event": "bootstrap_success",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "client_ip": client_ip,
    "user_agent": request.headers.get('user-agent', 'Unknown'),
    "session_token_created": True  # nosec B105: log dict key contains 'token' but value is bool True (event flag, not credential)
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
    f"| {f'Session token sent to client ({session_ttl // 60} min TTL)':<52}|\n"
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
    # B195: the previous next_steps pointed at POST /api/keys/generate (no such
    # route → 404) and told clients to use X-Session-Token, which no dependency
    # validates. Describe the real auth path instead: X-API-Key with the
    # installer-provisioned NEXE_PRIMARY_API_KEY. (Note: /installer/finalize only
    # serves the key once, during onboarding, and 404s afterwards — so we point
    # at the provisioning, not a runtime retrieval endpoint that may be closed.)
    next_steps=[
      f"1. This session_token is issued for local bootstrap and expires in {session_ttl // 60} minutes.",
      "2. Authenticate requests with the X-API-Key header using the NEXE_PRIMARY_API_KEY provisioned during installation.",
    ]
  )

@router.post("/api/regenerate-bootstrap", summary="Regenerate expired or used bootstrap token (localhost only)", response_model=dict, operation_id="regenerate_bootstrap")
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
  operation_id="bootstrap_info",
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

  # el guard try/except viu ara a resolve_core_env (sidecar_config).
  # Mantenim raw env per distingir "development" de valors no-produccio com
  # "staging"/"test".
  from core.sidecar_config import resolve_core_env
  core_env = resolve_core_env('production', 'bootstrap info endpoint', logger)
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

  logger.debug(  # nosemgrep: python-logger-credential-disclosure
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
