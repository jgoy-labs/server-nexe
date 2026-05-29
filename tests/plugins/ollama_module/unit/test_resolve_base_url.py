"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/ollama_module/unit/test_resolve_base_url.py
Description: resolve_base_url() must normalise OLLAMA_HOST / NEXE_OLLAMA_HOST into
             a connectable client URL. Regression for the 0.0.0.0 bind-address bug:
             OLLAMA_HOST=0.0.0.0 produced an unconnectable URL ("missing protocol")
             that opened the Ollama circuit breaker and forced the MLX fallback.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from plugins.ollama_module.core.client import resolve_base_url


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        # Bind-all IPv4 (the reported bug): not connectable from a client → loopback.
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("0.0.0.0:11434", "http://127.0.0.1:11434"),
        ("0.0.0.0:9999", "http://127.0.0.1:9999"),
        ("http://0.0.0.0:11434", "http://127.0.0.1:11434"),
        # Missing scheme → prepend http://; missing port → default 11434.
        ("localhost", "http://localhost:11434"),
        ("localhost:11434", "http://localhost:11434"),
        (" localhost:11434 ", "http://localhost:11434"),
        # Legitimate remote hosts must be preserved (only scheme/port completed).
        ("192.168.1.50:11434", "http://192.168.1.50:11434"),
        ("http://192.168.1.50:11434", "http://192.168.1.50:11434"),
        ("http://192.168.1.50:11434/", "http://192.168.1.50:11434"),
        # HTTPS preserved; no port → leave to httpx default (443), never force 11434.
        ("https://ollama.example.com:443", "https://ollama.example.com:443"),
        ("https://ollama.example.com", "https://ollama.example.com"),
        # IPv6 loopback keeps its brackets.
        ("[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_resolve_base_url_normalises_ollama_host(monkeypatch, env_value, expected):
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", env_value)
    assert resolve_base_url() == expected


def test_resolve_base_url_default_when_unset(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert resolve_base_url() == "http://localhost:11434"


def test_resolve_base_url_empty_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "")
    assert resolve_base_url() == "http://localhost:11434"


def test_resolve_base_url_nexe_overrides_ollama(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_HOST", "http://custom:1234")
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0")
    assert resolve_base_url() == "http://custom:1234"
