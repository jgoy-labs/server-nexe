"""
Tests for core.config network defaults — Q4.1.

Centralizes DEFAULT_HOST, DEFAULT_PORT, get_default_host(), get_default_port(),
get_server_url() to remove hardcoded "9119" / "127.0.0.1" literals across
runner.py, lifespan.py, middleware.py, cli/*, installer/tray.py and
plugins/web_ui_module/module.py.

Cirurgia post-BUS Q4.1 (Gemini hardcode fix).
"""

import pytest

from core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    get_default_host,
    get_default_port,
    get_server_url,
)


class TestNetworkDefaults:
    def test_default_host_constant(self):
        assert DEFAULT_HOST == "127.0.0.1"

    def test_default_port_constant(self):
        assert DEFAULT_PORT == 9119

    def test_get_default_host_returns_default_without_env(self, monkeypatch):
        monkeypatch.delenv("NEXE_SERVER_HOST", raising=False)
        assert get_default_host() == DEFAULT_HOST

    def test_get_default_host_reads_env(self, monkeypatch):
        monkeypatch.setenv("NEXE_SERVER_HOST", "0.0.0.0")
        assert get_default_host() == "0.0.0.0"

    def test_get_default_port_returns_default_without_env(self, monkeypatch):
        monkeypatch.delenv("NEXE_SERVER_PORT", raising=False)
        assert get_default_port() == DEFAULT_PORT

    def test_get_default_port_reads_env(self, monkeypatch):
        monkeypatch.setenv("NEXE_SERVER_PORT", "8080")
        assert get_default_port() == 8080

    def test_get_default_port_returns_int_not_str(self, monkeypatch):
        monkeypatch.setenv("NEXE_SERVER_PORT", "12345")
        result = get_default_port()
        assert isinstance(result, int)
        assert result == 12345

    def test_get_default_port_invalid_raises(self, monkeypatch):
        """Fail-fast: invalid NEXE_SERVER_PORT raises, no silent fallback."""
        monkeypatch.setenv("NEXE_SERVER_PORT", "not-a-number")
        with pytest.raises(ValueError):
            get_default_port()

    def test_get_default_port_empty_falls_back(self, monkeypatch):
        monkeypatch.setenv("NEXE_SERVER_PORT", "")
        assert get_default_port() == DEFAULT_PORT


class TestGetServerUrl:
    def test_default_url(self, monkeypatch):
        monkeypatch.delenv("NEXE_SERVER_HOST", raising=False)
        monkeypatch.delenv("NEXE_SERVER_PORT", raising=False)
        assert get_server_url() == "http://127.0.0.1:9119"

    def test_custom_scheme(self, monkeypatch):
        monkeypatch.delenv("NEXE_SERVER_HOST", raising=False)
        monkeypatch.delenv("NEXE_SERVER_PORT", raising=False)
        assert get_server_url("https") == "https://127.0.0.1:9119"

    def test_env_override_host_and_port(self, monkeypatch):
        monkeypatch.setenv("NEXE_SERVER_HOST", "192.168.1.10")
        monkeypatch.setenv("NEXE_SERVER_PORT", "8443")
        assert get_server_url() == "http://192.168.1.10:8443"

    def test_env_override_with_https(self, monkeypatch):
        monkeypatch.setenv("NEXE_SERVER_HOST", "0.0.0.0")
        monkeypatch.setenv("NEXE_SERVER_PORT", "443")
        assert get_server_url("https") == "https://0.0.0.0:443"
