"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/sidecar_stubs.py
Description: F2.5 — Stub endpoints sidecar-aware per a /sessions, /info, /backends.
             En sidecar mode (`web_ui_module` desactivat) retornen 200 amb body
             declaratiu `sidecar_mode=true, available=false` perquè la webview
             Tauri no rebi 404. En mode no-sidecar retornen 501 (el
             `web_ui_module` hauria de servir-los; si no és present, és
             configuració incorrecta).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from core.version import __version__

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sidecar-stubs"])


def _is_sidecar() -> bool:
  """Return True if sidecar mode actiu. Defensive — fallback False."""
  try:
    from core.sidecar_config import get_sidecar_config
    return bool(get_sidecar_config().is_sidecar)
  except Exception as exc:  # pragma: no cover — defensive light-touch
    logger.debug("sidecar_stubs: get_sidecar_config() failed (%s); assuming non-sidecar", exc)
    return False


def _stub_response(name: str, message: str, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
  """Build a uniform stub response body."""
  body: Dict[str, Any] = {
    "sidecar_mode": True,
    "available": False,
    "items": [],
    "message": message,
  }
  if extra:
    body.update(extra)
  return body


def _not_available_501(name: str) -> HTTPException:
  """Build a uniform 501 for non-sidecar mode (web_ui_module hauria de servir)."""
  return HTTPException(
    status_code=501,
    detail={
      "error": "endpoint_not_implemented",
      "message": (
        f"Endpoint /{name} is provided by web_ui_module when enabled. "
        f"Either enable web_ui_module or run in sidecar mode."
      ),
    },
  )


@router.get("/sessions", summary="Sessions stub (sidecar-aware)", operation_id="sessions_stub")
async def sessions_stub() -> Dict[str, Any]:
  """Stub per a `/sessions`. Sidecar → 200 amb body declaratiu, altrament 501."""
  if not _is_sidecar():
    raise _not_available_501("sessions")
  return _stub_response(
    "sessions",
    "Sessions endpoint disabled in sidecar mode (web_ui_module disabled)",
  )


@router.get("/info", summary="Info stub (sidecar-aware)", operation_id="info_stub")
async def info_stub() -> Dict[str, Any]:
  """Stub per a `/info`. Sidecar → 200 amb version+build, altrament 501."""
  if not _is_sidecar():
    raise _not_available_501("info")
  # `version` derivat de core.version (single source of truth via pyproject.toml).
  body = _stub_response(
    "info",
    "Info endpoint disabled in sidecar mode",
    extra={"version": __version__, "build": "sidecar"},
  )
  # `items` no aplica semànticament a /info — el deixem per uniformitat però
  # els callers haurien de mirar `version`/`build`.
  return body


@router.get("/backends", summary="Backends stub (sidecar-aware)", operation_id="backends_stub")
async def backends_stub() -> Dict[str, Any]:
  """Stub per a `/backends`. Sidecar → 200 amb body declaratiu, altrament 501."""
  if not _is_sidecar():
    raise _not_available_501("backends")
  return _stub_response(
    "backends",
    "Backends endpoint disabled in sidecar mode",
  )


def get_router() -> APIRouter:
  """Return the sidecar-stubs router for inclusion at factory level."""
  return router
