"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security_logger/logger.py
Description: SecurityEventLogger - Main class for security event logging.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from .enums import SecurityEventType, SecuritySeverity
from .sanitizers import sanitize_log_entry
from .helpers import SecurityLoggerHelpers

class SecurityEventLogger(SecurityLoggerHelpers):
  """
  Structured security event logger for Nexe 0.8

  Emits JSON-formatted security events to dedicated log file
  Compatible with SIEM/security monitoring tools

  Inherits convenience methods from SecurityLoggerHelpers mixin:
  - log_auth_failure(), log_path_traversal(), log_rate_limit_exceeded()
  - log_module_rejected(), log_config_validation_failed()
  - log_xss_attempt(), log_sql_injection_attempt(), log_command_injection_attempt()
  - log_invalid_content_type(), log_request_too_large()
  """

  def __init__(self, log_dir: Optional[Path] = None):
    """
    Initialize security event logger

    Args:
      log_dir: Directory for security logs (default: storage/system-logs/security)
    """
    if log_dir is None:
      log_dir = Path("storage/system-logs/security")

    self.log_dir = log_dir
    self.log_dir.mkdir(parents=True, exist_ok=True)

    self.log_file = self.log_dir / f"security_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"

    logger_name = f"nexe.security.events.{hash(str(log_dir))}"
    self.logger = logging.getLogger(logger_name)
    self.logger.setLevel(logging.INFO)
    self.logger.propagate = False

    self.logger.handlers.clear()

    file_handler = logging.FileHandler(self.log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(message)s'))

    self.logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(
      'SECURITY [%(levelname)s]: %(message)s'
    ))

    self.logger.addHandler(console_handler)

  def log_event(
    self,
    event_type: SecurityEventType,
    severity: SecuritySeverity,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    user: Optional[str] = None,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
  ) -> None:
    """
    Log a security event with structured data

    Args:
      event_type: Type of security event (from SecurityEventType enum)
      severity: Severity level (from SecuritySeverity enum)
      message: Human-readable message
      details: Additional structured details (dict)
      user: User identifier (if authenticated)
      ip_address: Client IP address
      endpoint: API endpoint/path
      method: HTTP method (GET, POST, etc.)
    """
    event = {
      "timestamp": datetime.now(timezone.utc).isoformat(),
      "hostname": "server-nexe",
      "appname": "Nexe",
      "version": "0.8.5",

      "event_type": event_type.value,
      "severity": severity.value,
      "message": message,

      "user": user or "anonymous",
      "ip_address": ip_address or "unknown",
      "endpoint": endpoint,
      "method": method,

      "details": details or {},
    }

    event = {k: v for k, v in event.items() if v is not None}

    event = sanitize_log_entry(event)

    json_event = json.dumps(event, ensure_ascii=False)

    level_map = {
      SecuritySeverity.EMERGENCY: logging.CRITICAL,
      SecuritySeverity.ALERT: logging.CRITICAL,
      SecuritySeverity.CRITICAL: logging.CRITICAL,
      SecuritySeverity.ERROR: logging.ERROR,
      SecuritySeverity.WARNING: logging.WARNING,
      SecuritySeverity.NOTICE: logging.INFO,
      SecuritySeverity.INFO: logging.INFO,
      SecuritySeverity.DEBUG: logging.DEBUG,
    }

    self.logger.log(level_map[severity], json_event)

__all__ = [
  "SecurityEventLogger",
]