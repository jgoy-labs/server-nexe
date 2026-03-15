"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security_logger/tests/test_helpers.py
Description: Tests per SecurityLoggerHelpers (tots els mètodes de log).

www.jgoy.net
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from ..logger import SecurityEventLogger
from ..enums import SecurityEventType, SecuritySeverity


@pytest.fixture
def logger(tmp_path):
    """Logger amb directori temporal per evitar fitxers reals."""
    return SecurityEventLogger(log_dir=tmp_path / "security")


class TestLogAuthFailure:

    def test_logs_auth_failure(self, logger):
        logger.log_auth_failure(reason="Invalid key")
        # No ha de llançar excepció

    def test_logs_auth_failure_with_ip(self, logger):
        logger.log_auth_failure(
            reason="Token expired",
            ip_address="192.168.1.100",
            endpoint="/api/v1/chat"
        )

    def test_logs_auth_failure_with_details(self, logger):
        logger.log_auth_failure(
            reason="Missing header",
            details={"expected_header": "X-API-Key"}
        )


class TestLogPathTraversal:

    def test_logs_path_traversal(self, logger):
        logger.log_path_traversal(attempted_path="../../../etc/passwd")

    def test_logs_with_ip_and_endpoint(self, logger):
        logger.log_path_traversal(
            attempted_path="../../secret.txt",
            ip_address="10.0.0.1",
            endpoint="/ui/static"
        )


class TestLogRateLimitExceeded:

    def test_logs_with_ip(self, logger):
        logger.log_rate_limit_exceeded(
            ip_address="203.0.113.1",
            endpoint="/api/v1/chat",
            limit=100
        )

    def test_logs_without_ip(self, logger):
        logger.log_rate_limit_exceeded(endpoint="/health")

    def test_logs_without_limit(self, logger):
        logger.log_rate_limit_exceeded(ip_address="1.2.3.4")

    def test_logs_without_any_args(self, logger):
        logger.log_rate_limit_exceeded()


class TestLogModuleRejected:

    def test_logs_module_rejected(self, logger):
        logger.log_module_rejected(
            module_name="unknown_module",
            reason="not in allowlist"
        )

    def test_logs_different_modules(self, logger):
        logger.log_module_rejected("evil_module", "disabled by admin")
        logger.log_module_rejected("test_module", "not found")


class TestLogConfigValidationFailed:

    def test_logs_config_failure(self, logger):
        logger.log_config_validation_failed(
            config_key="NEXE_PRIMARY_API_KEY",
            reason="too short"
        )

    def test_logs_with_value(self, logger):
        logger.log_config_validation_failed(
            config_key="NEXE_ENV",
            reason="invalid value",
            value="unknown"
        )

    def test_logs_without_value_redacts(self, logger):
        # Sense value → [redacted]
        logger.log_config_validation_failed(
            config_key="SECRET_KEY",
            reason="missing"
        )


class TestLogXssAttempt:

    def test_logs_xss(self, logger):
        logger.log_xss_attempt(
            input_data="<script>alert('xss')</script>",
            ip_address="1.2.3.4",
            endpoint="/ui/chat",
            parameter="message"
        )

    def test_logs_xss_minimal(self, logger):
        logger.log_xss_attempt(input_data="<img onerror=x>")


class TestLogSqlInjection:

    def test_logs_sql_injection(self, logger):
        logger.log_sql_injection_attempt(
            input_data="'; DROP TABLE users; --",
            ip_address="5.6.7.8",
            endpoint="/api/v1/query",
            parameter="q"
        )

    def test_logs_sql_minimal(self, logger):
        logger.log_sql_injection_attempt(input_data="' OR 1=1 --")


class TestLogCommandInjection:

    def test_logs_command_injection(self, logger):
        logger.log_command_injection_attempt(
            input_data="; rm -rf /",
            ip_address="9.8.7.6",
            endpoint="/api/exec",
            parameter="cmd"
        )

    def test_logs_command_minimal(self, logger):
        logger.log_command_injection_attempt(input_data="`cat /etc/passwd`")


class TestLogInvalidContentType:

    def test_logs_invalid_content_type(self, logger):
        logger.log_invalid_content_type(
            content_type="text/html",
            ip_address="1.2.3.4",
            endpoint="/api/v1/chat"
        )

    def test_logs_minimal(self, logger):
        logger.log_invalid_content_type(content_type="multipart/form-data")


class TestLogRequestTooLarge:

    def test_logs_request_too_large(self, logger):
        logger.log_request_too_large(
            size=10_000_000,
            max_size=1_000_000,
            ip_address="1.2.3.4",
            endpoint="/api/v1/chat"
        )

    def test_logs_minimal(self, logger):
        logger.log_request_too_large(size=999999, max_size=500000)
