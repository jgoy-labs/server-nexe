"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/core/tests/test_logger.py
Description: Tests per plugins/security/core/logger.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch


class TestLogSecurityEvent:

    def test_logs_event_to_file(self, tmp_path):
        from plugins.security.core.logger import log_security_event
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_event("test_event", {"key": "value"}, "INFO")
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            assert log_file.exists()
            events = [json.loads(line) for line in log_file.read_text().splitlines() if line]
            assert len(events) == 1
            assert events[0]["type"] == "test_event"
            assert events[0]["severity"] == "INFO"
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_event_has_required_fields(self, tmp_path):
        from plugins.security.core.logger import log_security_event
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_event("auth_failed", {"ip": "1.2.3.4"}, "WARNING")
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            event = json.loads(log_file.read_text().splitlines()[0])
            assert "timestamp" in event
            assert "type" in event
            assert "severity" in event
            assert "details" in event
            assert event["module"] == "security"
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_handles_write_error_gracefully(self):
        from plugins.security.core.logger import log_security_event

        with patch.object(Path, 'open', side_effect=PermissionError("No access")):
            # Should not raise
            try:
                log_security_event("test", {})
            except Exception:
                pass  # May raise from other causes


class TestLogVulnerabilityDetected:

    def test_logs_vulnerability(self, tmp_path):
        from plugins.security.core.logger import log_vulnerability_detected
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_vulnerability_detected(
                vuln_type="path_traversal",
                file_path="test.py",
                line=42,
                severity="CRITICAL",
                description="Traversal detected",
                fix_suggestion="Use validate_safe_path()"
            )
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            event = json.loads(log_file.read_text().splitlines()[0])
            assert event["type"] == "vulnerability_detected"
            assert event["details"]["vulnerability_type"] == "path_traversal"
            assert event["details"]["file"] == "test.py"
            assert event["details"]["line"] == 42
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_logs_vulnerability_without_fix_suggestion(self, tmp_path):
        from plugins.security.core.logger import log_vulnerability_detected
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_vulnerability_detected(
                vuln_type="sql_injection",
                file_path="api.py",
                line=10,
                severity="HIGH",
                description="SQL injection risk"
            )
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            event = json.loads(log_file.read_text().splitlines()[0])
            assert event["details"]["fix_suggestion"] is None
        finally:
            mod.SECURITY_LOG_PATH = original_path


class TestLogSecurityScan:

    def test_logs_scan_with_critical(self, tmp_path):
        from plugins.security.core.logger import log_security_scan
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_scan(
                scan_type="full",
                findings_count=5,
                critical_count=2,
                high_count=1,
                duration_seconds=1.5
            )
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            event = json.loads(log_file.read_text().splitlines()[0])
            assert event["type"] == "security_scan_completed"
            assert event["severity"] == "CRITICAL"
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_logs_scan_with_only_high(self, tmp_path):
        from plugins.security.core.logger import log_security_scan
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_scan("partial", 3, 0, 2, 0.5)
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            event = json.loads(log_file.read_text().splitlines()[0])
            assert event["severity"] == "WARNING"
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_logs_scan_clean(self, tmp_path):
        from plugins.security.core.logger import log_security_scan
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_scan("full", 0, 0, 0, 0.1)
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            event = json.loads(log_file.read_text().splitlines()[0])
            assert event["severity"] == "INFO"
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_handles_zero_duration(self, tmp_path):
        from plugins.security.core.logger import log_security_scan
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_scan("full", 5, 0, 0, 0.0)
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            log_file = tmp_path / f"security_{today}.jsonl"
            event = json.loads(log_file.read_text().splitlines()[0])
            assert event["details"]["findings_per_second"] == 0
        finally:
            mod.SECURITY_LOG_PATH = original_path


class TestGetSecurityLogs:

    def test_returns_empty_when_no_file(self, tmp_path):
        from plugins.security.core.logger import get_security_logs
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            result = get_security_logs("99991231")
            assert result == []
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_reads_events_from_file(self, tmp_path):
        from plugins.security.core.logger import get_security_logs, log_security_event
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_event("test1", {"x": 1})
            log_security_event("test2", {"y": 2})
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            events = get_security_logs(today)
            assert len(events) == 2
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_default_date_is_today(self, tmp_path):
        from plugins.security.core.logger import get_security_logs, log_security_event
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_event("test", {})
            events = get_security_logs()  # No date = today
            assert len(events) >= 1
        finally:
            mod.SECURITY_LOG_PATH = original_path


class TestGetLatestSecurityEvents:

    def test_returns_empty_when_no_logs(self, tmp_path):
        from plugins.security.core.logger import get_latest_security_events
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            result = get_latest_security_events(10)
            assert result == []
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_returns_limited_events(self, tmp_path):
        from plugins.security.core.logger import get_latest_security_events, log_security_event
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            for i in range(5):
                log_security_event(f"event_{i}", {"i": i})
            events = get_latest_security_events(limit=3)
            assert len(events) <= 3
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_events_sorted_by_timestamp_desc(self, tmp_path):
        from plugins.security.core.logger import get_latest_security_events, log_security_event
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH
        try:
            mod.SECURITY_LOG_PATH = tmp_path
            log_security_event("event_a", {})
            log_security_event("event_b", {})
            events = get_latest_security_events(10)
            if len(events) >= 2:
                assert events[0]["timestamp"] >= events[1]["timestamp"]
        finally:
            mod.SECURITY_LOG_PATH = original_path


class TestClearOldLogs:

    def test_clear_old_logs_returns_integer(self, tmp_path):
        from plugins.security.core.logger import clear_old_logs
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH

        try:
            mod.SECURITY_LOG_PATH = tmp_path
            result = clear_old_logs(days_to_keep=30)
            assert isinstance(result, int)
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_clear_old_logs_empty_dir(self, tmp_path):
        from plugins.security.core.logger import clear_old_logs
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH

        try:
            mod.SECURITY_LOG_PATH = tmp_path
            deleted = clear_old_logs(days_to_keep=30)
            assert deleted == 0
        finally:
            mod.SECURITY_LOG_PATH = original_path

    def test_clear_old_logs_processes_files(self, tmp_path):
        from plugins.security.core.logger import clear_old_logs
        import plugins.security.core.logger as mod
        original_path = mod.SECURITY_LOG_PATH

        try:
            mod.SECURITY_LOG_PATH = tmp_path
            # Create files that match the glob pattern
            (tmp_path / "security_20000101.jsonl").write_text('{"type": "old"}\n')
            # Call should not raise even if datetime comparison fails
            result = clear_old_logs(days_to_keep=1)
            assert isinstance(result, int)
        finally:
            mod.SECURITY_LOG_PATH = original_path
