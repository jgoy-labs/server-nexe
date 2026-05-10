"""Tests for plugins/security/checks/web_security_check.py — coverage gaps."""
import os
import pytest
from unittest.mock import patch


class TestWebSecurityCheck:
    """Tests for WebSecurityCheck.run()."""

    def test_no_cors_origins_medium(self):
        from plugins.security.checks.web_security_check import WebSecurityCheck
        env = {"NEXE_CORS_ORIGINS": "", "NEXE_ENV": "development", "NEXE_SSL_CERT": ""}
        with patch.dict(os.environ, env, clear=False):
            findings = WebSecurityCheck().run()
        assert any("CORS origins not configured" in f["title"] for f in findings)

    def test_cors_wildcard_high(self):
        from plugins.security.checks.web_security_check import WebSecurityCheck
        env = {"NEXE_CORS_ORIGINS": "*", "NEXE_ENV": "development", "NEXE_SSL_CERT": ""}
        with patch.dict(os.environ, env, clear=False):
            findings = WebSecurityCheck().run()
        assert any("all origins" in f["title"].lower() for f in findings)

    def test_cors_specific_origins_no_warning(self):
        from plugins.security.checks.web_security_check import WebSecurityCheck
        env = {"NEXE_CORS_ORIGINS": "https://example.com", "NEXE_ENV": "development", "NEXE_SSL_CERT": ""}
        with patch.dict(os.environ, env, clear=False):
            findings = WebSecurityCheck().run()
        cors_findings = [f for f in findings if "CORS" in f["title"]]
        assert len(cors_findings) == 0

    def test_injection_detectors_available(self):
        from plugins.security.checks.web_security_check import WebSecurityCheck
        env = {"NEXE_CORS_ORIGINS": "https://example.com", "NEXE_ENV": "development", "NEXE_SSL_CERT": ""}
        with patch.dict(os.environ, env, clear=False):
            findings = WebSecurityCheck().run()
        assert any("detectors operational" in f["title"].lower() for f in findings)

    def test_no_ssl_in_production(self):
        from plugins.security.checks.web_security_check import WebSecurityCheck
        env = {"NEXE_CORS_ORIGINS": "https://example.com", "NEXE_ENV": "production", "NEXE_SSL_CERT": ""}
        with patch.dict(os.environ, env, clear=False):
            findings = WebSecurityCheck().run()
        assert any("SSL" in f["title"] for f in findings)

    def test_ssl_configured_no_warning(self):
        from plugins.security.checks.web_security_check import WebSecurityCheck
        env = {"NEXE_CORS_ORIGINS": "https://example.com", "NEXE_ENV": "production", "NEXE_SSL_CERT": "/path/to/cert.pem"}
        with patch.dict(os.environ, env, clear=False):
            findings = WebSecurityCheck().run()
        ssl_findings = [f for f in findings if "SSL" in f.get("title", "")]
        assert len(ssl_findings) == 0

    def test_sanitizer_check_runs(self):
        from plugins.security.checks.web_security_check import WebSecurityCheck
        env = {"NEXE_CORS_ORIGINS": "https://example.com", "NEXE_ENV": "development", "NEXE_SSL_CERT": ""}
        with patch.dict(os.environ, env, clear=False):
            findings = WebSecurityCheck().run()
        sanitizer_findings = [f for f in findings if "anitizer" in f["title"]]
        assert len(sanitizer_findings) >= 1
