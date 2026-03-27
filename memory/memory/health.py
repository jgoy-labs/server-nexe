"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/health.py
Description: Health checks for Memory module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any, List
from pathlib import Path
import psutil
import structlog

from personality.i18n import get_i18n
from memory.shared.health_helpers import (
  check_module_initialized as _shared_check_module_initialized,
  aggregate_health_checks
)

logger = structlog.get_logger()

def check_module_initialized(module: Any) -> Dict[str, Any]:
  """Check 1: Verify that the module is initialized."""
  return _shared_check_module_initialized(module, "memory")

def check_flash_storage_paths() -> Dict[str, Any]:
  """Check 2: Verify flash storage paths exist."""
  i18n = get_i18n()
  try:
    from core.paths import get_repo_root
    _root = get_repo_root()
    flash_dir = _root / "storage" / "memory" / "flash"
    storage_dir = _root / "storage" / "memory" / "storage"
    cache_dir = _root / "storage" / "memory" / "cache"

    flash_dir.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    paths_checked = []
    all_writable = True

    for path in [flash_dir, storage_dir, cache_dir]:
      test_file = path / ".write_test"
      try:
        test_file.write_text("test")
        test_file.unlink()
        paths_checked.append(str(path.resolve()))
      except Exception:
        all_writable = False
        break

    if all_writable:
      return {
        "name": "storage_paths",
        "status": "pass",
        "message": i18n.t("memory.health.storage_paths_ok", "All storage paths writable: {count}/3", count=len(paths_checked)),
        "details": {
          "paths": paths_checked,
          "total": 3,
          "writable": len(paths_checked)
        }
      }
    else:
      return {
        "name": "storage_paths",
        "status": "fail",
        "message": i18n.t("memory.health.storage_paths_fail", "Some storage paths not writable"),
        "details": {
          "paths": paths_checked,
          "total": 3,
          "writable": len(paths_checked)
        }
      }

  except Exception as e:
    return {
      "name": "storage_paths",
      "status": "fail",
      "message": i18n.t("memory.health.flash_storage_error", "Error checking flash storage paths: {error}", error=str(e))
    }

def check_ram_available(min_gb: float = 1.0) -> Dict[str, Any]:
  """Check 3: Verify available RAM (>1GB)."""
  i18n = get_i18n()
  try:
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024**3)
    total_gb = mem.total / (1024**3)
    used_gb = mem.used / (1024**3)
    percentage = mem.percent

    if available_gb >= min_gb:
      status = "pass"
      message = i18n.t(
        "memory.health.ram_ok",
        "{available}GB available (>={required}GB required)",
        available=f"{available_gb:.1f}",
        required=f"{min_gb:.1f}"
      )
    elif available_gb >= min_gb / 2:
      status = "warn"
      message = i18n.t(
        "memory.health.ram_warn",
        "{available}GB available (<{required}GB required, may be slow)",
        available=f"{available_gb:.1f}",
        required=f"{min_gb:.1f}"
      )
    else:
      status = "fail"
      message = i18n.t(
        "memory.health.ram_critical",
        "{available}GB available (critical: <{critical}GB)",
        available=f"{available_gb:.1f}",
        critical=f"{min_gb/2:.1f}"
      )

    return {
      "name": "ram_available",
      "status": status,
      "message": message,
      "details": {
        "available_gb": round(available_gb, 2),
        "used_gb": round(used_gb, 2),
        "total_gb": round(total_gb, 2),
        "percentage": round(percentage, 1)
      }
    }

  except Exception as e:
    return {
      "name": "ram_available",
      "status": "fail",
      "message": i18n.t("memory.health.ram_error", "Error checking RAM: {error}", error=str(e))
    }

def check_cleanup_policies() -> Dict[str, Any]:
  """Check 4: Verify cleanup policies configured."""
  i18n = get_i18n()
  try:
    return {
      "name": "cleanup_policies",
      "status": "pass",
      "message": i18n.t("memory.health.cleanup_ok", "Cleanup policies ready")
    }

  except Exception as e:
    return {
      "name": "cleanup_policies",
      "status": "fail",
      "message": i18n.t("memory.health.cleanup_error", "Error checking cleanup policies: {error}", error=str(e))
    }

