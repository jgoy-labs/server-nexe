"""D-I phase 2 — UI auto cascade matches the core, no-engine is 503.

ADR-005 D-I / B260: auto is mlx → llama_cpp → ollama. Explicit picks
keep that engine first. MLX first is skipped by the caller when the
module is absent (non-Mac). Without any engine the product path must
not return 200 with an error string in the body.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from plugins.web_ui_module.api.routes_auth import _mark_active_backend
from plugins.web_ui_module.api.routes_chat import _resolve_engines


def _backend(bid: str, *, models=None, connected=True):
    return {
        "id": bid,
        "name": bid,
        "models": models if models is not None else [{"name": "m"}],
        "active": False,
        "connected": connected,
    }


def test_auto_follows_core_cascade():
    assert _resolve_engines("auto") == [
        "mlx_module",
        "llama_cpp_module",
        "ollama_module",
    ]


def test_explicit_ollama_still_starts_with_ollama():
    order = _resolve_engines("ollama")
    assert order[0] == "ollama_module"
    assert "mlx_module" in order


def test_explicit_mlx_and_llamacpp_keep_their_head():
    assert _resolve_engines("mlx")[0] == "mlx_module"
    assert _resolve_engines("llamacpp")[0] == "llama_cpp_module"


def test_unknown_preferred_uses_cascade_not_ollama_first():
    assert _resolve_engines("whatever")[0] == "mlx_module"


def test_auto_dropdown_prefers_mlx_when_present():
    backends = [
        _backend("ollama"),
        _backend("mlx"),
        _backend("llamacpp"),
    ]
    returned = _mark_active_backend(backends, "auto")
    assert returned == "auto"
    assert [b["id"] for b in backends if b["active"]] == ["mlx"]


def test_auto_dropdown_skips_mlx_when_absent():
    backends = [_backend("ollama"), _backend("llamacpp")]
    _mark_active_backend(backends, "auto")
    assert [b["id"] for b in backends if b["active"]] == ["llamacpp"]


def test_auto_dropdown_ollama_when_only_ollama():
    backends = [_backend("ollama")]
    _mark_active_backend(backends, "auto")
    assert [b["id"] for b in backends if b["active"]] == ["ollama"]


def test_explicit_ollama_not_rewritten_to_mlx():
    backends = [_backend("ollama"), _backend("mlx")]
    returned = _mark_active_backend(backends, "ollama")
    assert returned == "ollama"
    assert [b["id"] for b in backends if b["active"]] == ["ollama"]


def test_auto_does_not_mark_disconnected_mlx():
    backends = [
        _backend("mlx", connected=False),
        _backend("ollama"),
    ]
    _mark_active_backend(backends, "auto")
    assert [b["id"] for b in backends if b["active"]] == ["ollama"]


@pytest.mark.asyncio
async def test_no_engine_raises_503_not_200(monkeypatch):
    """Product path: no usable engine is an HTTP error, not a fake reply."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from fastapi import APIRouter
    from starlette.datastructures import State
    from starlette.requests import Request as StarletteRequest

    from plugins.web_ui_module.api.routes_chat import register_chat_routes
    from plugins.web_ui_module.core.session_manager import ChatSession

    registry = MagicMock()
    registry.list_modules.return_value = []
    registry.get_module.return_value = None
    state = MagicMock()
    state.module_manager = MagicMock(registry=registry)
    state.project_root = "/tmp"

    session = ChatSession(session_id="di-f2")
    session_mgr = MagicMock()
    session_mgr.get_or_create_session = MagicMock(return_value=session)
    session_mgr._save_session_to_disk = MagicMock()
    session_mgr.is_valid_session_id = MagicMock(return_value=True)

    mh = MagicMock()
    mh.detect_intent = MagicMock(return_value=("chat", None))
    mh.recall_from_memory = AsyncMock(return_value={"success": True, "results": []})

    router = APIRouter()
    register_chat_routes(
        router, session_mgr=session_mgr, require_ui_auth=AsyncMock(return_value=None)
    )
    endpoint = next(r.endpoint for r in router.routes if getattr(r, "path", None) == "/chat")

    app_mock = MagicMock()
    app_mock.state = State()
    app_mock.state.i18n = None
    req = StarletteRequest({
        "type": "http", "method": "POST", "path": "/ui/chat",
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 12345),
        "app": app_mock, "state": State(),
    })

    patches = [
        patch("plugins.web_ui_module.api.routes_chat._get_memory_helper", return_value=mh),
        patch("plugins.web_ui_module.api.routes_chat._compact_session", new=AsyncMock()),
        patch("core.lifespan.get_server_state", return_value=state),
    ]
    for p in patches:
        p.start()
    try:
        with pytest.raises(HTTPException) as ei:
            await endpoint(req, {"message": "hola"}, None)
    finally:
        for p in reversed(patches):
            p.stop()

    assert ei.value.status_code == 503
    assert ei.value.detail == "No AI engine available"
    assert not any(
        m["role"] == "assistant" for m in session.messages
    )
