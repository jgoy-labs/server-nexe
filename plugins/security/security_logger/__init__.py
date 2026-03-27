"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/security_logger/__init__.py
Description: Public facade for security_logger - unifies access to security logging.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional

from .enums import (
  SecurityEventType,
  SecuritySeverity,
)

from .sanitizers import (
  obfuscate_ip,
  redact_api_key,
  truncate_prompt,
  anonymize_path,
  sanitize_log_entry,
)

from .logger import SecurityEventLogger

from .helpers import SecurityLoggerHelpers

_security_logger: Optional[SecurityEventLogger] = None

def get_security_logger() -> SecurityEventLogger:
  """
  Get global security logger instance (singleton pattern).

  Returns:
    SecurityEventLogger instance (sempre la mateixa)

  Examples:
    >>> logger = get_security_logger()
    >>> logger.log_auth_failure("Invalid API key", ip_address="192.168.1.1")
  """
  global _security_logger
  if _security_logger is None:
    _security_logger = SecurityEventLogger()
  return _security_logger

__all__ = [
  "SecurityEventType",
  "SecuritySeverity",

  "obfuscate_ip",
  "redact_api_key",
  "truncate_prompt",
  "anonymize_path",
  "sanitize_log_entry",

  "SecurityEventLogger",

  "SecurityLoggerHelpers",

  "get_security_logger",
]

__version__ = "2.0.0"
__author__ = "Jordi Goy"
__description__ = "Security event logger RFC5424-compliant - IRONCLAD v2.0.0"