"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/health.py
Description: Health checks for the RAG module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

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
  """Check 2: Verify Qdrant is available."""
  i18n = get_i18n()
  try:
    pass
    try:
      import importlib.metadata
      version = importlib.metadata.version("qdrant-client")
    except Exception:
      version = "unknown"

    return {
      "name": "qdrant_available",
      "status": "pass",
      "message": i18n.t("rag.health.qdrant_available", "qdrant-client {version} available", version=version)
    }
  except ImportError:
    return {
      "name": "qdrant_available",
      "status": "fail",
      "message": i18n.t("rag.health.qdrant_not_installed", "qdrant-client not installed (pip install qdrant-client)")
    }
  except Exception as e:
    return {
      "name": "qdrant_available",
      "status": "fail",
      "message": i18n.t("rag.health.qdrant_check_error", "Error checking qdrant-client: {error}", error=str(e))
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
  """Check: Verify health of each RAG source."""
  i18n = get_i18n()
  try:
    if not module._initialized:
      return {
        "name": "rag_sources",
        "status": "warn",
        "message": i18n.t("rag.health.module_not_initialized_no_sources", "Module not initialized - no sources loaded")
      }

    if not module._sources:
      return {
        "name": "rag_sources",
        "status": "fail",
        "message": i18n.t("rag.health.no_sources_registered", "No RAG sources registered")
      }

    sources_health = {}
    all_healthy = True

    for name, source in module._sources.items():
      try:
        source_health = source.health()
        sources_health[name] = source_health

        if source_health.get("status") in ["unhealthy", "degraded"]:
          all_healthy = False

      except Exception as e:
        sources_health[name] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    if all_healthy:
      return {
        "name": "rag_sources",
        "status": "pass",
        "message": i18n.t("rag.health.sources_healthy", "{count} sources healthy", count=len(module._sources)),
        "sources": sources_health
      }
    else:
      return {
        "name": "rag_sources",
        "status": "fail",
        "message": i18n.t("rag.health.sources_unhealthy", "Some sources unhealthy ({count} total)", count=len(module._sources)),
        "sources": sources_health
      }

  except Exception as e:
    return {
      "name": "rag_sources",
      "status": "fail",
      "message": i18n.t("rag.health.sources_check_error", "Error checking sources: {error}", error=str(e))
    }

def check_disk_space(min_gb: float = 10.0) -> Dict[str, Any]:
  """Check 6: Verify available disk space (>10GB)."""
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
      status = "fail"
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
    checks.append(check_disk_space(min_gb=10.0))

    metadata = {
      "module_id": module.module_id,
      "name": module.name,
      "version": module.version,
      "initialized": module._initialized,
      "sources": list(module._sources.keys()) if module._initialized else [],
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