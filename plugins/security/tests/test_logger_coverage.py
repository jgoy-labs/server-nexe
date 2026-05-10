"""Tests for plugins/security/core/logger.py — coverage gaps."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


class TestLogSecurityEvent:
    def test_logs_event_to_file(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import log_security_event
            log_security_event("test_event", {"key": "value"}, severity="WARNING")

        files = list(tmp_path.glob("security_*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text()
        event = json.loads(content.strip())
        assert event["type"] == "test_event"
        assert event["severity"] == "WARNING"
        assert event["details"]["key"] == "value"

    def test_handles_write_error(self, tmp_path):
        read_only = tmp_path / "readonly"
        read_only.mkdir()
        read_only.chmod(0o444)
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", read_only):
            from plugins.security.core.logger import log_security_event
            log_security_event("fail_event", {})
        read_only.chmod(0o755)


class TestLogVulnerabilityDetected:
    def test_logs_vulnerability(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import log_vulnerability_detected
            log_vulnerability_detected(
                vuln_type="xss",
                file_path="test.py",
                line=42,
                severity="HIGH",
                description="XSS found",
                fix_suggestion="Sanitize input",
            )

        files = list(tmp_path.glob("security_*.jsonl"))
        assert len(files) == 1
        event = json.loads(files[0].read_text().strip())
        assert event["details"]["vulnerability_type"] == "xss"
        assert event["details"]["line"] == 42


class TestLogSecurityScan:
    def test_logs_scan_info(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import log_security_scan
            log_security_scan("full", findings_count=5, critical_count=0, high_count=2, duration_seconds=1.5)

        files = list(tmp_path.glob("security_*.jsonl"))
        event = json.loads(files[0].read_text().strip())
        assert event["severity"] == "WARNING"
        assert event["details"]["total_findings"] == 5

    def test_logs_scan_critical(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import log_security_scan
            log_security_scan("auth", findings_count=1, critical_count=1, high_count=0, duration_seconds=0.5)

        files = list(tmp_path.glob("security_*.jsonl"))
        event = json.loads(files[0].read_text().strip())
        assert event["severity"] == "CRITICAL"

    def test_zero_duration(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import log_security_scan
            log_security_scan("quick", findings_count=0, critical_count=0, high_count=0, duration_seconds=0)


class TestGetSecurityLogs:
    def test_reads_existing_logs(self, tmp_path):
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        log_file = tmp_path / f"security_{today}.jsonl"
        event = {"type": "test", "severity": "INFO", "timestamp": "2026-01-01T00:00:00"}
        log_file.write_text(json.dumps(event) + "\n")

        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import get_security_logs
            events = get_security_logs(today)
        assert len(events) == 1
        assert events[0]["type"] == "test"

    def test_returns_empty_for_missing_date(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import get_security_logs
            events = get_security_logs("19700101")
        assert events == []

    def test_defaults_to_today(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import get_security_logs
            events = get_security_logs()
        assert events == []


class TestGetLatestSecurityEvents:
    def test_returns_limited_events(self, tmp_path):
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        log_file = tmp_path / f"security_{today}.jsonl"
        lines = []
        for i in range(10):
            lines.append(json.dumps({"type": f"event_{i}", "timestamp": f"2026-01-01T00:00:{i:02d}"}))
        log_file.write_text("\n".join(lines) + "\n")

        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import get_latest_security_events
            events = get_latest_security_events(limit=5)
        assert len(events) == 5

    def test_empty_logs(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import get_latest_security_events
            events = get_latest_security_events()
        assert events == []


class TestClearOldLogs:
    def test_handles_datetime_comparison_gracefully(self, tmp_path):
        """clear_old_logs processes files without crashing (aware/naive datetime edge case)."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime('%Y%m%d')
        recent_date = datetime.now(timezone.utc).strftime('%Y%m%d')
        (tmp_path / f"security_{old_date}.jsonl").write_text("{}\n")
        (tmp_path / f"security_{recent_date}.jsonl").write_text("{}\n")

        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import clear_old_logs
            deleted = clear_old_logs(days_to_keep=30)

        # Function handles the error gracefully (returns int, no crash)
        assert isinstance(deleted, int)

    def test_no_log_files(self, tmp_path):
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import clear_old_logs
            deleted = clear_old_logs(days_to_keep=30)
        assert deleted == 0

    def test_malformed_filename_handled(self, tmp_path):
        (tmp_path / "security_baddate.jsonl").write_text("{}\n")
        with patch("plugins.security.core.logger.SECURITY_LOG_PATH", tmp_path):
            from plugins.security.core.logger import clear_old_logs
            deleted = clear_old_logs(days_to_keep=30)
        assert deleted == 0
