"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/health.py
Description: Health checks for the RAG module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from pathlib import Path  # noqa: F401  # patched by tests via patch("memory.rag.health.Path")
from typing import Dict, Any, List
import psutil
import structlog

from personality.i18n import get_i18n
from memory.shared.health_helpers import (
  check_module_initialized as _shared_check_module_initialized,
  aggregate_health_checks,
  check_paths_writable
)

logger = structlog.get_logger()

def check_module_initialized(module: Any) -> Dict[str, Any]:
  """Check 1: Verify that the module is initialized."""
  return _shared_check_module_initialized(module, "rag")

def check_qdrant_available() -> Dict[str, Any]:
  """Check 2: ask Qdrant whether it is actually there.

  This used to open a `try:` with a bare `pass`, read the installed
  qdrant-client VERSION and return "pass" — the `except ImportError` below it
  was unreachable, so the check answered "available" even with the package
  missing and, more to the point, never asked the store anything. Everything
  downstream inherited the lie: the readiness aggregate, /status, and the
  watcher's Qdrant eye.

  What is read is the watcher's last observation of the SHARED pooled client
  — the one that serves the chat, not a second one opened for the occasion.
  """
  i18n = get_i18n()
  from core.qdrant_pool import qdrant_status  # deferred: memory/ must not import core/ at import time

  # Reads the watcher's last observation; it must not probe here, because
  # get_health() runs on the event loop and readiness is polled every 3s.
  ok, detail = qdrant_status()
  if ok:
    return {
      "name": "qdrant_available",
      "status": "pass",
      "message": i18n.t("rag.health.qdrant_available", "Qdrant responding ({detail})", detail=detail)
    }
  return {
    "name": "qdrant_available",
    "status": "fail",
    "message": i18n.t("rag.health.qdrant_unreachable", "Qdrant not responding ({detail})", detail=detail)
  }


def check_storage_paths() -> Dict[str, Any]:
  """Check 3: Verify storage paths exist (storage/vectors/)."""
  i18n = get_i18n()
  try:
    from core.paths import get_repo_root
    vector_dir = get_repo_root() / "storage" / "vectors"
    catalog_dir = get_repo_root() / "storage" / "vectors" / "catalog"

    return check_paths_writable(
      check_name="storage_paths",
      paths=[vector_dir],
      i18n_prefix="rag.health",
      writable_key="storage_paths_writable",
      writable_text="Storage paths writable: {path}",
      not_writable_key="storage_paths_not_writable",
      not_writable_text="Storage paths not writable: {path}",
      mkdir_paths=[vector_dir, catalog_dir]
    )

  except Exception as e:
    return {
      "name": "storage_paths",
      "status": "fail",
      "message": i18n.t("rag.health.storage_paths_error", "Error checking storage paths: {error}", error=str(e))
    }

def check_rag_sources(module) -> Dict[str, Any]:
  """Check: the module can name the sources the chat retrieves from.

  ADR-008 E2: this used to walk `module._sources` (one PersonalityRAG) and
  call each one's `health()`. The real sources (`core/rag/`) have no
  `health()` — whether their store answers is `check_qdrant_available`'s
  question, asked once, not per source — so what is left to check is that the
  list is there.

  The three system collections are ALWAYS in `list_sources()`, whatever the
  registry holds. That is load-bearing: the registry is empty on a default
  install, and a check fed only `registered_names()` would report `fail`,
  turn the aggregate `unhealthy` and hold readiness down
  (`core/endpoints/root.py`) on a server whose chat retrieves just fine.
  """
  i18n = get_i18n()
  try:
    if not module._initialized:
      return {
        "name": "rag_sources",
        "status": "warn",
        "message": i18n.t("rag.health.module_not_initialized_no_sources", "Module not initialized - no sources loaded")
      }

    sources = module.list_sources()
    if not sources:
      return {
        "name": "rag_sources",
        "status": "fail",
        "message": i18n.t("rag.health.no_sources_registered", "No RAG sources registered")
      }

    return {
      "name": "rag_sources",
      "status": "pass",
      "message": i18n.t("rag.health.sources_available", "{count} sources available", count=len(sources)),
      "sources": sources
    }

  except Exception as e:
    return {
      "name": "rag_sources",
      "status": "fail",
      "message": i18n.t("rag.health.sources_check_error", "Error checking sources: {error}", error=str(e))
    }

