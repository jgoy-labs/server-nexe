"""F-C fix (2026-09-06): the /v1 thread mirror must reach disk on a REAL server.

What went wrong: `attach_session_manager` hangs the SessionManager on
`server_state`; `mirror_v1_conversation` / `persist_v1_turn` read
`request.app.state.session_manager`; nothing copied it across, the mirror found
None and returned silently. Every existing test set `app.state.session_manager`
by hand, so the suite was green while no /v1 conversation was ever persisted on
the product. Found by a live run on 2026-09-06: zero files in `sessions/` after a
complete /v1 turn, on the old and the new code alike.

These tests do what those could not: they go through the exposure step the
lifespan now performs, and they look at the DISK.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.endpoints.chat_engines._common import mirror_v1_conversation, persist_v1_turn
from core.endpoints.chat_schemas import Message
from core.lifespan_sessions import _expose_session_manager
from core.sessions import SessionManager, attach_session_manager

ROOT = Path(__file__).resolve().parents[2]


def _fake_app():
    return SimpleNamespace(state=SimpleNamespace())


@pytest.fixture
def attached(tmp_path, monkeypatch):
    """A server_state with the process-wide manager attached, dev mode (plaintext .json)."""
    monkeypatch.setenv("NEXE_ENV", "development")
    state = SimpleNamespace(crypto_provider=None, session_manager=None)
    attach_session_manager(state, storage_path=str(tmp_path / "sessions"))
    return state, tmp_path / "sessions"


def test_expose_puts_the_same_instance_on_app_state(attached):
    state, _ = attached
    app = _fake_app()
    _expose_session_manager(app, state)
    assert isinstance(app.state.session_manager, SessionManager)
    assert app.state.session_manager is state.session_manager  # one registry, not a copy


def test_v1_mirror_reaches_disk_through_app_state(attached):
    state, storage = attached
    app = _fake_app()
    _expose_session_manager(app, state)

    mirror_v1_conversation(app.state, "thread-abc123", [Message(role="user", content="hola, em dic Aran")])
    persist_v1_turn(app.state, "thread-abc123", "Hola Aran!")

    files = sorted(p.name for p in storage.glob("*.json"))
    assert files == ["thread-abc123.json"], files
    thread = state.session_manager.get_session("thread-abc123")
    assert [m["role"] for m in thread.messages] == ["user", "assistant"]


def test_without_exposure_nothing_reaches_disk_and_it_is_said(attached, caplog):
    """The pre-fix shape, kept as the negative: app.state without the manager."""
    state, storage = attached
    app = _fake_app()  # no _expose_session_manager
    with caplog.at_level(logging.WARNING):
        mirror_v1_conversation(app.state, "thread-abc123", [Message(role="user", content="hola")])
    assert list(storage.glob("*.json")) == []
    assert any("no session_manager on app state" in r.getMessage() for r in caplog.records)


def test_expose_without_attach_warns_and_leaves_app_state_alone(caplog):
    app = _fake_app()
    with caplog.at_level(logging.WARNING):
        _expose_session_manager(app, SimpleNamespace(session_manager=None))
    assert not hasattr(app.state, "session_manager")
    assert any("not attached" in r.getMessage() for r in caplog.records)


def test_lifespan_exposes_right_after_attaching():
    """Placement guard (the behaviour above proves the effect; this proves the
    lifespan actually calls it, in the one spot that has both app and state)."""
    src = (ROOT / "core" / "lifespan.py").read_text(encoding="utf-8")
    attach = src.index("await _startup_session_manager(server_state)")
    expose = src.index("_expose_session_manager(app, server_state)")
    modules = src.index("await _startup_module_discovery(app, server_state, _translate)")
    assert attach < expose < modules
