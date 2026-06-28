"""MC-031: the Ollama install machine was duplicated between
_install_ollama_if_needed (RuntimeError path, used by _stream_ollama) and
install_ollama_endpoint (SSE path, POST /installer/ollama). The duplication
hid a real divergence: only the RuntimeError path applied the bundle-binary
fallback when the CLI was installed but not yet on PATH; the SSE path returned
``binary: null`` to the frontend in that edge case.

These tests pin the unified behaviour: both paths must locate the bundle
binary via the shared helper.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.endpoints import installer

BUNDLE = "/Applications/Ollama.app/Contents/Resources/ollama"


@pytest.fixture()
def _ollama_installed_no_cli(monkeypatch):
    """Ollama just installed but the CLI is not yet registered on PATH, while
    the bundle binary exists on disk."""
    monkeypatch.setattr(installer, "_find_ollama_bin", lambda: None)
    monkeypatch.setattr(
        "installer.installer_ollama_install.ensure_ollama_installed",
        lambda *a, **k: True,
    )
    real_isfile = installer.os.path.isfile
    real_access = installer.os.access
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: p == BUNDLE or real_isfile(p))
    monkeypatch.setattr(installer.os, "access", lambda p, m=0: p == BUNDLE or real_access(p, m))
    # Make sure the install lock starts free.
    if installer._ollama_install_lock.locked():
        installer._ollama_install_lock.release()


def test_endpoint_returns_bundle_binary_when_cli_not_registered(_ollama_installed_no_cli):
    app = FastAPI()
    app.include_router(installer.router)
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.post("/installer/ollama")
    assert resp.status_code == 200
    events = [
        json.loads(line[5:].strip())
        for line in resp.text.splitlines()
        if line.startswith("data:") and line[5:].strip()
    ]
    done = [e for e in events if e.get("type") == "done"]
    assert done, f"no done event: {events}"
    assert done[-1].get("already_installed") is False
    # Divergence fix: the SSE path must return the bundle binary, not null.
    assert done[-1].get("binary") == BUNDLE, f"MC-031 divergence: binary={done[-1].get('binary')}"


async def test_shared_helper_applies_bundle_fallback(_ollama_installed_no_cli):
    # The shared helper both paths delegate to must locate the bundle binary.
    result = await installer._install_ollama_and_locate()
    assert result == BUNDLE
