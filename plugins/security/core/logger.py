"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/logger.py
Description: Logger d'esdeveniments de seguretat. Registra events en format JSONL.

www.jgoy.net
────────────────────────────────────
"""

from pathlib import Path
import json
from datetime import datetime
from typing import Dict, Any, Optional
import logging
from .messages import get_message

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
SECURITY_LOG_PATH = PROJECT_ROOT / "storage" / "system-logs" / "security"

SECURITY_LOG_PATH.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("security")

def log_security_event(
  event_type: str,
  details: Dict[str, Any],
  severity: str = "INFO"
) -> None:
  """
  Registra un event de seguretat en format JSONL

  Args:
    event_type: Tipus d'event (path_traversal_blocked, rce_blocked, auth_failed, etc.)
    details: Detalls de l'event (dict amb info rellevant)
    severity: Severitat (INFO, WARNING, ERROR, CRITICAL)

  Logs a:
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
    log_file = SECURITY_LOG_PATH / f"security_{datetime.now().strftime('%Y%m%d')}.jsonl"

    event = {
      "timestamp": datetime.now().isoformat(),
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
  Registra una vulnerabilitat detectada pels checks

  Args:
    vuln_type: Tipus de vulnerabilitat (path_traversal, rce, sql_injection, etc.)
    file_path: Fitxer on s'ha detectat
    line: Línia del codi
    severity: CRITICAL, HIGH, MEDIUM, LOW
    description: Descripció de la vulnerabilitat
    fix_suggestion: Sugerència de com arreglar-ho (opcional)

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
  Registra execució d'un scan de seguretat

  Args:
    scan_type: Tipus de scan (full, web_security, auth_check, etc.)
    findings_count: Total de findings
    critical_count: Findings crítics
    high_count: Findings alts
    duration_seconds: Durada del scan

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
  Llegeix els logs de seguretat d'una data

  Args:
    date: Data en format YYYYMMDD (default: avui)

  Returns:
    Llista d'events (dicts)

  Usage:
    logs = get_security_logs("20251005")
    for event in logs:
      print(event["type"], event["severity"])
  """
  if not date:
    date = datetime.now().strftime('%Y%m%d')

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
  Obté els últims N events de seguretat (de tots els logs)

  Args:
    limit: Nombre màxim d'events a retornar

  Returns:
    Llista d'events ordenats per timestamp descendent

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
  Neteja logs de seguretat més antics de N dies

  Args:
    days_to_keep: Dies a mantenir (default 30)

  Returns:
    Nombre de fitxers eliminats

  Usage:
    deleted = clear_old_logs(days_to_keep=90)
  """
  from datetime import timedelta

  cutoff_date = datetime.now() - timedelta(days=days_to_keep)
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