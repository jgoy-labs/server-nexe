"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/health.py
Description: Health checks for Embeddings module.

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
  """
  Check 1: Verify that the module is initialized.

  Args:
    module: EmbeddingsModule instance

  Returns:
    Dict: {"name": str, "status": "pass"|"fail", "message": str}
  """
  return _shared_check_module_initialized(module, "embeddings")

def check_dependencies_available() -> Dict[str, Any]:
  """
  Check 2: Verify available dependencies (sentence-transformers).

  Returns:
    Dict: {"name": str, "status": "pass"|"warn"|"fail", "message": str}
  """
  try:
    import sentence_transformers
    version = sentence_transformers.__version__
    return {
      "name": "dependencies_available",
      "status": "pass",
      "message": get_i18n().t(
        "embeddings.health.dependencies_ok",
        "sentence-transformers {version} available",
        version=version
      )
    }
  except ImportError:
    return {
      "name": "dependencies_available",
      "status": "fail",
      "message": get_i18n().t(
        "embeddings.health.dependencies_missing",
        "sentence-transformers not installed (pip install sentence-transformers)"
      )
    }
  except Exception as e:
    return {
      "name": "dependencies_available",
      "status": "fail",
      "message": get_i18n().t(
        "embeddings.health.dependencies_error",
        "Error checking dependencies: {error}",
        error=str(e)
      )
    }

def check_device_available() -> Dict[str, Any]:
  """
  Check 3: Detect available device (MPS/CUDA/CPU).

  Mac: Search for MPS (Apple Silicon) or CPU
  Others: CUDA or CPU

  Returns:
    Dict: {"name": str, "status": "pass"|"warn", "message": str, "device": str}
  """
  try:
    import torch

    if torch.backends.mps.is_available():
      device = "mps"
      status = "pass"
      message = get_i18n().t("embeddings.health.device_mps", "MPS (Apple Silicon) available")
    elif torch.cuda.is_available():
      device = f"cuda:{torch.cuda.current_device()}"
      status = "pass"
      device_name = torch.cuda.get_device_name(0)
      message = get_i18n().t(
        "embeddings.health.device_cuda",
        "CUDA available ({device})",
        device=device_name
      )
    else:
      device = "cpu"
      status = "warn"
      message = get_i18n().t("embeddings.health.device_cpu_only", "Only CPU available (slower performance)")

    return {
      "name": "device_available",
      "status": status,
      "message": message,
      "device": device
    }

  except ImportError:
    return {
      "name": "device_available",
      "status": "fail",
      "message": get_i18n().t("embeddings.health.device_torch_missing", "torch not installed (pip install torch)")
    }
  except Exception as e:
    return {
      "name": "device_available",
      "status": "fail",
      "message": get_i18n().t(
        "embeddings.health.device_error",
        "Error checking device: {error}",
        error=str(e)
      )
    }

def check_cache_directories() -> Dict[str, Any]:
  """
  Check 4: Verify that cache directories exist and are writable.

  Directories:
  - storage/vectors/embeddings/cache/l2/

  Returns:
    Dict: {"name": str, "status": "pass"|"fail", "message": str}
  """
  try:
    from core.paths import get_repo_root
    cache_dir = get_repo_root() / "storage" / "vectors" / "embeddings" / "cache" / "l2"

    cache_dir.mkdir(parents=True, exist_ok=True)

    test_file = cache_dir / ".write_test"
    try:
      test_file.write_text("test")
      test_file.unlink()
      writable = True
    except Exception:
      writable = False

    if writable:
      return {
        "name": "cache_directories",
        "status": "pass",
        "message": get_i18n().t(
          "embeddings.health.cache_writable",
          "Cache directory writable: {path}",
          path=str(cache_dir)
        )
      }
    else:
      return {
        "name": "cache_directories",
        "status": "fail",
        "message": get_i18n().t(
          "embeddings.health.cache_not_writable",
          "Cache directory not writable: {path}",
          path=str(cache_dir)
        )
      }

  except Exception as e:
    return {
      "name": "cache_directories",
      "status": "fail",
      "message": get_i18n().t(
        "embeddings.health.cache_error",
        "Error checking cache directories: {error}",
        error=str(e)
      )
    }

def check_memory_available(min_gb: float = 2.0) -> Dict[str, Any]:
  """
  Check 5: Verify available RAM.

  Args:
    min_gb: Minimum GB required (default 2.0)

  Returns:
    Dict: {"name": str, "status": "pass"|"warn"|"fail", "message": str, "available_gb": float}
  """
  try:
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024**3)

    if available_gb >= min_gb:
      status = "pass"
      message = get_i18n().t(
        "embeddings.health.memory_ok",
        "{available}GB available (>={required}GB required)",
        available=f"{available_gb:.1f}",
        required=f"{min_gb:.1f}"
      )
    elif available_gb >= min_gb / 2:
      status = "warn"
      message = get_i18n().t(
        "embeddings.health.memory_warn",
        "{available}GB available (<{required}GB required, may be slow)",
        available=f"{available_gb:.1f}",
        required=f"{min_gb:.1f}"
      )
    else:
      status = "fail"
      message = get_i18n().t(
        "embeddings.health.memory_critical",
        "{available}GB available (critical: <{critical}GB)",
        available=f"{available_gb:.1f}",
        critical=f"{min_gb/2:.1f}"
      )

    return {
      "name": "memory_available",
      "status": status,
      "message": message,
      "available_gb": round(available_gb, 2)
    }

  except Exception as e:
    return {
      "name": "memory_available",
      "status": "fail",
      "message": get_i18n().t(
        "embeddings.health.memory_error",
        "Error checking memory: {error}",
        error=str(e)
      )
    }

def check_health(module) -> Dict[str, Any]:
  """
  Executes all health checks and returns aggregated status.

  Args:
    module: EmbeddingsModule instance

  Returns:
    Dict with:
      - status: "healthy" | "degraded" | "unhealthy"
      - checks: List of all checks
      - metadata: Module info

  Status logic:
    - healthy: All pass
    - degraded: Some warn, no fail
    - unhealthy: Any fail
  """
  checks: List[Dict[str, Any]] = []

  try:
    checks.append(check_module_initialized(module))
    checks.append(check_dependencies_available())
    checks.append(check_device_available())
    checks.append(check_cache_directories())
    checks.append(check_memory_available(min_gb=2.0))

    metadata = {
      "module_id": module.module_id,
      "name": module.name,
      "version": module.version,
      "initialized": module._initialized
    }

    return aggregate_health_checks(checks, "embeddings", metadata)

  except Exception as e:
    logger.error(
      "embeddings_health_check_failed",
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
  "check_dependencies_available",
  "check_device_available",
  "check_cache_directories",
  "check_memory_available"
]