def check_disk_space(min_gb: float | None = None) -> Dict[str, Any]:
  """Check 6: Verify available disk space.

  Low disk DEGRADES the RAG; it never blocks startup. The critical branch
  reports "warn" (not "fail"), so the aggregate stays "degraded" and the app
  still boots (readiness treats only "unhealthy" as not-ready). The threshold
  is configurable via NEXE_RAG_MIN_DISK_GB (default 5 GB) so a desktop/VM with
  a small disk does not warn too eagerly.
  """
  if min_gb is None:
    try:
      min_gb = float(os.environ.get("NEXE_RAG_MIN_DISK_GB", "5.0"))
    except (TypeError, ValueError):
      min_gb = 5.0
    if min_gb <= 0:
      # A non-positive threshold would make the check always "pass" and silently
      # disable the disk signal — fall back to the documented default.
      min_gb = 5.0
  i18n = get_i18n()
  try:
    disk = psutil.disk_usage(".")
    free_gb = disk.free / (1024**3)

    if free_gb >= min_gb:
      status = "pass"
      message = i18n.t(
        "rag.health.disk_space_ok",
        "{free}GB available (>={required}GB required)",
        free=f"{free_gb:.1f}",
        required=min_gb
      )
    elif free_gb >= min_gb / 2:
      status = "warn"
      message = i18n.t(
        "rag.health.disk_space_warn",
        "{free}GB available (<{required}GB required, may run out)",
        free=f"{free_gb:.1f}",
        required=min_gb
      )
    else:
      # Low disk DEGRADES the RAG; it does NOT block startup. Readiness treats
      # "unhealthy" as not-ready (the web UI holds the "Iniciando…" overlay for
      # ~6 min), but a critical disk still lets the RAG serve reads — so report
      # "warn" (→ aggregate "degraded", app boots) while keeping the critical text.
      status = "warn"
      message = i18n.t(
        "rag.health.disk_space_critical",
        "{free}GB available (critical: <{critical}GB)",
        free=f"{free_gb:.1f}",
        critical=min_gb/2
      )

    return {
      "name": "disk_space",
      "status": status,
      "message": message,
      "free_gb": round(free_gb, 2)
    }

  except Exception as e:
    return {
      "name": "disk_space",
      "status": "fail",
      "message": i18n.t("rag.health.disk_space_error", "Error checking disk space: {error}", error=str(e))
    }

def check_health(module) -> Dict[str, Any]:
  """
  Runs all health checks and returns aggregated status.

  Args:
    module: RAGModule instance

  Returns:
    Dict with status, checks, metadata

  Status logic:
    - healthy: All pass
    - degraded: Some warn, no fail
    - unhealthy: Any fail
  """
  checks: List[Dict[str, Any]] = []

  try:
    checks.append(check_module_initialized(module))
    checks.append(check_rag_sources(module))
    checks.append(check_qdrant_available())
    checks.append(check_storage_paths())
    checks.append(check_disk_space())

    metadata = {
      "module_id": module.module_id,
      "name": module.name,
      "version": module.version,
      "initialized": module._initialized,
      "sources": module.list_sources() if module._initialized else [],
      "stats": module._stats if module._initialized else {}
    }

    return aggregate_health_checks(checks, "rag", metadata)

  except Exception as e:
    logger.error(
      "rag_health_check_failed",
      error=str(e),
      exc_info=True
    )

    return {
      "status": "unhealthy",
      "checks": checks,
      "metadata": {
        "error": str(e)
      }
    }

__all__ = [
  "check_health",
  "check_module_initialized",
  "check_rag_sources",
  "check_qdrant_available",
  "check_storage_paths",
  "check_disk_space"
]