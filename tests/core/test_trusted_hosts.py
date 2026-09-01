"""
Tests for core.config.get_trusted_hosts() — #864.

Split out of get_localhost_aliases()/NEXE_LOCALHOST_ALIASES: that list answers
a different question (client IP for the bootstrap endpoint) and an alias
added for it used to leak into the Host-header allow-list too. Mirrors
test_localhost_aliases.py's coverage for the twin function.
"""

import pytest

from core.config import get_trusted_hosts, DEFAULT_TRUSTED_HOSTS


class TestGetTrustedHosts:
    def test_default_hosts(self, monkeypatch):
        monkeypatch.delenv("NEXE_TRUSTED_HOSTS", raising=False)
        result = get_trusted_hosts()
        assert result == ["127.0.0.1", "::1", "localhost"]
        assert result == DEFAULT_TRUSTED_HOSTS

    def test_default_returns_copy_not_reference(self, monkeypatch):
        """Mutating the result must not affect the global default."""
        monkeypatch.delenv("NEXE_TRUSTED_HOSTS", raising=False)
        result = get_trusted_hosts()
        result.append("evil.com")
        assert "evil.com" not in DEFAULT_TRUSTED_HOSTS

    def test_env_host_single_is_added(self, monkeypatch):
        monkeypatch.setenv("NEXE_TRUSTED_HOSTS", "example.local")
        assert get_trusted_hosts() == ["127.0.0.1", "::1", "localhost", "example.local"]

    def test_env_host_multiple_are_added(self, monkeypatch):
        monkeypatch.setenv("NEXE_TRUSTED_HOSTS", "example.local,host.docker.internal")
        result = get_trusted_hosts()
        assert "example.local" in result
        assert "host.docker.internal" in result

    def test_env_host_never_drops_the_defaults(self, monkeypatch):
        """Setting a custom host must not lock the local user out."""
        monkeypatch.setenv("NEXE_TRUSTED_HOSTS", "example.local")
        result = get_trusted_hosts()
        for default in DEFAULT_TRUSTED_HOSTS:
            assert default in result, f"{default} lost after setting a trusted host"

    def test_env_host_repeating_a_default_does_not_duplicate(self, monkeypatch):
        monkeypatch.setenv("NEXE_TRUSTED_HOSTS", "127.0.0.1,example.local,localhost")
        result = get_trusted_hosts()
        assert result.count("127.0.0.1") == 1
        assert result.count("localhost") == 1
        assert result == ["127.0.0.1", "::1", "localhost", "example.local"]

    def test_env_host_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("NEXE_TRUSTED_HOSTS", " example.local , foo.local ")
        result = get_trusted_hosts()
        assert result == ["127.0.0.1", "::1", "localhost", "example.local", "foo.local"]

    def test_env_override_empty_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NEXE_TRUSTED_HOSTS", "")
        assert get_trusted_hosts() == DEFAULT_TRUSTED_HOSTS

    def test_env_override_only_commas_falls_back(self, monkeypatch):
        monkeypatch.setenv("NEXE_TRUSTED_HOSTS", " , , ")
        result = get_trusted_hosts()
        assert "" not in result
        assert result == DEFAULT_TRUSTED_HOSTS

    def test_localhost_aliases_no_longer_affects_trusted_hosts(self, monkeypatch):
        """#864: the two env vars must not leak into each other anymore."""
        monkeypatch.delenv("NEXE_TRUSTED_HOSTS", raising=False)
        monkeypatch.setenv("NEXE_LOCALHOST_ALIASES", "some-lan-host")
        result = get_trusted_hosts()
        assert "some-lan-host" not in result
        assert result == DEFAULT_TRUSTED_HOSTS
