"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security_logger/helpers.py
Description: Convenience methods for logging specific security events.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any, Optional, TYPE_CHECKING

from .enums import SecurityEventType, SecuritySeverity
from personality.i18n import get_i18n

if TYPE_CHECKING:
  from .logger import SecurityEventLogger

class SecurityLoggerHelpers:
  """
  Mixin with convenience methods for SecurityEventLogger.

  This class is designed to be inherited by SecurityEventLogger,
  providing high-level methods for logging specific events.

  NOTE: Methods assume the subclass has the log_event() method.
  """

  def log_auth_failure(
    self: "SecurityEventLogger",
    reason: str,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
  ) -> None:
    """Log authentication failure"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.AUTH_FAILURE,
      severity=SecuritySeverity.WARNING,
      message=i18n.t(
        "security_logger.auth.failure",
        "Authentication failed: {reason}",
        reason=reason
      ),
      ip_address=ip_address,
      endpoint=endpoint,
      details=details,
    )

  def log_path_traversal(
    self: "SecurityEventLogger",
    attempted_path: str,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
  ) -> None:
    """Log path traversal attempt"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.PATH_TRAVERSAL_ATTEMPT,
      severity=SecuritySeverity.ERROR,
      message=i18n.t(
        "security_logger.path_traversal.attempt",
        "Path traversal attempt: {attempted_path}",
        attempted_path=attempted_path
      ),
      ip_address=ip_address,
      endpoint=endpoint,
      details={"attempted_path": attempted_path},
    )

  def log_rate_limit_exceeded(
    self: "SecurityEventLogger",
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    limit: Optional[int] = None,
  ) -> None:
    """Log rate limit exceeded"""
    i18n = get_i18n()
    if ip_address:
      message = i18n.t(
        "security_logger.rate_limit.exceeded",
        "Rate limit exceeded for {source}",
        source=ip_address
      )
    else:
      message = i18n.t(
        "security_logger.rate_limit.exceeded_unknown",
        "Rate limit exceeded for unknown source"
      )

    self.log_event(
      event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
      severity=SecuritySeverity.WARNING,
      message=message,
      ip_address=ip_address,
      endpoint=endpoint,
      details={"limit": limit} if limit else None,
    )

  def log_module_rejected(
    self: "SecurityEventLogger",
    module_name: str,
    reason: str,
  ) -> None:
    """Log module rejected (not in allowlist or disabled)"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.MODULE_REJECTED,
      severity=SecuritySeverity.NOTICE,
      message=i18n.t(
        "security_logger.module.rejected",
        "Module '{module_name}' rejected: {reason}",
        module_name=module_name,
        reason=reason
      ),
      details={"module": module_name, "reason": reason},
    )

  def log_config_validation_failed(
    self: "SecurityEventLogger",
    config_key: str,
    reason: str,
    value: Optional[str] = None,
  ) -> None:
    """Log configuration validation failure"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.CONFIG_VALIDATION_FAILED,
      severity=SecuritySeverity.CRITICAL,
      message=i18n.t(
        "security_logger.config.validation_failed",
        "Configuration validation failed for '{config_key}': {reason}",
        config_key=config_key,
        reason=reason
      ),
      details={
        "config_key": config_key,
        "reason": reason,
        "value": value if value else "[redacted]",
      },
    )

  def log_xss_attempt(
    self: "SecurityEventLogger",
    input_data: str,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    parameter: Optional[str] = None,
  ) -> None:
    """Log XSS attack attempt"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.XSS_ATTEMPT,
      severity=SecuritySeverity.ERROR,
      message=i18n.t(
        "security_logger.attacks.xss_detected",
        "XSS attempt detected: {preview}",
        preview=input_data[:100]
      ),
      ip_address=ip_address,
      endpoint=endpoint,
      details={"parameter": parameter, "input_preview": input_data[:200]},
    )

  def log_sql_injection_attempt(
    self: "SecurityEventLogger",
    input_data: str,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    parameter: Optional[str] = None,
  ) -> None:
    """Log SQL injection attempt"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.SQL_INJECTION_ATTEMPT,
      severity=SecuritySeverity.ERROR,
      message=i18n.t(
        "security_logger.attacks.sql_injection_detected",
        "SQL injection attempt detected: {preview}",
        preview=input_data[:100]
      ),
      ip_address=ip_address,
      endpoint=endpoint,
      details={"parameter": parameter, "input_preview": input_data[:200]},
    )

  def log_command_injection_attempt(
    self: "SecurityEventLogger",
    input_data: str,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    parameter: Optional[str] = None,
  ) -> None:
    """Log command injection attempt"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.COMMAND_INJECTION_ATTEMPT,
      severity=SecuritySeverity.CRITICAL,
      message=i18n.t(
        "security_logger.attacks.command_injection_detected",
        "Command injection attempt detected: {preview}",
        preview=input_data[:100]
      ),
      ip_address=ip_address,
      endpoint=endpoint,
      details={"parameter": parameter, "input_preview": input_data[:200]},
    )

  def log_invalid_content_type(
    self: "SecurityEventLogger",
    content_type: str,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
  ) -> None:
    """Log invalid content type"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.INVALID_CONTENT_TYPE,
      severity=SecuritySeverity.WARNING,
      message=i18n.t(
        "security_logger.content.invalid_type",
        "Invalid Content-Type: {content_type}",
        content_type=content_type
      ),
      ip_address=ip_address,
      endpoint=endpoint,
      details={"content_type": content_type},
    )

  def log_request_too_large(
    self: "SecurityEventLogger",
    size: int,
    max_size: int,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
  ) -> None:
    """Log request exceeding size limit"""
    i18n = get_i18n()
    self.log_event(
      event_type=SecurityEventType.REQUEST_TOO_LARGE,
      severity=SecuritySeverity.WARNING,
      message=i18n.t(
        "security_logger.request.too_large",
        "Request too large: {size} bytes (max: {max_size})",
        size=size,
        max_size=max_size
      ),
      ip_address=ip_address,
      endpoint=endpoint,
      details={"size": size, "max_size": max_size},
    )

__all__ = [
  "SecurityLoggerHelpers",
]