"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/core/logger.py
Description: Security event logger. Records events in JSONL format.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import logging
from .messages import get_message

from core.paths import get_repo_root
SECURITY_LOG_PATH = get_repo_root() / "storage" / "system-logs" / "security"

SECURITY_LOG_PATH.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("security")

def log_security_event(
  event_type: str,
  details: Dict[str, Any],
  severity: str = "INFO"
) -> None:
  """
  Log a security event in JSONL format.

  Args:
    event_type: Event type (path_traversal_blocked, rce_blocked, auth_failed, etc.)
    details: Event details (dict with relevant info)
    severity: Severity level (INFO, WARNING, ERROR, CRITICAL)

  Logs to:
    storage/system-logs/security/security_YYYYMMDD.jsonl

  Usage:
    from plugins.security.core.logger import log_security_event

    log_security_event("path_traversal_blocked", {
      "requested_path": "/etc/passwd",
      "base_path": "/var/www/assets",
      "ip_address": request.client.host
    }, severity="WARNING")
  """
  try:
    log_file = SECURITY_LOG_PATH / f"security_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

    event = {
      "timestamp": datetime.now(timezone.utc).isoformat(),
      "type": event_type,
      "severity": severity,
      "details": details,
      "module": "security"
    }

    with log_file.open("a", encoding="utf-8") as f:
      f.write(json.dumps(event, ensure_ascii=False) + "\n")

    log_level = getattr(logging, severity, logging.INFO)
    logger.log(log_level, "[%s] %s", event_type, json.dumps(details, ensure_ascii=False))

  except Exception as e:
    logger.error(get_message(None, "security.logger.failed_log_event", error=e))

def log_vulnerability_detected(
  vuln_type: str,
  file_path: str,
  line: int,
  severity: str,
  description: str,
  fix_suggestion: Optional[str] = None
) -> None:
  """
  Log a vulnerability detected by security checks.

  Args:
    vuln_type: Vulnerability type (path_traversal, rce, sql_injection, etc.)
    file_path: File where it was detected
    line: Code line number
    severity: CRITICAL, HIGH, MEDIUM, LOW
    description: Vulnerability description
    fix_suggestion: Suggested fix (optional)

  Usage:
    log_vulnerability_detected(
      vuln_type="path_traversal",
      file_path="plugins/security/manifest.py",
      line=336,
      severity="CRITICAL",
      description="Endpoint with {path:path} without validation",
      fix_suggestion="Use validate_safe_path() from security.core.validators"
    )
  """
  details = {
    "vulnerability_type": vuln_type,
    "file": file_path,
    "line": line,
    "description": description,
    "fix_suggestion": fix_suggestion
  }

  log_security_event(
    event_type="vulnerability_detected",
    details=details,
    severity=severity
  )

def log_security_scan(
  scan_type: str,
  findings_count: int,
  critical_count: int,
  high_count: int,
  duration_seconds: float
) -> None:
  """
  Log a security scan execution.

  Args:
    scan_type: Scan type (full, web_security, auth_check, etc.)
    findings_count: Total findings count
    critical_count: Critical findings count
    high_count: High-severity findings count
    duration_seconds: Scan duration in seconds

  Usage:
    import time
    start = time.time()
    results = await security_specialist.run_checks()
    log_security_scan(
      scan_type="full",
      findings_count=len(results),
      critical_count=...,
      high_count=...,
      duration_seconds=time.time() - start
    )
  """
  details = {
    "scan_type": scan_type,
    "total_findings": findings_count,
    "critical": critical_count,
    "high": high_count,
    "duration_seconds": round(duration_seconds, 2),
    "findings_per_second": round(findings_count / duration_seconds, 2) if duration_seconds > 0 else 0
  }

  severity = "CRITICAL" if critical_count > 0 else "WARNING" if high_count > 0 else "INFO"

  log_security_event(
    event_type="security_scan_completed",
    details=details,
    severity=severity
  )

def get_security_logs(date: Optional[str] = None) -> list:
  """
  Read security logs for a given date.

  Args:
    date: Date in YYYYMMDD format (default: today)

  Returns:
    List of events (dicts)

  Usage:
    logs = get_security_logs("20251005")
    for event in logs:
      print(event["type"], event["severity"])
  """
  if not date:
    date = datetime.now(timezone.utc).strftime('%Y%m%d')

  log_file = SECURITY_LOG_PATH / f"security_{date}.jsonl"

  if not log_file.exists():
    return []

  events = []
  try:
    with log_file.open("r", encoding="utf-8") as f:
      for line in f:
        if line.strip():
          events.append(json.loads(line))
  except Exception as e:
    logger.error(get_message(None, "security.logger.failed_read_logs", error=e))

  return events

def get_latest_security_events(limit: int = 100) -> list:
  """
  Get the latest N security events (across all log files).

  Args:
    limit: Maximum number of events to return

  Returns:
    List of events sorted by timestamp descending

  Usage:
    recent_events = get_latest_security_events(limit=50)
  """
  all_events = []

  log_files = sorted(SECURITY_LOG_PATH.glob("security_*.jsonl"), reverse=True)

  for log_file in log_files:
    try:
      with log_file.open("r", encoding="utf-8") as f:
        for line in f:
          if line.strip():
            all_events.append(json.loads(line))

            if len(all_events) >= limit:
              break
    except Exception as e:
      logger.error(get_message(None, "security.logger.failed_read_file", file=log_file, error=e))

    if len(all_events) >= limit:
      break

  all_events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

  return all_events[:limit]

def clear_old_logs(days_to_keep: int = 30) -> int:
  """
  Clean up security logs older than N days.

  Args:
    days_to_keep: Days to keep (default 30)

  Returns:
    Number of deleted files

  Usage:
    deleted = clear_old_logs(days_to_keep=90)
  """
  from datetime import timedelta

  cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
  deleted_count = 0

  for log_file in SECURITY_LOG_PATH.glob("security_*.jsonl"):
    try:
      date_str = log_file.stem.replace("security_", "")
      file_date = datetime.strptime(date_str, "%Y%m%d")

      if file_date < cutoff_date:
        log_file.unlink()
        deleted_count += 1
        logger.info(get_message(None, "security.logger.deleted_old_log", filename=log_file.name))

    except Exception as e:
      logger.error(get_message(None, "security.logger.failed_process_file", file=log_file, error=e))

  return deleted_count