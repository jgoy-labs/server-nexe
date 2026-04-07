"""
Tests for core.config.get_localhost_aliases() — Gemini hardcode fix.

Centralizes the previously-hardcoded ["127.0.0.1", "::1", "localhost"]
lists spread across bootstrap.py and middleware.py.

Cirurgia post-BUS Q2.4.
"""

import pytest

from core.config import get_localhost_aliases, DEFAULT_LOCALHOST_ALIASES


class TestGetLocalhostAliases:
    def test_default_aliases(self, monkeypatch):
        monkeypatch.delenv("NEXE_LOCALHOST_ALIASES", raising=False)
        result = get_localhost_aliases()
        assert result == ["127.0.0.1", "::1", "localhost"]
        assert result == DEFAULT_LOCALHOST_ALIASES

    def test_default_returns_copy_not_reference(self, monkeypatch):
        """Mutating the result must not affect the global default."""
        monkeypatch.delenv("NEXE_LOCALHOST_ALIASES", raising=False)
        result = get_localhost_aliases()
        result.append("evil.com")
        assert "evil.com" not in DEFAULT_LOCALHOST_ALIASES

    def test_env_override_single(self, monkeypatch):
        monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", "10.0.0.1")
        assert get_localhost_aliases() == ["10.0.0.1"]

    def test_env_override_multiple(self, monkeypatch):
        monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", "10.0.0.1,172.16.0.1,host.docker.internal")
        result = get_localhost_aliases()
        assert "10.0.0.1" in result
        assert "172.16.0.1" in result
        assert "host.docker.internal" in result

    def test_env_override_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", " 10.0.0.1 , 172.16.0.1 ")
        result = get_localhost_aliases()
        assert result == ["10.0.0.1", "172.16.0.1"]

    def test_env_override_empty_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", "")
        assert get_localhost_aliases() == DEFAULT_LOCALHOST_ALIASES

    def test_env_override_only_commas_falls_back(self, monkeypatch):
        """Edge case: only commas/whitespace → strips empty → fallback OR empty list."""
        monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", " , , ")
        result = get_localhost_aliases()
        # Should NOT include empty strings
        assert "" not in result
