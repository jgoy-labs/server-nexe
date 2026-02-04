"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security_logger/tests/test_logger.py
Description: Nexe Server Component

www.jgoy.net
────────────────────────────────────
"""

import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from plugins.security_logger.logger import SecurityEventLogger
from plugins.security_logger.enums import SecurityEventType, SecuritySeverity

@pytest.fixture
def temp_log_dir():
  """Create a temporary directory for test logs."""
  with TemporaryDirectory() as tmpdir:
    yield Path(tmpdir)

@pytest.fixture
def logger(temp_log_dir):
  """Create a SecurityEventLogger with temporary log directory."""
  return SecurityEventLogger(log_dir=temp_log_dir)

class TestLoggerInit:
  """Tests for SecurityEventLogger initialization."""

  def test_creates_log_directory(self, temp_log_dir):
    """Logger should create log directory if it doesn't exist."""
    log_dir = temp_log_dir / "new_subdir"
    assert not log_dir.exists()

    logger = SecurityEventLogger(log_dir=log_dir)
    assert log_dir.exists()

  def test_creates_log_file(self, logger, temp_log_dir):
    """Logger should create a dated log file."""
    log_files = list(temp_log_dir.glob("security_*.log"))
    assert len(log_files) == 1

class TestLogEvent:
  """Tests for the log_event method."""

  def test_log_event_writes_json(self, logger, temp_log_dir):
    """log_event should write valid JSON to file."""
    logger.log_event(
      event_type=SecurityEventType.AUTH_FAILURE,
      severity=SecuritySeverity.WARNING,
      message="Test auth failure",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    content = log_file.read_text()

    event = json.loads(content.strip())
    assert event["event_type"] == "auth.failure"
    assert event["severity"] == "warning"
    assert event["message"] == "Test auth failure"

  def test_log_event_includes_timestamp(self, logger, temp_log_dir):
    """log_event should include ISO timestamp."""
    logger.log_event(
      event_type=SecurityEventType.AUTH_SUCCESS,
      severity=SecuritySeverity.INFO,
      message="Test",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert "timestamp" in event
    assert "T" in event["timestamp"]

  def test_log_event_with_details(self, logger, temp_log_dir):
    """log_event should include details dict."""
    logger.log_event(
      event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
      severity=SecuritySeverity.WARNING,
      message="Rate limit hit",
      details={"limit": 100, "current": 150},
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert event["details"]["limit"] == 100
    assert event["details"]["current"] == 150

  def test_log_event_with_context(self, logger, temp_log_dir):
    """log_event should include IP, endpoint, method."""
    logger.log_event(
      event_type=SecurityEventType.ACCESS_DENIED,
      severity=SecuritySeverity.ERROR,
      message="Access denied",
      ip_address="192.168.1.50",
      endpoint="/api/admin",
      method="DELETE",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert event["ip_address"] == "192.168.1.xxx"
    assert event["endpoint"] == "/api/admin"
    assert event["method"] == "DELETE"

  def test_log_event_sanitizes_api_keys(self, logger, temp_log_dir):
    """log_event should redact API keys in message."""
    api_key = "a" * 64
    logger.log_event(
      event_type=SecurityEventType.AUTH_FAILURE,
      severity=SecuritySeverity.WARNING,
      message=f"Invalid key: {api_key}",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert "[REDACTED_API_KEY]" in event["message"]
    assert api_key not in event["message"]

class TestLoggerHelpers:
  """Tests for convenience logging methods."""

  def test_log_auth_failure(self, logger, temp_log_dir):
    """log_auth_failure should log with correct event type."""
    logger.log_auth_failure(
      reason="Invalid token",
      ip_address="10.0.0.1",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert event["event_type"] == "auth.failure"
    assert event["severity"] == "warning"
    assert "auth" in event["message"].lower() or "Invalid token" in event["message"]

  def test_log_path_traversal(self, logger, temp_log_dir):
    """log_path_traversal should log with ERROR severity."""
    logger.log_path_traversal(
      attempted_path="../../../etc/passwd",
      ip_address="192.168.1.100",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert event["event_type"] == "access.path_traversal"
    assert event["severity"] == "error"

  def test_log_rate_limit_exceeded(self, logger, temp_log_dir):
    """log_rate_limit_exceeded should log with limit info."""
    logger.log_rate_limit_exceeded(
      ip_address="8.8.8.8",
      limit=100,
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert event["event_type"] == "rate_limit.exceeded"
    assert event["details"]["limit"] == 100

  def test_log_xss_attempt(self, logger, temp_log_dir):
    """log_xss_attempt should log with ERROR severity."""
    logger.log_xss_attempt(
      input_data="<script>alert('xss')</script>",
      ip_address="1.2.3.4",
      parameter="name",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert event["event_type"] == "validation.xss_attempt"
    assert event["severity"] == "error"
    assert event["details"]["parameter"] == "name"

  def test_log_command_injection_attempt(self, logger, temp_log_dir):
    """log_command_injection_attempt should log with CRITICAL severity."""
    logger.log_command_injection_attempt(
      input_data="; rm -rf /",
      ip_address="5.6.7.8",
    )

    log_file = list(temp_log_dir.glob("security_*.log"))[0]
    event = json.loads(log_file.read_text().strip())

    assert event["event_type"] == "validation.command_injection"
    assert event["severity"] == "critical"