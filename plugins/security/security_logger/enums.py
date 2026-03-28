"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security_logger/enums.py
Description: Enums per security event logging: tipus d'events i nivells de severitat.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from enum import Enum

class SecurityEventType(str, Enum):
  """Security event types for classification"""

  AUTH_SUCCESS = "auth.success"
  AUTH_FAILURE = "auth.failure"
  AUTH_INVALID_KEY = "auth.invalid_key"
  AUTH_MISSING_KEY = "auth.missing_key"
  AUTH_EXPIRED_KEY = "auth.expired_key"

  ACCESS_DENIED = "access.denied"
  PATH_TRAVERSAL_ATTEMPT = "access.path_traversal"

  RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"
  RATE_LIMIT_WARNING = "rate_limit.warning"

  CONFIG_VALIDATION_FAILED = "config.validation_failed"
  OLLAMA_HOST_INVALID = "config.ollama_invalid"
  MODULE_LOAD_FAILED = "module.load_failed"
  MODULE_REJECTED = "module.rejected"

  SUSPICIOUS_REQUEST = "suspicious.request"
  MALFORMED_INPUT = "suspicious.malformed_input"

  STARTUP_SUCCESS = "system.startup_success"
  STARTUP_FAILURE = "system.startup_failure"
  SHUTDOWN = "system.shutdown"

  XSS_ATTEMPT = "validation.xss_attempt"
  SQL_INJECTION_ATTEMPT = "validation.sql_injection"
  COMMAND_INJECTION_ATTEMPT = "validation.command_injection"
  LDAP_INJECTION_ATTEMPT = "validation.ldap_injection"
  INVALID_CONTENT_TYPE = "validation.invalid_content_type"
  INVALID_CHARSET = "validation.invalid_charset"
  REQUEST_TOO_LARGE = "validation.request_too_large"

class SecuritySeverity(str, Enum):
  """Security event severity levels (RFC5424-inspired)"""
  EMERGENCY = "emergency"
  ALERT = "alert"
  CRITICAL = "critical"
  ERROR = "error"
  WARNING = "warning"
  NOTICE = "notice"
  INFO = "info"
  DEBUG = "debug"

__all__ = [
  "SecurityEventType",
  "SecuritySeverity",
]