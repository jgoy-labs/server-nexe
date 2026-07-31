"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_f855_ollama_install_keepalive.py
Description: #855 — POST /installer/ollama ran the whole install in an executor
             without emitting a single SSE event until done/error. Since #833
             the install legitimately waits on an API probe (30-60 s), and
             WebKit (the Tauri WebView on macOS) drops EventSource/fetch
             streams that stay silent for >~30 s: the wizard looked hung, or
             died without a word.

             Same fix the model download already carries (installer.py:240-242):
             a keepalive event while the worker runs.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.endpoints import installer

BUNDLE = "/Applications/Ollama.app/Contents/Resources/ollama"


def _events(text: str) -> list:
    return [
        json.loads(line[5:].strip())
        for line in text.splitlines()
        if line.startswith("data:") and line[5:].strip()
    ]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(installer.router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _install_branch(monkeypatch):
    """Force the "not installed yet" branch and free the process-wide lock."""
    monkeypatch.setattr(installer, "_find_ollama_bin", lambda: None)
    if installer._ollama_install_lock.locked():
        installer._ollama_install_lock.release()


def _slow_install(delay: float, result: str = BUNDLE):
    async def _run():
        await asyncio.sleep(delay)
        return result
    return _run


class TestKeepaliveWhileInstalling:

    def test_slow_install_emits_keepalives_before_done(self, monkeypatch):
        """#855: a silent stream is what WebKit kills. A long install must keep
        the connection fed while the executor works.

        Mutation guard: await _install_ollama_and_locate() directly (the
        pre-fix shape) and this goes RED — zero keepalive events.
        """
        monkeypatch.setattr(installer, "_OLLAMA_INSTALL_KEEPALIVE_S", 0.05)
        monkeypatch.setattr(installer, "_install_ollama_and_locate", _slow_install(0.35))

        resp = _client().post("/installer/ollama")
        assert resp.status_code == 200
        events = _events(resp.text)
        keepalives = [e for e in events if e.get("type") == "keepalive"]
        assert len(keepalives) >= 3, (
            f"#855: install ran ~7 keepalive periods and emitted {len(keepalives)}: {events}"
        )

    def test_keepalives_carry_a_monotonic_timestamp(self, monkeypatch):
        """Same shape as the download keepalive so one client handler covers
        both streams."""
        monkeypatch.setattr(installer, "_OLLAMA_INSTALL_KEEPALIVE_S", 0.05)
        monkeypatch.setattr(installer, "_install_ollama_and_locate", _slow_install(0.2))

        events = _events(_client().post("/installer/ollama").text)
        keepalives = [e for e in events if e.get("type") == "keepalive"]
        assert keepalives, "no keepalive emitted"
        assert all(isinstance(k.get("ts"), (int, float)) for k in keepalives)
        stamps = [k["ts"] for k in keepalives]
        assert stamps == sorted(stamps), f"keepalive timestamps went backwards: {stamps}"

    def test_no_keepalive_when_the_install_is_quick(self, monkeypatch):
        """No noise on the happy path: nothing is emitted before the first
        keepalive period elapses.

        Mutation guards: emit the keepalive unconditionally on every loop turn,
        OR set the wait timeout to 0 — both go RED here.

        The delay is 0.02 s, NOT 0.0: an install that finishes within a single
        event-loop cycle is the one case where timeout=0 and timeout=30 are
        indistinguishable, and the first version of this test used it. The
        timeout=0 mutant survived and was written up as "not a valid mutation";
        it was a blind test (ALERT-1 of the phase-1 audit). A few cycles of real
        waiting are what make the period observable.
        """
        monkeypatch.setattr(installer, "_OLLAMA_INSTALL_KEEPALIVE_S", 30.0)
        monkeypatch.setattr(installer, "_install_ollama_and_locate", _slow_install(0.02))

        events = _events(_client().post("/installer/ollama").text)
        assert not [e for e in events if e.get("type") == "keepalive"], events


class TestContractsPreserved:
    """The keepalive must not disturb what the wizard (and MC-031) rely on."""

    def test_done_event_still_carries_the_binary(self, monkeypatch):
        monkeypatch.setattr(installer, "_OLLAMA_INSTALL_KEEPALIVE_S", 0.05)
        monkeypatch.setattr(installer, "_install_ollama_and_locate", _slow_install(0.15))

        events = _events(_client().post("/installer/ollama").text)
        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1
        assert done[-1]["already_installed"] is False
        assert done[-1]["binary"] == BUNDLE
        assert events[0]["type"] == "progress", events
        assert events[-1]["type"] == "done", events

    def test_install_failure_still_reports_the_error(self, monkeypatch):
        async def _boom():
            await asyncio.sleep(0.12)
            raise RuntimeError("Ollama install failed: no admin rights")

        monkeypatch.setattr(installer, "_OLLAMA_INSTALL_KEEPALIVE_S", 0.05)
        monkeypatch.setattr(installer, "_install_ollama_and_locate", _boom)

        events = _events(_client().post("/installer/ollama").text)
        errors = [e for e in events if e.get("type") == "error"]
        assert errors, f"the RuntimeError path lost its error event: {events}"
        assert "no admin rights" in errors[-1]["message"]
        assert not [e for e in events if e.get("type") == "done"]
        assert not installer._ollama_install_lock.locked(), (
            "the install lock leaked on the error path"
        )

    def test_already_installed_short_circuit_is_untouched(self, monkeypatch):
        monkeypatch.setattr(installer, "_find_ollama_bin", lambda: BUNDLE)
        events = _events(_client().post("/installer/ollama").text)
        assert events == [{"type": "done", "already_installed": True}]

    def test_concurrent_install_still_refused(self, monkeypatch):
        monkeypatch.setattr(installer, "_OLLAMA_INSTALL_KEEPALIVE_S", 0.05)
        monkeypatch.setattr(installer, "_install_ollama_and_locate", _slow_install(0.05))
        installer._ollama_install_lock.acquire(blocking=False)
        try:
            events = _events(_client().post("/installer/ollama").text)
        finally:
            installer._ollama_install_lock.release()
        assert [e["type"] for e in events] == ["progress", "error"]
        assert "instal" in events[-1]["message"].lower()
