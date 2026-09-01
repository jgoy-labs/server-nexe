"""F-B / F-B.2 gate: SessionManager lives in core, instance too.

Mutation: put plugins/web_ui_module/core/session_manager.py back and
test_session_manager_module_is_not_in_the_ui_plugin goes red. Look the
instance up on web_ui_module again and
test_lifespan_does_not_read_the_instance_from_the_ui_plugin goes red.
Swap the save/detect_intent calls in routes_chat and
test_user_turn_is_saved_before_memory_runs goes red.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter
from starlette.datastructures import State
from starlette.requests import Request as StarletteRequest

from core.sessions import ChatSession

ROOT = Path(__file__).resolve().parents[2]


def test_session_manager_is_imported_from_core():
    from core.sessions import (
        ChatSession,
        SessionManager,
        attach_session_manager,
        start_session_cleanup_task,
    )

    assert SessionManager.__module__ == "core.sessions.session_manager"
    assert ChatSession.__module__ == "core.sessions.session_manager"
    assert start_session_cleanup_task.__module__ == "core.sessions.cleanup"
    assert attach_session_manager.__module__ == "core.sessions.attach"


def test_session_manager_module_is_not_in_the_ui_plugin():
    leftover = ROOT / "plugins" / "web_ui_module" / "core" / "session_manager.py"
    assert not leftover.exists(), (
        f"{leftover} still exists — SessionManager must live only in core/sessions/"
    )


def test_web_ui_module_consumes_core_sessions():
    import plugins.web_ui_module.module as web_ui

    from core.sessions import SessionManager
    assert web_ui.SessionManager is SessionManager
    src = (ROOT / "plugins" / "web_ui_module" / "module.py").read_text(encoding="utf-8")
    assert "SessionManager(" not in src, (
        "the UI plugin must consume the core instance, not construct its own"
    )


def test_core_has_zero_import_time_edges_into_plugins():
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import check_layering
    finally:
        sys.path.pop(0)

    edges = check_layering._edges()
    core_to_plugins = sorted(
        e for e in edges if e.startswith("core/") and " -> plugins." in e
    )
    assert core_to_plugins == [], (
        "core → plugins import-time edges must stay at zero after F-B: "
        f"{core_to_plugins}"
    )


def test_lifespan_does_not_read_the_instance_from_the_ui_plugin():
    """F-B.2: the instance is on server_state, not on web_ui_module."""
    src = (ROOT / "core" / "lifespan_sessions.py").read_text(encoding="utf-8")
    assert "web_ui_module" not in src
    assert 'modules.get("web_ui_module")' not in src
    lifespan = (ROOT / "core" / "lifespan.py").read_text(encoding="utf-8")
    enc = lifespan.index("await _startup_encryption(server_state)")
    sess = lifespan.index("await _startup_session_manager(server_state)")
    mods = lifespan.index("await _startup_module_discovery(app, server_state, _translate)")
    assert enc < sess < mods, (
        "SessionManager must be attached after encryption and before plugins"
    )


def test_attach_session_manager_puts_the_instance_on_server_state(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_ENV", "test")
    from core.sessions import SessionManager, attach_session_manager

    state = SimpleNamespace(crypto_provider=None, session_manager=None)
    mgr = attach_session_manager(state, storage_path=str(tmp_path))
    assert isinstance(mgr, SessionManager)
    assert state.session_manager is mgr
    assert attach_session_manager(state, storage_path=str(tmp_path / "other")) is mgr


def test_attach_session_manager_refuses_production_without_crypto(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_ENV", "production")
    from core.sessions import attach_session_manager

    state = SimpleNamespace(crypto_provider=None, session_manager=None)
    with pytest.raises(RuntimeError, match="crypto_provider is None in production"):
        attach_session_manager(state, storage_path=str(tmp_path))
    assert state.session_manager is None


def test_startup_session_manager_attaches_without_the_ui_plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_ENV", "test")
    from core.lifespan_sessions import _startup_session_manager
    from core.sessions import SessionManager

    state = SimpleNamespace(crypto_provider=None, session_manager=None)
    monkeypatch.setattr(
        "core.paths.helpers.get_data_dir",
        lambda name="": tmp_path / name if name else tmp_path,
    )
    asyncio.run(_startup_session_manager(state))
    assert isinstance(state.session_manager, SessionManager)


def test_startup_session_cleanup_uses_server_state(monkeypatch):
    from core.lifespan_sessions import _startup_session_cleanup

    captured = {}

    def _fake_start(mgr):
        captured["mgr"] = mgr
        return "task"

    monkeypatch.setattr(
        "core.sessions.start_session_cleanup_task", _fake_start
    )
    sentinel = object()
    state = SimpleNamespace(session_manager=sentinel, _session_cleanup_task=None)
    app = SimpleNamespace(state=SimpleNamespace(modules={}))
    asyncio.run(_startup_session_cleanup(app, state))
    assert captured["mgr"] is sentinel
    assert state._session_cleanup_task == "task"


@pytest.mark.asyncio
async def test_user_turn_is_saved_before_memory_runs():
    """Losing memory must not lose the conversation (plan 22/08).

    Spies: _save_session_to_disk is called before detect_intent. Changing a
    comment must stay green; swapping the two calls must go red.
    """
    from plugins.web_ui_module.api.routes_chat import register_chat_routes

    order: list[str] = []
    session = ChatSession(session_id="fb2-order")
    session_mgr = MagicMock()
    session_mgr.get_or_create_session.return_value = session
    session_mgr._save_session_to_disk.side_effect = lambda *a, **k: order.append("save")

    mh = MagicMock()

    def _detect(message):
        order.append("detect_intent")
        return ("save", "un fet")

    mh.detect_intent.side_effect = _detect
    mh.save_to_memory = AsyncMock(
        return_value={"success": True, "document_id": "doc-1"}
    )
    mh.matches_clear_all_confirm = MagicMock(return_value=False)

    router = APIRouter()
    register_chat_routes(
        router,
        session_mgr=session_mgr,
        require_ui_auth=AsyncMock(return_value=None),
    )
    endpoint = next(
        r.endpoint for r in router.routes if getattr(r, "path", None) == "/chat"
    )

    app_mock = MagicMock()
    app_mock.state = State()
    app_mock.state.i18n = None
    req = StarletteRequest(
        {
            "type": "http",
            "method": "POST",
            "path": "/ui/chat",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "app": app_mock,
            "state": State(),
        }
    )

    from core.dependencies import limiter

    previous = limiter.enabled
    limiter.enabled = False
    try:
        with patch(
            "plugins.web_ui_module.api.routes_chat._get_memory_helper",
            return_value=mh,
        ):
            await endpoint(req, {"message": "Recorda que em dic Joan"}, None)
    finally:
        limiter.enabled = previous

    assert "save" in order, f"user turn was never saved; calls={order}"
    assert "detect_intent" in order, f"intent was never detected; calls={order}"
    assert order.index("save") < order.index("detect_intent"), (
        "the user-turn save must run before detect_intent; "
        f"got {order}"
    )
