"""Fixtures shared by the web UI module's tests that drive the real routes.

#1145: those tests POST to `/ui/session/new` and `/ui/chat`, and the routes
write to the module's `session_manager`. The module binds the process-wide
SessionManager of the core, whose folder is `storage/data/sessions` of the
repo: the sessions of the product, and DEV's sidebar. A test that drives these
routes asks for `private_sessions`.
"""
from __future__ import annotations

import pytest

from core.sessions.session_manager import SessionManager


@pytest.fixture
def private_sessions(tmp_path, monkeypatch):
    """A SessionManager that stores in the test's own folder, and is the
    process-wide one while the test runs: whatever initializes the module (or
    the integration lifespan) afterwards gets it from `attach_session_manager`
    instead of binding the product's. A module that was already initialized by
    an earlier test keeps what it had bound: the test rebinds that itself."""
    from core.server_state import get_server_state

    manager = SessionManager(storage_path=str(tmp_path / "sessions"))
    monkeypatch.setattr(get_server_state(), "session_manager", manager, raising=False)
    return manager


@pytest.fixture
def product_sessions():
    """What is in the product's session folder now, with each file's mtime:
    what a test must not touch. Call it before and after."""
    from core.paths.helpers import get_data_dir

    def snapshot() -> dict:
        return {p.name: p.stat().st_mtime_ns for p in get_data_dir("sessions").iterdir()}

    return snapshot