def check_flash_memory_size(module) -> Dict[str, Any]:
  """Check 5: Verify FlashMemory cache size."""
  i18n = get_i18n()
  try:
    if not module._initialized or not module._flash_memory:
      return {
        "name": "flash_memory",
        "status": "warn",
        "message": i18n.t("memory.health.flash_not_init", "FlashMemory not initialized"),
        "details": {
          "items": 0
        }
      }

    cache_size = len(module._flash_memory._store)

    if cache_size > 1000:
      status = "warn"
      message = i18n.t(
        "memory.health.flash_high_cache",
        "FlashMemory cache high: {size} entries (>1000)",
        size=cache_size
      )
    else:
      status = "pass"
      message = i18n.t(
        "memory.health.flash_ok",
        "FlashMemory: {size} items",
        size=cache_size
      )

    return {
      "name": "flash_memory",
      "status": status,
      "message": message,
      "details": {
        "items": cache_size
      }
    }

  except Exception as e:
    return {
      "name": "flash_memory",
      "status": "fail",
      "message": i18n.t("memory.health.flash_error", "Error checking FlashMemory: {error}", error=str(e))
    }

def check_persistence_connectivity(module) -> Dict[str, Any]:
  """Check 6: Verify Persistence connectivity (SQLite + Qdrant)."""
  i18n = get_i18n()
  try:
    if not module._initialized or not module._persistence:
      return {
        "name": "persistence_connectivity",
        "status": "warn",
        "message": i18n.t("memory.health.persistence_not_init", "Persistence not initialized")
      }

    db_exists = module._persistence.db_path.exists()

    qdrant_exists = module._persistence.qdrant_path.exists()

    if db_exists and qdrant_exists:
      status = "pass"
      message = i18n.t(
        "memory.health.persistence_ok",
        "Persistence healthy: SQLite + Qdrant"
      )
    elif db_exists or qdrant_exists:
      status = "warn"
      message = i18n.t(
        "memory.health.persistence_partial",
        "Persistence partially available (SQLite: {db}, Qdrant: {qdrant})",
        db=db_exists,
        qdrant=qdrant_exists
      )
    else:
      status = "fail"
      message = i18n.t(
        "memory.health.persistence_down",
        "Persistence unavailable"
      )

    return {
      "name": "persistence_connectivity",
      "status": status,
      "message": message,
      "sqlite_ready": db_exists,
      "qdrant_ready": qdrant_exists
    }

  except Exception as e:
    return {
      "name": "persistence_connectivity",
      "status": "fail",
      "message": i18n.t("memory.health.persistence_error", "Error checking Persistence: {error}", error=str(e))
    }

def check_pipeline_stats(module) -> Dict[str, Any]:
  """Check 7: Verify Pipeline statistics."""
  i18n = get_i18n()
  try:
    if not module._initialized or not module._pipeline:
      return {
        "name": "pipeline_stats",
        "status": "warn",
        "message": i18n.t("memory.health.pipeline_not_init", "Pipeline not initialized"),
        "stats": {}
      }

    stats = module._pipeline.get_stats()

    total = stats.get("total_ingested", 0)
    failures = stats.get("failures", 0)

    failure_rate = (failures / total * 100) if total > 0 else 0

    if failure_rate > 10:
      status = "warn"
      message = i18n.t(
        "memory.health.pipeline_high_failures",
        "Pipeline failure rate high: {rate}% ({failures}/{total})",
        rate=f"{failure_rate:.1f}",
        failures=failures,
        total=total
      )
    else:
      status = "pass"
      message = i18n.t(
        "memory.health.pipeline_ok",
        "Pipeline healthy: {total} ingested, {failures} failures ({rate}%)",
        total=total,
        failures=failures,
        rate=f"{failure_rate:.1f}"
      )

    return {
      "name": "pipeline_stats",
      "status": status,
      "message": message,
      "stats": stats
    }

  except Exception as e:
    return {
      "name": "pipeline_stats",
      "status": "fail",
      "message": i18n.t("memory.health.pipeline_error", "Error checking Pipeline: {error}", error=str(e))
    }

def check_health(module) -> Dict[str, Any]:
  """
  Executes all health checks and returns aggregated status.

  Args:
    module: MemoryModule instance

  Returns:
    Dict amb status, checks, metadata
  """
  checks: List[Dict[str, Any]] = []

  try:
    checks.append(check_module_initialized(module))
    checks.append(check_flash_storage_paths())
    checks.append(check_ram_available(min_gb=1.0))
    checks.append(check_cleanup_policies())

    checks.append(check_flash_memory_size(module))
    checks.append(check_persistence_connectivity(module))
    checks.append(check_pipeline_stats(module))

    metadata = {
      "module_id": module.module_id,
      "name": module.name,
      "version": module.version,
      "initialized": module._initialized
    }

    return aggregate_health_checks(checks, "memory", metadata)

  except Exception as e:
    logger.error(
      "memory_health_check_failed",
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
  "check_flash_storage_paths",
  "check_ram_available",
  "check_cleanup_policies",
  "check_flash_memory_size",
  "check_persistence_connectivity",
  "check_pipeline_stats"
]