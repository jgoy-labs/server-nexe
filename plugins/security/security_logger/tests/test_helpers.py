"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security_logger/tests/test_helpers.py
Description: Behavioral tests for SecurityLoggerHelpers — verify JSON output,
severity mapping, IP obfuscation, and log file creation.

Replaces 24 assertion-free smoke tests with 8 tests that verify real behavior.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import pytest

from ..logger import SecurityEventLogger
from ..enums import SecurityEventType, SecuritySeverity


@pytest.fixture
def logger(tmp_path):
    """Logger with temporary directory to avoid real files."""
    return SecurityEventLogger(log_dir=tmp_path / "security")


def _read_log_events(logger):
    """Read all JSON events from the log file."""
    lines = logger.log_file.read_text().strip().splitlines()
    return [json.loads(line) for line in lines]


class TestLogFileCreation:

    def test_log_file_created_on_first_event(self, logger):
        logger.log_auth_failure(reason="test")
        assert logger.log_file.exists()

    def test_log_file_contains_valid_json(self, logger):
        logger.log_auth_failure(reason="bad key")
        events = _read_log_events(logger)
        assert len(events) == 1
        assert "timestamp" in events[0]
        assert "event_type" in events[0]
        assert "severity" in events[0]


class TestEventContent:

    def test_auth_failure_has_correct_fields(self, logger):
        logger.log_auth_failure(
            reason="Invalid key",
            ip_address="203.0.113.42",
            endpoint="/api/v1/chat",
        )
        event = _read_log_events(logger)[0]
        assert event["event_type"] == SecurityEventType.AUTH_FAILURE.value
        assert event["severity"] == SecuritySeverity.WARNING.value
        assert event["endpoint"] == "/api/v1/chat"
        # IP should be obfuscated (GDPR)
        assert event["ip_address"] == "203.0.113.xxx"

    def test_path_traversal_includes_attempted_path_in_details(self, logger):
        logger.log_path_traversal(attempted_path="../../../etc/passwd")
        event = _read_log_events(logger)[0]
        assert event["event_type"] == SecurityEventType.PATH_TRAVERSAL_ATTEMPT.value
        assert event["severity"] == SecuritySeverity.ERROR.value
        assert event["details"]["attempted_path"] == "../../../etc/passwd"

    def test_config_validation_redacts_missing_value(self, logger):
        logger.log_config_validation_failed(config_key="SECRET_KEY", reason="missing")
        event = _read_log_events(logger)[0]
        assert event["details"]["value"] == "[redacted]"
        assert event["details"]["config_key"] == "SECRET_KEY"

    def test_config_validation_shows_provided_value(self, logger):
        logger.log_config_validation_failed(
            config_key="NEXE_ENV", reason="invalid", value="unknown"
        )
        event = _read_log_events(logger)[0]
        assert event["details"]["value"] == "unknown"


class TestSeverityMapping:

    def test_attack_events_use_error_or_critical(self, logger):
        logger.log_xss_attempt(input_data="<script>alert(1)</script>")
        logger.log_sql_injection_attempt(input_data="' OR 1=1 --")
        logger.log_command_injection_attempt(input_data="; rm -rf /")
        events = _read_log_events(logger)
        severities = {e["event_type"]: e["severity"] for e in events}
        assert severities[SecurityEventType.XSS_ATTEMPT.value] == SecuritySeverity.ERROR.value
        assert severities[SecurityEventType.SQL_INJECTION_ATTEMPT.value] == SecuritySeverity.ERROR.value
        assert severities[SecurityEventType.COMMAND_INJECTION_ATTEMPT.value] == SecuritySeverity.CRITICAL.value


class TestMultipleLoggers:

    def test_two_loggers_dont_interfere(self, tmp_path):
        logger_a = SecurityEventLogger(log_dir=tmp_path / "a")
        logger_b = SecurityEventLogger(log_dir=tmp_path / "b")
        logger_a.log_auth_failure(reason="from A")
        logger_b.log_xss_attempt(input_data="from B")
        events_a = _read_log_events(logger_a)
        events_b = _read_log_events(logger_b)
        assert len(events_a) == 1
        assert len(events_b) == 1
        assert events_a[0]["event_type"] == SecurityEventType.AUTH_FAILURE.value
        assert events_b[0]["event_type"] == SecurityEventType.XSS_ATTEMPT.value
        assert "from B" in events_b[0]["details"]["input_preview"]
