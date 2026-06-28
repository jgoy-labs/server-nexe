"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/tests/test_ollama_utils.py
Description: Tests for core/ollama_utils.py — the canonical Ollama URL resolver
    (MC-089). Cascade behaviour + a guard that every Ollama client honours
    OLLAMA_HOST instead of hardcoding NEXE_OLLAMA_HOST-only.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import pytest

from core.ollama_utils import resolve_ollama_url
from core.sidecar_config import reset_sidecar_config


@pytest.fixture(autouse=True)
def _clean_sidecar(monkeypatch):
    monkeypatch.delenv("NEXE_SIDECAR", raising=False)
    reset_sidecar_config()
    yield
    reset_sidecar_config()


def test_resolves_nexe_ollama_host_first(monkeypatch):
    monkeypatch.setenv("NEXE_OLLAMA_HOST", "http://nexe.lan:11434")
    monkeypatch.setenv("OLLAMA_HOST", "http://ignored.lan:11434")
    assert resolve_ollama_url() == "http://nexe.lan:11434"


def test_honours_ollama_host_when_no_nexe(monkeypatch):
    # MC-089: the core bug — OLLAMA_HOST must be honoured (not ignored).
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://custom.lan:9999")
    assert resolve_ollama_url() == "http://custom.lan:9999"


def test_falls_back_to_localhost(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert resolve_ollama_url() == "http://localhost:11434"


def test_strips_trailing_slash(monkeypatch):
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://custom.lan:9999/")
    assert resolve_ollama_url() == "http://custom.lan:9999"


@pytest.mark.parametrize("raw,expected", [
    ("127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("0.0.0.0", "http://0.0.0.0"),
    ("ollama.lan:11434", "http://ollama.lan:11434"),
    ("https://secure.lan:443", "https://secure.lan:443"),
])
def test_adds_scheme_to_bare_host(monkeypatch, raw, expected):
    # Ollama's OLLAMA_HOST convention is bare host:port — must get a scheme so
    # httpx doesn't raise UnsupportedProtocol.
    monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", raw)
    assert resolve_ollama_url() == expected


# MC-089: every component that TALKS to Ollama must route through the shared
# resolver (which honours OLLAMA_HOST), not hardcode NEXE_OLLAMA_HOST-only.
# This guard fails if a fixed consumer reintroduces the bug.
@pytest.mark.parametrize("module_path", [
    "core.endpoints.chat_engines.ollama",
    "memory.memory.pipeline.ingestion",
    "memory.memory.workflow.nodes.memory_recall_node",
    "plugins.ollama_module.health",
])
def test_consumers_use_resolver_not_hardcoded_host(module_path):
    import importlib
    src = inspect.getsource(importlib.import_module(module_path))
    # the NEXE-only hardcode (no OLLAMA_HOST fallback) must be gone
    assert 'os.environ.get("NEXE_OLLAMA_HOST", "http://localhost:11434")' not in src
    assert "os.getenv(\"NEXE_OLLAMA_HOST\", \"http://localhost:11434\")" not in src
    assert "resolve_ollama_url" in src
