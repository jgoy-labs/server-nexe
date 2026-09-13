"""D-I phase 2 — UI auto cascade matches the core, no-engine is 503.

ADR-005 D-I / B260: auto is mlx → llama_cpp → ollama. Explicit picks keep that
engine first. Without any engine the product path must not return 200 with an
error string in the body.

F-D block 5: the UI no longer has a cascade of its own. It had
``_resolve_engines``, a second table in module-key spelling whose only alias was
"llamacpp" and which was not node-aware — so these tests could only check the
ORDER, never whether an engine in it could actually serve. They now drive
``resolve_engine_cascade``, the core's, which answers both at once.

One deliberate behaviour change: an explicit pick that is not serviceable now
falls back through the canonical cascade. Asking for MLX on a machine without it
used to land on Ollama (the UI table put ollama second for an explicit mlx) and
now lands on llama.cpp, which is what /v1 and /status have always answered.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from core.endpoints.chat_engines.routing import resolve_engine_cascade
from plugins.web_ui_module.api.routes_auth import _mark_active_backend

_MODULE_KEYS = {"mlx": "mlx_module", "llama_cpp": "llama_cpp_module", "ollama": "ollama_module"}


@pytest.fixture(autouse=True)
def _no_preferred_engine(monkeypatch):
    """`auto` must mean auto: a preferred engine left in the environment (or in
    a runtime override) by another test would prepend itself to every cascade."""
    from core.runtime_state import get_override, set_override

    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    # set_override returns None, so the previous value has to be read first —
    # restoring what it "returned" would clear the override for whatever ran
    # before this file.
    _prev = get_override("NEXE_MODEL_ENGINE")
    set_override("NEXE_MODEL_ENGINE", None)
    yield
    set_override("NEXE_MODEL_ENGINE", _prev)


def _state(*live):
    """An app state where exactly these engines are serviceable.

    mlx and llama_cpp need a live ``_node`` to count (B260) — a registered
    module with a dead node is precisely what the old UI table could not see.
    """
    state = SimpleNamespace(modules={}, config={})
    for name in live:
        module = MagicMock()
        module._node = object()
        state.modules[_MODULE_KEYS[name]] = module
    return state


def _backend(bid: str, *, models=None, connected=True):
    return {
        "id": bid,
        "name": bid,
        "models": models if models is not None else [{"name": "m"}],
        "active": False,
        "connected": connected,
    }


def test_auto_follows_core_cascade():
    assert resolve_engine_cascade("auto", _state("mlx", "llama_cpp", "ollama")) == [
        "mlx",
        "llama_cpp",
        "ollama",
    ]


def test_explicit_ollama_still_starts_with_ollama():
    order = resolve_engine_cascade("ollama", _state("mlx", "llama_cpp", "ollama"))
    assert order[0] == "ollama"
    assert "mlx" in order


def test_explicit_mlx_and_llamacpp_keep_their_head():
    everything = _state("mlx", "llama_cpp", "ollama")
    assert resolve_engine_cascade("mlx", everything)[0] == "mlx"
    # The alias the UI sends. The old table knew this one spelling and no other;
    # the core normalises "llamacpp", "llama-cpp" and "llama.cpp" alike.
    assert resolve_engine_cascade("llamacpp", everything)[0] == "llama_cpp"
    assert resolve_engine_cascade("llama.cpp", everything)[0] == "llama_cpp"


def test_unknown_preferred_uses_cascade_not_ollama_first():
    assert resolve_engine_cascade("whatever", _state("mlx", "llama_cpp", "ollama"))[0] == "mlx"


def test_an_engine_that_is_not_serviceable_is_not_offered():
    """What the UI table could not express: mlx present but with a dead node.

    It used to be first in the list regardless, dispatched to, and the turn fell
    through to whatever the generic handler caught."""
    state = _state("mlx", "ollama")
    state.modules["mlx_module"]._node = None
    assert resolve_engine_cascade("auto", state) == ["ollama"]


def test_an_explicit_pick_that_is_dead_falls_through_the_cascade():
    state = _state("llama_cpp", "ollama")
    assert resolve_engine_cascade("mlx", state) == ["llama_cpp", "ollama"]


def test_nothing_live_is_an_empty_cascade():
    """The caller answers 503 from this, instead of dispatching blindly."""
    assert resolve_engine_cascade("auto", _state()) == []


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
    from core.sessions import ChatSession

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
        # C4.1 (#1044): the trace `require_ui_auth` leaves behind — the principal
        # it authenticated. The door copies it onto the turn and `authorize`
        # refuses a turn without one, so a harness that stubs the auth
        # dependency has to leave the same trace. A plain dict is what
        # Starlette's `request.state` wraps.
        "app": app_mock, "state": {"principal": "harness-key"},
    })

    patches = [
        patch("core.memory_facts.helper_for", return_value=mh),
        patch("plugins.web_ui_module.api.turn_adapters.compact_session", new=AsyncMock()),
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
