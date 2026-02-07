"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/endpoints/bootstrap.py
Description: Sistema d'autenticació bootstrap per inicialització de sessions

www.jgoy.net
────────────────────────────────────
"""

import logging
import ipaddress
import os
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.bootstrap_tokens import create_session_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bootstrap"])

def _t(request: Request, key: str, fallback: str, **kwargs) -> str:
  """Helper per traduir amb fallback des de request.app.state"""
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
  ip.strip() for ip in os.getenv('VPN_ALLOWED_IPS', '').split(',') if ip.strip()
)

class BootstrapRequest(BaseModel):
  """Request per inicialitzar sessió amb token bootstrap"""
  token: str

class BootstrapResponse(BaseModel):
  """Response amb session token despres d'inicialitzacio exitosa"""
  session_token: str
  expires_in: int
  status: str
  message: str
  next_steps: list

class BootstrapInfoResponse(BaseModel):
  """Response amb informació sobre l'estat del bootstrap"""
  bootstrap_enabled: bool
  mode: str
  token_active: bool
  token_expires_in: Optional[int]
  ssl_enabled: bool

def check_rate_limit(client_ip: str, request: Request) -> None:
  """
  Valida rate limiting global i per IP.

  Límits:
  - Global: màxim 10 intents de QUALSEVOL IP en 5 minuts
  - Per IP: màxim 3 intents d'UNA IP en 5 minuts

  Raises:
    HTTPException 429 si s'excedeix el límit
  """
  from core.bootstrap_tokens import check_bootstrap_rate_limit

  result = check_bootstrap_rate_limit(client_ip, window_seconds=300, global_limit=10, ip_limit=3)

  if result == "global":
    msg = _t(
      request,
      "core.server.bootstrap_system_blocked",
      "🚨 System blocked: too many global bootstrap attempts"
    )
    logger.error(msg)
    raise HTTPException(
      status_code=429,
      detail=_t(
        request,
        "core.server.bootstrap_rate_limit_global_detail",
        "System temporarily blocked. Wait 5 minutes."
      )
    )

  if result == "ip":
    logger.warning(_t(
      request,
      "core.server.bootstrap_rate_limit_ip_log",
      "IP {ip} blocked: too many attempts",
      ip=client_ip
    ))
    raise HTTPException(
      status_code=429,
      detail=_t(
        request,
        "core.server.bootstrap_rate_limit_ip_detail",
        "Too many attempts from your IP. Wait 5 minutes."
      )
    )

@router.post("/api/bootstrap", response_model=BootstrapResponse)
async def bootstrap_session(
  bootstrap_data: BootstrapRequest,
  request: Request
) -> BootstrapResponse:
  """
  Inicialitza sessió amb token bootstrap.

  Security:
  - Token d'un sol ús generat al startup
  - Validació d'IP (localhost + xarxes privades + whitelist VPN)
  - Rate limiting: 3 intents/IP + 10 globals per 5 min
  - TTL configurable del token
  - Auditoria completa amb logs estructurats
  """
  client_ip = request.client.host if request.client else "unknown"
  token = bootstrap_data.token.strip().upper()

  core_env = os.getenv('NEXE_ENV', 'production').lower()
  if core_env != 'development':
    logger.error(_t(
      request,
      "core.server.bootstrap_not_available_log",
      "Bootstrap attempt in non-development environment (NEXE_ENV={env})",
      env=core_env
    ))
    raise HTTPException(
      status_code=503,
      detail=_t(
        request,
        "core.server.bootstrap_not_available_env",
        "Bootstrap not available in this environment"
      )
    )

  try:
    if client_ip == "unknown":
      raise HTTPException(
        status_code=400,
        detail=_t(request, "core.server.bootstrap_invalid_ip", "Invalid IP address")
      )
    ip_obj = ipaddress.ip_address(client_ip)
    is_local = ip_obj.is_loopback
    is_private = ip_obj.is_private
    is_whitelisted = client_ip in VPN_ALLOWED_IPS

    if not (is_local or is_private or is_whitelisted):
      logger.warning(_t(
        request,
        "core.server.bootstrap_non_allowed_ip",
        "Bootstrap attempt from non-allowed IP: {ip}",
        ip=client_ip
      ))
      raise HTTPException(
        status_code=403,
        detail=_t(
          request,
          "core.server.bootstrap_access_denied_ip",
          "Access denied from this IP address"
        )
      )
  except ValueError:
    logger.error(_t(
      request,
      "core.server.bootstrap_invalid_ip_log",
      "Invalid IP received: {ip}",
      ip=client_ip
    ))
    raise HTTPException(
      status_code=400,
      detail=_t(request, "core.server.bootstrap_invalid_ip", "Invalid IP address")
    )

  check_rate_limit(client_ip, request)
  
  from core.bootstrap_tokens import validate_master_bootstrap

  # ✅ FIX: Validació persistent contra la DB (suport multi-worker)
  if not validate_master_bootstrap(token):
    # Intentem loguejar la raó de la fallada (expirat vs invàlid vs usat)
    from core.bootstrap_tokens import get_bootstrap_token
    info = get_bootstrap_token()
    
    if not info:
      detail = _t(
        request,
        "core.server.bootstrap_token_not_initialized",
        "Server not ready - bootstrap token not initialized"
      )
      status_code = 503
    elif info["used"]:
      detail = _t(
        request,
        "core.server.bootstrap_token_used",
        "Token already used. Restart server or regenerate token."
      )
      status_code = 403
    elif datetime.now(timezone.utc).timestamp() > info["expires"]:
      detail = _t(
        request,
        "core.server.bootstrap_token_expired",
        "Token expired. Restart server to generate new token."
      )
      status_code = 410
    else:
      detail = _t(
        request,
        "core.server.bootstrap_token_invalid",
        "Invalid token. Check the terminal for the correct code."
      )
      status_code = 401
      
    logger.warning(_t(
      request,
      "core.server.bootstrap_failed_log",
      "Bootstrap failed from {ip}: {detail}",
      ip=client_ip,
      detail=detail
    ))
    raise HTTPException(status_code=status_code, detail=detail)

  session_ttl = 900
  session_token = create_session_token(ttl_seconds=session_ttl)

  log_data = {
    "event": "bootstrap_success",
    "timestamp": datetime.now().isoformat(),
    "client_ip": client_ip,
    "user_agent": request.headers.get('user-agent', 'Unknown'),
    "session_token_created": True
  }
  logger.info(_t(
    request,
    "core.server.bootstrap_initialized_log",
    "Nexe Framework initialized: {data}",
    data=log_data
  ))

  title = _t(request, "core.server.bootstrap_token_used_title", "TOKEN USED SUCCESSFULLY")
  session_from = _t(request, "core.server.bootstrap_session_from", "Session initialized from: {ip}", ip=client_ip)

  session_token_msg = _t(
    request,
    "core.server.bootstrap_session_token_sent",
    "Session token sent to client (15 min TTL)"
  )
  api_key_msg = _t(
    request,
    "core.server.bootstrap_api_key_not_exposed",
    "API key NOT exposed"
  )

  print(f"""
+========================================================+
| {title:<52}|
|                            |
| {session_from:<52}|
| {datetime.now().strftime("%Y-%m-%d %H:%M:%S"):<52}|
|                            |
| {session_token_msg:<52}|
| {api_key_msg:<52}|
|                            |
+========================================================+
  """)

  msg = _t(request, "core.server.bootstrap_successful", "Bootstrap successful")
  return BootstrapResponse(
    session_token=session_token,
    expires_in=session_ttl,
    status="initialized",
    message=msg,
    next_steps=[
      _t(request, "core.server.bootstrap_next_step_1", "1. Use X-Session-Token header for initial requests"),
      _t(request, "core.server.bootstrap_next_step_2", "2. Generate permanent API key via POST /api/keys/generate"),
      _t(request, "core.server.bootstrap_next_step_3", "3. The session_token expires in 15 minutes")
    ]
  )

