"""Tests for plugins/security/checks/rate_limit_check.py — coverage gaps."""
import os
import pytest
from unittest.mock import patch, MagicMock


class TestRateLimitCheck:
    """Tests for RateLimitCheck.run()."""

    def test_slowapi_available(self):
        from plugins.security.checks.rate_limit_check import RateLimitCheck
        findings = RateLimitCheck().run()
        lib_findings = [f for f in findings if "library" in f["title"].lower()]
        assert len(lib_findings) >= 1

    def test_no_global_limit_configured(self):
        from plugins.security.checks.rate_limit_check import RateLimitCheck
        env = {"NEXE_RATE_LIMIT_GLOBAL": "", "NEXE_ENV": "development", "NEXE_RATE_LIMIT_HEALTH": "1000/minute"}
        with patch.dict(os.environ, env, clear=False):
            findings = RateLimitCheck().run()
        assert any("default" in f["title"].lower() for f in findings)

    def test_global_limit_set(self):
        from plugins.security.checks.rate_limit_check import RateLimitCheck
        env = {"NEXE_RATE_LIMIT_GLOBAL": "50/minute", "NEXE_ENV": "development", "NEXE_RATE_LIMIT_HEALTH": "100/minute"}
        with patch.dict(os.environ, env, clear=False):
            findings = RateLimitCheck().run()
        default_findings = [f for f in findings if "default global" in f.get("title", "").lower()]
        assert len(default_findings) == 0

    def test_high_health_limit_in_production(self):
        from plugins.security.checks.rate_limit_check import RateLimitCheck
        env = {
            "NEXE_RATE_LIMIT_GLOBAL": "100/minute",
            "NEXE_ENV": "production",
            "NEXE_RATE_LIMIT_HEALTH": "1000/minute",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = RateLimitCheck().run()
        assert any("health endpoint" in f["title"].lower() for f in findings)

    def test_low_health_limit_in_production_no_warning(self):
        from plugins.security.checks.rate_limit_check import RateLimitCheck
        env = {
            "NEXE_RATE_LIMIT_GLOBAL": "100/minute",
            "NEXE_ENV": "production",
            "NEXE_RATE_LIMIT_HEALTH": "100/minute",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = RateLimitCheck().run()
        health_high = [f for f in findings if "High health" in f.get("title", "")]
        assert len(health_high) == 0

    def test_tracker_operational(self):
        from plugins.security.checks.rate_limit_check import RateLimitCheck
        env = {"NEXE_RATE_LIMIT_GLOBAL": "", "NEXE_ENV": "development", "NEXE_RATE_LIMIT_HEALTH": "100/minute"}
        with patch.dict(os.environ, env, clear=False):
            findings = RateLimitCheck().run()
        tracker_findings = [f for f in findings if "tracker" in f["title"].lower()]
        assert len(tracker_findings) >= 1
