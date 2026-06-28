"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/shared/health_helpers.py
Description: Shared health check utilities for memory modules.
             Extracted from F-100/F-101 consolidation audit.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import structlog

from personality.i18n import get_i18n

logger = structlog.get_logger()


def check_module_initialized(module, module_name: str) -> Dict[str, Any]:
  """
  Generic check: Verify that a module is initialized.

  Args:
    module: Module instance (must have _initialized attribute)
    module_name: i18n key prefix (e.g. "rag", "memory", "embeddings")

  Returns:
    Dict: {"name": str, "status": "pass"|"fail", "message": str}
  """
  i18n = get_i18n()
  try:
    is_init = module._initialized
    message = (
      i18n.t(f"{module_name}.health.initialized_ok", "Module initialized correctly")
      if is_init
      else i18n.t(f"{module_name}.health.not_initialized", "Module not initialized")
    )
    return {
      "name": "module_initialized",
      "status": "pass" if is_init else "fail",
      "message": message
    }
  except Exception as e:
    return {
      "name": "module_initialized",
      "status": "fail",
      "message": i18n.t(
        f"{module_name}.health.init_check_error",
        "Error checking initialization: {error}",
        error=str(e)
      )
    }


def aggregate_health_checks(
  checks_results: List[Dict[str, Any]],
  module_name: str,
  metadata: Dict[str, Any]
) -> Dict[str, Any]:
  """
  Generic health check aggregation.

  Takes a list of individual check results, determines overall status,
  logs the result, and returns the aggregated response.

  Args:
    checks_results: List of check dicts, each with "name", "status", "message"
    module_name: Used for log event name (e.g. "rag", "memory", "embeddings")
    metadata: Module metadata dict to include in the result

  Returns:
    Dict with:
      - status: "healthy" | "degraded" | "unhealthy"
      - checks: The original checks list
      - metadata: Module metadata

  Status logic:
    - healthy: All pass
    - degraded: Some warn, no fail
    - unhealthy: Any fail
  """
  has_fail = any(c["status"] == "fail" for c in checks_results)
  has_warn = any(c["status"] == "warn" for c in checks_results)

  if has_fail:
    overall_status = "unhealthy"
  elif has_warn:
    overall_status = "degraded"
  else:
    overall_status = "healthy"

  result = {
    "status": overall_status,
    "checks": checks_results,
    "metadata": metadata
  }

  logger.info(
    f"{module_name}_health_check_complete",
    status=overall_status,
    checks_total=len(checks_results),
    checks_pass=sum(1 for c in checks_results if c["status"] == "pass"),
    checks_warn=sum(1 for c in checks_results if c["status"] == "warn"),
    checks_fail=sum(1 for c in checks_results if c["status"] == "fail")
  )

  return result


def check_paths_writable(
  check_name: str,
  paths: List[Path],
  i18n_prefix: str,
  *,
  writable_key: str,
  writable_text: str,
  not_writable_key: str,
  not_writable_text: str,
  mkdir_paths: Optional[List[Path]] = None,
  with_details: bool = False
) -> Dict[str, Any]:
  """
  Shared mkdir + write-test + unlink routine for path-writability health checks.

  Creates the required directories, then probes each path in ``paths`` by writing
  and removing a ``.write_test`` file (stopping at the first failure). Builds the
  pass/fail result. Callers keep their own try/except so the module-specific
  "error" branch (and its i18n key) is preserved unchanged.

  Args:
    check_name: Value for the result "name" field.
    paths: Directories to probe for writability.
    i18n_prefix: i18n key namespace (e.g. "rag.health").
    writable_key / writable_text: i18n key suffix + fallback for the pass case.
    not_writable_key / not_writable_text: i18n key suffix + fallback for the fail case.
    mkdir_paths: Directories to create (defaults to ``paths``).
    with_details: When True, include a "details" block (memory module shape) and
      render the pass message with ``count``; otherwise render it with ``path``.

  Returns:
    Dict: {"name", "status", "message"[, "details"]}
  """
  i18n = get_i18n()
  dirs_to_make = mkdir_paths if mkdir_paths is not None else paths

  for directory in dirs_to_make:
    directory.mkdir(parents=True, exist_ok=True)

  paths_checked: List[str] = []
  all_writable = True

  for path in paths:
    test_file = path / ".write_test"
    try:
      test_file.write_text("test")
      test_file.unlink()
      paths_checked.append(str(path.resolve()))
    except Exception:
      all_writable = False
      break

  if all_writable:
    if with_details:
      message = i18n.t(f"{i18n_prefix}.{writable_key}", writable_text, count=len(paths_checked))
    else:
      message = i18n.t(f"{i18n_prefix}.{writable_key}", writable_text, path=str(paths[0]))
    result = {
      "name": check_name,
      "status": "pass",
      "message": message
    }
  else:
    if with_details:
      message = i18n.t(f"{i18n_prefix}.{not_writable_key}", not_writable_text)
    else:
      message = i18n.t(f"{i18n_prefix}.{not_writable_key}", not_writable_text, path=str(paths[0]))
    result = {
      "name": check_name,
      "status": "fail",
      "message": message
    }

  if with_details:
    result["details"] = {
      "paths": paths_checked,
      "total": len(paths),
      "writable": len(paths_checked)
    }

  return result


__all__ = [
  "check_module_initialized",
  "aggregate_health_checks",
  "check_paths_writable"
]