@router.post("/api/regenerate-bootstrap")
async def regenerate_bootstrap(request: Request) -> Dict[str, str]:
  """
  Regenera token bootstrap si l'anterior ja s'ha utilitzat.

  Security: NOMÉS accessible des de localhost (127.0.0.1, ::1)
  """
  client_ip = request.client.host

  if client_ip not in ["127.0.0.1", "::1", "localhost"]:
    logger.warning(_t(
      request,
      "core.server.bootstrap_regen_attempt",
      "Regeneration attempt from {ip}",
      ip=client_ip
    ))
    raise HTTPException(
      status_code=403,
      detail=_t(
        request,
        "core.server.bootstrap_only_localhost",
        "Only allowed from localhost"
      )
    )

  from core.bootstrap_tokens import set_bootstrap_token, get_bootstrap_token
  from core.lifespan import generate_bootstrap_token

  current_info = get_bootstrap_token()
  if current_info and not current_info["used"] and datetime.now().timestamp() < current_info["expires"]:
    raise HTTPException(
      status_code=400,
      detail=_t(
        request,
        "core.server.bootstrap_token_still_active",
        "Current token still active and not used yet"
      )
    )

  bootstrap_ttl = int(os.getenv('BOOTSTRAP_TTL', '30'))
  new_token = generate_bootstrap_token()
  
  # ✅ FIX: Persistir nou token a DB
  set_bootstrap_token(new_token, ttl_minutes=bootstrap_ttl)

  title = _t(
    request,
    "core.server.bootstrap_token_regenerated_title",
    "🔄 NEW BOOTSTRAP TOKEN GENERATED"
  )
  expiry = _t(
    request,
    "core.server.bootstrap_token_expiry",
    "⏰ Expires in: {minutes} minutes",
    minutes=bootstrap_ttl
  )

  print(f"""
╔════════════════════════════════════════════════════════╗
║ {title:<52}║
║                            ║
║   {new_token:<48}║
║                            ║
║ {expiry:<52}║
║                            ║
╚════════════════════════════════════════════════════════╝
  """)

  log_msg = _t(
    request,
    "core.server.bootstrap_token_regenerated_log",
    "🔄 Token regenerated from {ip}",
    ip=client_ip
  )
  logger.info(log_msg)

  return {
    "status": "regenerated",
    "message": _t(
      request,
      "core.server.bootstrap_regenerated_message",
      "New token generated. Check terminal."
    )
  }

@router.get("/api/bootstrap/info", response_model=BootstrapInfoResponse)
async def bootstrap_info(request: Request) -> BootstrapInfoResponse:
  """
  Retorna informació sobre l'estat del bootstrap.

  Aquest endpoint és públic (no requereix autenticació) i permet
  al frontend prendre decisions intel·ligents sobre com mostrar la UI.

  Returns:
    BootstrapInfoResponse amb estat complet del sistema bootstrap
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
    _t(
      request,
      "core.server.bootstrap_info_log",
      "📊 Bootstrap info request: enabled={enabled}, mode={mode}, token_active={active}, ssl={ssl}",
      enabled=bootstrap_enabled,
      mode=mode,
      active=token_active,
      ssl=ssl_enabled
    )
  )

  return BootstrapInfoResponse(
    bootstrap_enabled=bootstrap_enabled,
    mode=mode,
    token_active=token_active,
    token_expires_in=token_expires_in,
    ssl_enabled=ssl_enabled
  )
