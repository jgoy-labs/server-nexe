"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/endpoints/system.py
Description: System administration endpoints: server restart,

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
    int: Supervisor PID

  Raises:
    HTTPException: If the file does not exist or cannot be read
  """
  if not SUPERVISOR_PID_FILE.exists():
    raise HTTPException(
      status_code=503,
      detail={
        "error": "supervisor_not_found",
        "message": _t(
          "system.supervisor_not_found",
          "Supervisor not detected. Run: python3 scripts/supervisor.py"
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
          "Invalid supervisor PID: {error}",
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
          "Supervisor PID found but process does not exist (zombie)"
        ),
        "pid_file": str(SUPERVISOR_PID_FILE),
        "suggestion": _t(
          "system.supervisor_dead_suggestion",
          "Remove PID file and restart the supervisor"
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
          "You do not have permission to access the supervisor process: {error}",
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
          "Error reading supervisor PID: {error}",
          error=str(e)
        )
      }
    )

async def send_restart_signal():
  """
  Send SIGHUP to supervisor after brief delay.

  The delay allows the HTTP response to be returned before restart,
  avoiding client connection errors.
  """
  await asyncio.sleep(0.5)

  try:
    supervisor_pid = get_supervisor_pid()
    logger.info(
      _t(
        "core.endpoints.system.sighup_sent_log",
        "Sending SIGHUP to supervisor PID {pid}",
        pid=supervisor_pid,
      )
    )

    os.kill(supervisor_pid, signal.SIGHUP)

    logger.info(_t("core.endpoints.system.restart_signal_sent", "Restart signal sent successfully"))

  except HTTPException as e:
    logger.error(_t("core.endpoints.system.restart_signal_error", "Error sending restart signal: {detail}", detail=str(e.detail)))
  except Exception as e:
    logger.error(_t("core.endpoints.system.restart_signal_unexpected", "Unexpected error sending restart signal: {error}", error=str(e)))

@router_admin.post("/restart")
async def restart_server(
  background_tasks: BackgroundTasks,
  _: str = Depends(require_api_key)
) -> Dict[str, Any]:
  """
  Restart the Nexe server via supervisor.

  🔒 Requires API key authentication (X-API-Key header).

  Flow:
  1. Endpoint returns response immediately
  2. Background task sends SIGHUP to the supervisor (0.5s delay)
  3. Supervisor performs a graceful shutdown of the worker
  4. Supervisor restarts the worker with new configuration
  5. Expected downtime: 3-6 seconds

  Returns:
    dict: Restart status and estimated time

  Raises:
    HTTPException: If the supervisor is not available
  """
  try:
    supervisor_pid = get_supervisor_pid()

    background_tasks.add_task(send_restart_signal)

    logger.info(
      _t(
        "core.endpoints.system.restart_initiated_log",
        "Restart initiated by authenticated user (supervisor PID: {pid})",
        pid=supervisor_pid,
      )
    )

    return {
      "status": "restart_initiated",
      "message": _t(
        "system.restart_initiated_message",
        "Server restarting in ~1 second"
      ),
      "supervisor_pid": supervisor_pid,
      "expected_downtime_seconds": 5,
      "instructions": _t(
        "system.restart_instructions",
        "The UI will reconnect automatically"
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
          "Error restarting server: {error}",
          error=str(e)
        )
      }
    )

@router_admin.get("/status")
async def supervisor_status(_: str = Depends(require_api_key)) -> Dict[str, Any]:
  """
  Check supervisor status.

  🔒 Requires API key authentication (X-API-Key header).

  Returns:
    dict: Information about supervisor status

  Example Response:
    {
      "supervisor_running": true,
      "supervisor_pid": 12345,
      "pid_file": "/tmp/core_supervisor.pid",
      "restart_available": true
    }
  """
  try:
    supervisor_pid = get_supervisor_pid()

    return {
      "supervisor_running": True,
      "supervisor_pid": supervisor_pid,
      "pid_file": str(SUPERVISOR_PID_FILE),
      "restart_available": True,
      "restart_command": f"kill -HUP {supervisor_pid}",
      "shutdown_command": f"kill -TERM {supervisor_pid}"
    }

  except HTTPException as e:
    return {
      "supervisor_running": False,
      "supervisor_pid": None,
      "pid_file": str(SUPERVISOR_PID_FILE),
      "restart_available": False,
      "error": e.detail
    }

@router_admin.get("/health")
async def system_health() -> Dict[str, Any]:
  """
  Simple health check (NO auth required).

  This endpoint is used by the UI to verify the server
  is available after a restart.

  Returns:
    dict: Basic system status

  Example Response:
    {
      "status": "healthy",
      "version": "0.7.1",
      "platform": "Nexe Framework"
    }
  """
  return {
    "status": "healthy",
    "version": "0.7.1",
    "platform": "Nexe Framework",
    "uptime": "available"
  }

def get_router() -> APIRouter:
  """
  Return the system admin router.

  This router should be included in server_core.py:
    from core.endpoints import system
    app.include_router(system.get_router())
  """
  return router_admin
