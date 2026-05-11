"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security_logger/tests/test_enums.py
Description: Nexe Server Component

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from plugins.security.security_logger.enums import SecurityEventType, SecuritySeverity

class TestSecurityEventType:
  """Tests for SecurityEventType enum."""

  def test_auth_events_exist(self):
    """Authentication events should be defined."""
    assert SecurityEventType.AUTH_SUCCESS.value == "auth.success"
    assert SecurityEventType.AUTH_FAILURE.value == "auth.failure"
    assert SecurityEventType.AUTH_INVALID_KEY.value == "auth.invalid_key"
    assert SecurityEventType.AUTH_MISSING_KEY.value == "auth.missing_key"
    assert SecurityEventType.AUTH_EXPIRED_KEY.value == "auth.expired_key"

  def test_access_events_exist(self):
    """Access control events should be defined."""
    assert SecurityEventType.ACCESS_DENIED.value == "access.denied"
    assert SecurityEventType.PATH_TRAVERSAL_ATTEMPT.value == "access.path_traversal"

  def test_rate_limit_events_exist(self):
    """Rate limiting events should be defined."""
    assert SecurityEventType.RATE_LIMIT_EXCEEDED.value == "rate_limit.exceeded"
    assert SecurityEventType.RATE_LIMIT_WARNING.value == "rate_limit.warning"

  def test_validation_events_exist(self):
    """Input validation events should be defined."""
    assert SecurityEventType.XSS_ATTEMPT.value == "validation.xss_attempt"
    assert SecurityEventType.SQL_INJECTION_ATTEMPT.value == "validation.sql_injection"
    assert SecurityEventType.COMMAND_INJECTION_ATTEMPT.value == "validation.command_injection"

  def test_system_events_exist(self):
    """System events should be defined."""
    assert SecurityEventType.STARTUP_SUCCESS.value == "system.startup_success"
    assert SecurityEventType.STARTUP_FAILURE.value == "system.startup_failure"
    assert SecurityEventType.SHUTDOWN.value == "system.shutdown"

  def test_enum_is_string(self):
    """SecurityEventType should be a string enum."""
    assert isinstance(SecurityEventType.AUTH_SUCCESS, str)
    assert SecurityEventType.AUTH_SUCCESS == "auth.success"

class TestSecuritySeverity:
  """Tests for SecuritySeverity enum (RFC5424-inspired)."""

  def test_all_severity_levels_exist(self):
    """All RFC5424 severity levels should be defined."""
    assert SecuritySeverity.EMERGENCY.value == "emergency"
    assert SecuritySeverity.ALERT.value == "alert"
    assert SecuritySeverity.CRITICAL.value == "critical"
    assert SecuritySeverity.ERROR.value == "error"
    assert SecuritySeverity.WARNING.value == "warning"
    assert SecuritySeverity.NOTICE.value == "notice"
    assert SecuritySeverity.INFO.value == "info"
    assert SecuritySeverity.DEBUG.value == "debug"

  def test_severity_count(self):
    """There should be exactly 8 severity levels."""
    assert len(SecuritySeverity) == 8

  def test_enum_is_string(self):
    """SecuritySeverity should be a string enum."""
    assert isinstance(SecuritySeverity.ERROR, str)
    assert SecuritySeverity.ERROR == "error"