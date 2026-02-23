"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/endpoints/system.py
Description: Endpoints d'administració del sistema: reinici del servidor,

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pathlib import Path
import os
import signal
import asyncio
import logging
from typing import Dict, Any

from plugins.security.core.auth import require_api_key

router_admin = APIRouter(prefix="/admin/system", tags=["system-admin"])
logger = logging.getLogger(__name__)

def _get_i18n():
  """Helper to get i18n instance from server state."""
  try:
    from core.lifespan import get_server_state
    return get_server_state().i18n
  except Exception:
    return None

def _t(key: str, fallback: str, **kwargs) -> str:
  """Helper to translate with fallback."""
  i18n = _get_i18n()
  if not i18n:
    return fallback.format(**kwargs) if kwargs else fallback
  try:
    value = i18n.t(key, **kwargs)
    if value == key:
      return fallback.format(**kwargs) if kwargs else fallback
    return value
  except Exception:
    return fallback.format(**kwargs) if kwargs else fallback

SUPERVISOR_PID_FILE = Path.home() / 'Nexe-Logs' / 'core_supervisor.pid'

def get_supervisor_pid() -> int:
  """
  Read supervisor PID from file.

  Returns:
    int: PID del supervisor

  Raises:
    HTTPException: Si el fitxer no existeix o no es pot llegir
  """
  if not SUPERVISOR_PID_FILE.exists():
    raise HTTPException(
      status_code=503,
      detail={
        "error": "supervisor_not_found",
        "message": _t(
          "system.supervisor_not_found",
          "Supervisor no detectat. Executa: python3 scripts/supervisor.py"
        ),
        "pid_file": str(SUPERVISOR_PID_FILE)
      }
    )

  try:
    pid = int(SUPERVISOR_PID_FILE.read_text().strip())

    os.kill(pid, 0)

    return pid

  except ValueError as e:
    raise HTTPException(
      status_code=503,
      detail={
        "error": "invalid_pid",
        "message": _t(
          "system.supervisor_pid_invalid",
          "Supervisor PID invàlid: {error}",
          error=str(e)
        ),
        "pid_file": str(SUPERVISOR_PID_FILE)
      }
    )
  except ProcessLookupError:
    raise HTTPException(
      status_code=503,
      detail={
        "error": "supervisor_dead",
        "message": _t(
          "system.supervisor_dead",
          "Supervisor PID trobat però procés no existeix (zombie)"
        ),
        "pid_file": str(SUPERVISOR_PID_FILE),
        "suggestion": _t(
          "system.supervisor_dead_suggestion",
          "Elimina el fitxer PID i reinicia el supervisor"
        )
      }
    )
  except PermissionError as e:
    raise HTTPException(
      status_code=500,
      detail={
        "error": "permission_denied",
        "message": _t(
          "system.supervisor_permission_denied",
          "No tens permisos per accedir al procés supervisor: {error}",
          error=str(e)
        )
      }
    )
  except Exception as e:
    raise HTTPException(
      status_code=500,
      detail={
        "error": "unknown_error",
        "message": _t(
          "system.supervisor_read_error",
          "Error llegint supervisor PID: {error}",
          error=str(e)
        )
      }
    )

async def send_restart_signal():
  """
  Send SIGHUP to supervisor after brief delay.

  El delay permet que la resposta HTTP es retorni abans del reinici,
  evitant errors de connexió al client.
  """
  await asyncio.sleep(0.5)

  try:
    supervisor_pid = get_supervisor_pid()
    logger.info(f"Sending SIGHUP to supervisor PID {supervisor_pid}")

    os.kill(supervisor_pid, signal.SIGHUP)

    logger.info(_t("core.endpoints.system.restart_signal_sent", "Restart signal sent successfully"))

  except HTTPException as e:
    logger.error(_t("core.endpoints.system.restart_signal_error", "Error sending restart signal: {detail}", detail=str(e.detail)))
  except Exception as e:
    logger.error(_t("core.endpoints.system.restart_signal_unexpected", "Unexpected error sending restart signal: {error}", error=str(e)))

@router_admin.post("/restart", summary="Reinicia el servidor via supervisor (🔒 API key)")
async def restart_server(
  background_tasks: BackgroundTasks,
  _: str = Depends(require_api_key)
) -> Dict[str, Any]:
  """
  Reinicia el servidor Nexe via supervisor.

  🔒 Requereix autenticació amb API key (X-API-Key header).

  Funcionament:
  1. Endpoint retorna resposta immediatament
  2. Background task envia SIGHUP al supervisor (0.5s delay)
  3. Supervisor fa graceful shutdown del worker
  4. Supervisor reinicia worker amb configuració nova
  5. Downtime esperat: 3-6 segons

  Returns:
    dict: Estat del reinici i temps estimat

  Raises:
    HTTPException: Si el supervisor no està disponible
  """
  try:
    supervisor_pid = get_supervisor_pid()

    background_tasks.add_task(send_restart_signal)

    logger.info(f"Restart initiated by authenticated user (supervisor PID: {supervisor_pid})")

    return {
      "status": "restart_initiated",
      "message": _t(
        "system.restart_initiated_message",
        "Servidor reiniciant en ~1 segon"
      ),
      "expected_downtime_seconds": 5,
      "instructions": _t(
        "system.restart_instructions",
        "La UI es reconnectarà automàticament"
      )
    }

  except HTTPException:
    raise
  except Exception as e:
    logger.error(_t("core.endpoints.system.restart_initiation_error", "Error initiating restart: {error}", error=str(e)))
    raise HTTPException(
      status_code=500,
      detail={
        "error": "restart_failed",
        "message": _t(
          "system.restart_failed",
          "Error reiniciant servidor: {error}",
          error=str(e)
        )
      }
    )

@router_admin.get("/status", summary="Estat del supervisor i disponibilitat de restart (🔒 API key)")
async def supervisor_status(_: str = Depends(require_api_key)) -> Dict[str, Any]:
  """
  Check supervisor status.

  🔒 Requereix autenticació amb API key (X-API-Key header).

  Returns:
    dict: Informació sobre l'estat del supervisor

  Example Response:
    {
      "supervisor_running": true,
      "restart_available": true
    }
  """
  try:
    supervisor_pid = get_supervisor_pid()

    return {
      "supervisor_running": True,
      "restart_available": True
    }

  except HTTPException as e:
    return {
      "supervisor_running": False,
      "restart_available": False,
      "error": e.detail
    }

@router_admin.get("/health", summary="Health check admin (públic, usat per la UI post-restart)")
async def system_health() -> Dict[str, Any]:
  """
  Health check simple (NO requereix auth).

  Aquest endpoint es fa servir per la UI per comprovar si el servidor
  està disponible després d'un reinici.

  Returns:
    dict: Estat bàsic del sistema

  Example Response:
    {
      "status": "healthy",
      "version": "0.8.0",
      "platform": "Nexe Framework"
    }
  """
  try:
    from core.lifespan import get_server_state
    version = get_server_state().config.get('meta', {}).get('version', '0.8.0')
  except Exception:
    version = '0.8.0'
  return {
    "status": "healthy",
    "version": version,
    "platform": "Nexe Framework",
    "uptime": "available"
  }

def get_router() -> APIRouter:
  """
  Retorna el router admin del sistema.

  Aquest router s'ha d'incloure a server_core.py:
    from core.endpoints import system
    app.include_router(system.get_router())
  """
  return router_admin