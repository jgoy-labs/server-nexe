"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_fc_thread_mirror.py
Description: Gate for F-C — the mirror thread. /v1/chat/completions conversations
             must appear as a real ChatSession, readable from the same
             SessionManager the UI reads from, so a conversation started via
             the API shows up as a thread in the Tauri/mobile app too.

             Two independent things are pinned here:
             (1) the thread id: X-Session-Id wins when sent; otherwise it is
                 derived from the conversation's first USER message (not the
                 raw first element, which is often a repeated system prompt),
                 so the same conversation always maps to the same thread and
                 two different conversations never collide.
             (2) the mirror: every /v1 call overwrites the session's history
                 with what the client sent (client stays the source of
                 truth), then appends the assistant's reply once generated —
                 for the non-streaming response and for all three engines'
                 streaming generators alike.

             Drives the real generators/endpoint, not a local copy of the
             expression — a mutation that removes any of the hooks this test
             covers must turn the matching test red.
www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.sessions import SessionManager

API_KEY = "test-fc-key"


# ─── Helpers ──────────────────────────────────────────────────────────────

@pytest.fixture
def session_manager(tmp_path, monkeypatch):
    """A real SessionManager over a tmp dir — no crypto, dev-mode plaintext."""
    monkeypatch.setenv("NEXE_ENV", "development")
    return SessionManager(storage_path=str(tmp_path / "sessions"), crypto_provider=None)


def _make_app(session_manager):
    app = FastAPI()
    app.state.config = {}
    app.state.modules = {"ollama_module": MagicMock()}
    app.state.session_manager = session_manager

    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from core.endpoints.chat import router
    app.include_router(router)
    return app


class _OllamaCapture:
    """httpx.AsyncClient double: /api/tags OK, /api/chat echoes a fixed reply."""

    def __init__(self, reply: str = "adeu"):
        self.reply = reply

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *a, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"models": [{"name": "llama3.2"}]}
        return resp

    async def post(self, url, json=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"message": {"content": self.reply}, "done": True}
        return resp


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    from core.dependencies import limiter as _limiter
    _limiter.enabled = False
    yield
    _limiter.enabled = True


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
    monkeypatch.delenv("NEXE_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("NEXE_DEFAULT_MODEL", raising=False)


def _post(client, messages, session_id=None, **extra):
    headers = {"X-Api-Key": API_KEY, "Content-Type": "application/json"}
    if session_id:
        headers["X-Session-Id"] = session_id
    body = {"messages": messages, "engine": "ollama", "stream": False, "use_rag": False}
    body.update(extra)
    with patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")):
        return client.post("/chat/completions", json=body, headers=headers)


# ─── Unit: id derivation (F-C part 1) ──────────────────────────────────────

class TestDeriveSessionIdFromFirstUserMessage:
    def test_header_wins_even_with_messages(self):
        from core.endpoints.chat_engines._common import derive_session_id

        req = MagicMock()
        req.headers = {"x-session-id": "explicit-id"}
        messages = [{"role": "user", "content": "hola"}]
        assert derive_session_id(req, messages) == "explicit-id"

    def test_same_first_user_message_same_id(self):
        from core.endpoints.chat_engines._common import derive_session_id

        req = MagicMock()
        req.headers = {}
        a = derive_session_id(req, [{"role": "user", "content": "bon dia"}])
        b = derive_session_id(
            req,
            [
                {"role": "user", "content": "bon dia"},
                {"role": "assistant", "content": "hola!"},
                {"role": "user", "content": "com estàs?"},
            ],
        )
        assert a == b
        assert a.startswith("sess_")

    def test_different_first_user_message_different_id(self):
        from core.endpoints.chat_engines._common import derive_session_id

        req = MagicMock()
        req.headers = {}
        a = derive_session_id(req, [{"role": "user", "content": "bon dia"}])
        b = derive_session_id(req, [{"role": "user", "content": "bona tarda"}])
        assert a != b

    def test_system_message_is_not_the_key(self):
        """A shared/boilerplate system prompt must not collide two real
        conversations that differ only in their first USER message — the
        collision F-C exists to avoid."""
        from core.endpoints.chat_engines._common import derive_session_id

        req = MagicMock()
        req.headers = {}
        same_system = {"role": "system", "content": "You are a helpful assistant."}
        a = derive_session_id(req, [same_system, {"role": "user", "content": "bon dia"}])
        b = derive_session_id(req, [same_system, {"role": "user", "content": "bona tarda"}])
        assert a != b

    def test_pydantic_message_objects_work_too(self):
        """The raw /v1 request carries pydantic Message objects, not dicts."""
        from core.endpoints.chat_engines._common import derive_session_id
        from core.endpoints.chat_schemas import Message

        req = MagicMock()
        req.headers = {}
        got = derive_session_id(req, [Message(role="user", content="bon dia")])
        want = derive_session_id(req, [{"role": "user", "content": "bon dia"}])
        assert got == want

    def test_no_user_message_falls_back_to_api_key_hash(self):
        from core.endpoints.chat_engines._common import derive_session_id

        req = MagicMock()
        req.headers = {"x-api-key": "k"}
        assert derive_session_id(req, []) == derive_session_id(req, None)
        assert derive_session_id(req, [{"role": "system", "content": "x"}]).startswith("sess_")


# ─── Unit: mirror + persist (F-C part 2) ───────────────────────────────────

class TestMirrorV1Conversation:
    def test_writes_user_and_assistant_turns_excluding_system(self, session_manager):
        from core.endpoints.chat_engines._common import mirror_v1_conversation

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_x", [
            {"role": "system", "content": "You are Nexe."},
            {"role": "user", "content": "hola"},
        ])
        session = session_manager.get_session("sess_x")
        assert session is not None
        assert [m["role"] for m in session.messages] == ["user"]
        assert session.messages[0]["content"] == "hola"

    def test_second_call_overwrites_not_appends(self, session_manager):
        """The client resends the full history; the mirror must match it
        exactly, never accumulate duplicates turn after turn."""
        from core.endpoints.chat_engines._common import mirror_v1_conversation

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_x", [{"role": "user", "content": "hola"}])
        mirror_v1_conversation(app_state, "sess_x", [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "hola!"},
            {"role": "user", "content": "com va?"},
        ])
        session = session_manager.get_session("sess_x")
        assert [m["content"] for m in session.messages] == ["hola", "hola!", "com va?"]

    def test_persisted_to_disk(self, session_manager, tmp_path):
        from core.endpoints.chat_engines._common import mirror_v1_conversation

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_disk", [{"role": "user", "content": "hola"}])
        assert (tmp_path / "sessions" / "sess_disk.json").exists()

    def test_no_session_manager_does_not_raise(self):
        from core.endpoints.chat_engines._common import mirror_v1_conversation

        mirror_v1_conversation(MagicMock(session_manager=None), "sess_x", [{"role": "user", "content": "hi"}])
        mirror_v1_conversation(None, "sess_x", [{"role": "user", "content": "hi"}])


class TestPersistV1Turn:
    def test_appends_assistant_reply(self, session_manager):
        from core.endpoints.chat_engines._common import mirror_v1_conversation, persist_v1_turn

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_x", [{"role": "user", "content": "hola"}])
        persist_v1_turn(app_state, "sess_x", "hola, com et puc ajudar?")
        session = session_manager.get_session("sess_x")
        assert session.messages[-1]["role"] == "assistant"
        assert session.messages[-1]["content"] == "hola, com et puc ajudar?"

    def test_blank_response_is_not_persisted(self, session_manager):
        from core.endpoints.chat_engines._common import mirror_v1_conversation, persist_v1_turn

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_x", [{"role": "user", "content": "hola"}])
        persist_v1_turn(app_state, "sess_x", "   ")
        session = session_manager.get_session("sess_x")
        assert len(session.messages) == 1  # only the mirrored user turn

    def test_no_session_manager_does_not_raise(self):
        from core.endpoints.chat_engines._common import persist_v1_turn

        persist_v1_turn(MagicMock(session_manager=None), "sess_x", "hi")
        persist_v1_turn(None, "sess_x", "hi")


# ─── End to end: /v1/chat/completions mirrors a real thread ───────────────

class TestV1NonStreamingMirrorsToSession:
    def test_conversation_becomes_a_session(self, session_manager):
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)
        capture = _OllamaCapture(reply="Hola, sóc Nexe")

        with patch("httpx.AsyncClient", return_value=capture):
            resp = _post(client, [{"role": "user", "content": "Bon dia!"}])

        assert resp.status_code == 200
        sessions = session_manager.list_sessions()
        assert len(sessions) == 1
        session = session_manager.get_session(sessions[0]["id"])
        assert [m["role"] for m in session.messages] == ["user", "assistant"]
        assert session.messages[0]["content"] == "Bon dia!"
        assert session.messages[1]["content"] == "Hola, sóc Nexe"

    def test_second_turn_same_thread(self, session_manager):
        """Resending the full history keeps mapping to the same thread —
        the F-C gate: the SAME conversation, two calls, ONE session."""
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="Hola!")):
            _post(client, [{"role": "user", "content": "Bon dia!"}])
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="Molt bé, gràcies!")):
            _post(client, [
                {"role": "user", "content": "Bon dia!"},
                {"role": "assistant", "content": "Hola!"},
                {"role": "user", "content": "Com estàs?"},
            ])

        sessions = session_manager.list_sessions()
        assert len(sessions) == 1
        session = session_manager.get_session(sessions[0]["id"])
        assert [m["content"] for m in session.messages] == [
            "Bon dia!", "Hola!", "Com estàs?", "Molt bé, gràcies!",
        ]

    def test_two_different_conversations_do_not_collide(self, session_manager):
        """F-C gate: two different conversations via the API never merge into
        one thread (the old bug — an API-key hash collapsed them)."""
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-a")):
            _post(client, [{"role": "user", "content": "Explica'm el temps d'avui"}])
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-b")):
            _post(client, [{"role": "user", "content": "Recomana'm un llibre"}])

        sessions = session_manager.list_sessions()
        assert len(sessions) == 2
        ids = {s["id"] for s in sessions}
        assert len(ids) == 2

    def test_explicit_session_id_header_is_honoured(self, session_manager):
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok")):
            _post(client, [{"role": "user", "content": "hola"}], session_id="my-thread")

        session = session_manager.get_session("my-thread")
        assert session is not None
        assert session.messages[0]["content"] == "hola"


# ─── Collision avoidance (2026-08-31 regression, C4 + C5) ─────────────────
#
# The CHANGELOG and derive_session_id's own docstring claimed "two different
# conversations never merge" — they did, and destructively (the first one's
# turns disappeared). These pin the fix: a candidate id whose existing
# session is NOT a coherent continuation of the incoming turns is diverted
# to "<id>_alt" instead of being overwritten.

class TestSessionCollisionAvoidance:
    def test_same_first_message_different_conversations_get_different_ids(self, session_manager):
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-a1")):
            _post(client, [{"role": "user", "content": "Hola"}])
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-b1")):
            _post(client, [{"role": "user", "content": "Hola"}])

        sessions = session_manager.list_sessions()
        assert len(sessions) == 2, (
            "two unrelated conversations sharing the same first message must "
            "never merge into one session"
        )

    def test_first_conversation_is_not_corrupted_by_the_second(self, session_manager):
        """The concrete failure mode: conv A's exclusive turn used to
        disappear once conv B (same first message) arrived."""
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-a1")):
            _post(client, [{"role": "user", "content": "Hola"}])
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-b1")):
            _post(client, [{"role": "user", "content": "Hola"}])

        sessions = session_manager.list_sessions()
        contents = [
            [m["content"] for m in session_manager.get_session(s["id"]).messages]
            for s in sessions
        ]
        assert ["Hola", "ok-a1"] in contents
        assert ["Hola", "ok-b1"] in contents

    def test_diverted_conversation_keeps_its_own_stable_thread(self, session_manager):
        """The _alt id, once assigned, stays the SAME thread across that
        conversation's own further turns — not a new one every time."""
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-a1")):
            _post(client, [{"role": "user", "content": "Hola"}])
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-b1")):
            _post(client, [{"role": "user", "content": "Hola"}])
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok-b2")):
            _post(client, [
                {"role": "user", "content": "Hola"},
                {"role": "assistant", "content": "ok-b1"},
                {"role": "user", "content": "els meus resultats mèdics"},
            ])

        sessions = session_manager.list_sessions()
        assert len(sessions) == 2, "the diverted conversation must grow on its OWN thread, not open a third"
        contents = [
            [m["content"] for m in session_manager.get_session(s["id"]).messages]
            for s in sessions
        ]
        assert ["Hola", "ok-a1"] in contents, "conversation A must stay untouched"
        assert ["Hola", "ok-b1", "els meus resultats mèdics", "ok-b2"] in contents, (
            "conversation B must keep growing as one thread on its diverted id"
        )

    def test_three_way_collision_resolved_via_chain(self, session_manager):
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)
        for reply in ("ok-1", "ok-2", "ok-3"):
            with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply=reply)):
                _post(client, [{"role": "user", "content": "Hola"}])

        sessions = session_manager.list_sessions()
        assert len(sessions) == 3, "three unrelated 'Hola' conversations must get three distinct threads"


class TestExplicitSessionIdCollisionAvoidance:
    def test_explicit_session_id_does_not_overwrite_unrelated_session(self, session_manager):
        """C5: an X-Session-Id borrowed from another (e.g. UI/Tauri) session
        with more history than the incoming request must not destroy it."""
        ui_session = session_manager.get_or_create_session("ui-thread")
        for role, content in [
            ("user", "hola"), ("assistant", "hola!"),
            ("user", "com estàs"), ("assistant", "bé"),
            ("user", "explica'm algo"), ("assistant", "..."),
        ]:
            ui_session.add_message(role, content)
        session_manager.save_session("ui-thread")

        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok")):
            resp = _post(
                client, [{"role": "user", "content": "un missatge no relacionat"}],
                session_id="ui-thread",
            )

        assert resp.status_code == 200, "the collision check must never break the chat response"
        original = session_manager.get_session("ui-thread")
        assert len(original.messages) == 6, "the unrelated session must not be overwritten"
        diverted = session_manager.get_session("ui-thread_alt")
        assert diverted is not None
        assert diverted.messages[0]["content"] == "un missatge no relacionat"

    def test_explicit_session_id_multi_turn_stays_stable(self, session_manager):
        """Zero-regression: the normal case (same X-Session-Id, history
        growing coherently turn after turn, as a real client does) must
        NEVER be diverted."""
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok1")):
            _post(client, [{"role": "user", "content": "hola"}], session_id="my-thread")
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok2")):
            _post(client, [
                {"role": "user", "content": "hola"},
                {"role": "assistant", "content": "ok1"},
                {"role": "user", "content": "com va"},
            ], session_id="my-thread")

        assert session_manager.get_session("my-thread_alt") is None
        session = session_manager.get_session("my-thread")
        assert [m["content"] for m in session.messages] == ["hola", "ok1", "com va", "ok2"]


class TestEmptyContentTurns:
    """A turn with empty content must be invisible to BOTH the mirror and the
    collision guard, and a request with nothing storable must not touch any
    thread at all.

    The mirror has always dropped empty turns; the guard used to count them,
    so the two lists lined up differently and a legitimate continuation was
    judged a collision. A client sends an empty turn whenever a generation
    produced no text, and a tool-calling client must send "" rather than null
    because Message.content is a required str (null is a 422).
    """

    def test_continuation_with_an_empty_turn_stays_one_thread(self, session_manager):
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        # Turn 1: the history already carries a turn that produced no text.
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="Fa 18 graus.")):
            _post(client, [
                {"role": "user", "content": "quin temps fa?"},
                {"role": "assistant", "content": ""},
            ])
        # Turn 2: the same conversation continuing — the client resends its
        # whole history, empty turn included, plus the new question.
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="Demà plou.")):
            _post(client, [
                {"role": "user", "content": "quin temps fa?"},
                {"role": "assistant", "content": ""},
                {"role": "assistant", "content": "Fa 18 graus."},
                {"role": "user", "content": "i demà?"},
            ])

        sessions = session_manager.list_sessions()
        assert len(sessions) == 1, (
            "the empty turn shifted the comparison: a legitimate continuation "
            f"was diverted to an _alt thread (got {[s['id'] for s in sessions]})"
        )
        contents = [m["content"] for m in session_manager.get_session(sessions[0]["id"]).messages]
        assert contents == ["quin temps fa?", "Fa 18 graus.", "i demà?", "Demà plou."]

    def test_a_request_with_nothing_storable_does_not_damage_a_borrowed_thread(self, session_manager):
        """Nothing storable + a borrowed X-Session-Id must leave that thread
        exactly as it was: not overwritten (the mirror declines to write an
        empty history) and not appended to (the guard diverts, so the reply
        lands elsewhere).

        "Elsewhere" is not nowhere, and the second half of this test says so
        out loud: persist_v1_turn has no way of knowing the mirror declined,
        so the reply still creates a thread — an `_alt` one holding a single
        assistant turn and no user turn. That is pre-existing behaviour (it
        reproduces identically on the parent commit), it is filed, and it is
        asserted here rather than left for a green test to hide.
        """
        ui_session = session_manager.get_or_create_session("ui-thread")
        for role, content in [
            ("user", "hola"), ("assistant", "hola!"),
            ("user", "com estàs"), ("assistant", "bé"),
            ("user", "explica'm algo"), ("assistant", "..."),
        ]:
            ui_session.add_message(role, content)
        session_manager.save_session("ui-thread")
        before = [m["content"] for m in session_manager.get_session("ui-thread").messages]

        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok")):
            resp = _post(client, [{"role": "user", "content": ""}], session_id="ui-thread")

        assert resp.status_code == 200, "the guard must never break the chat response"
        after = [m["content"] for m in session_manager.get_session("ui-thread").messages]
        assert after == before, "an unrelated thread was modified by a request with no content"

        # Known and filed: the reply still lands somewhere. Pinned so that a
        # future fix shows up here as a failing assertion instead of passing
        # unnoticed.
        diverted = session_manager.get_session("ui-thread_alt")
        assert diverted is not None, (
            "expected the reply to be diverted to _alt (pre-existing: persist_v1_turn "
            "cannot know the mirror declined). If this is now None the ghost thread is "
            "fixed — update this test."
        )
        assert [m["role"] for m in diverted.messages] == ["assistant"], (
            "the diverted thread holds an orphan assistant turn and no user turn"
        )

    def test_nothing_storable_does_not_wipe_the_api_key_fallback_thread(self, session_manager):
        """The mirror must decline to write an empty history on its own, not
        rely on the collision guard having vetted the id.

        This is the one id the guard never checks by design: when there is no
        usable first user message, derive_session_id falls back to the API-key
        hash. A request with nothing storable lands there unvetted, so if the
        mirror wrote its empty result it would erase whatever that key's
        thread already held.
        """
        client = TestClient(_make_app(session_manager), raise_server_exceptions=False)

        # Empty first user turn -> no key to derive from -> API-key-hash id.
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok1")):
            _post(client, [
                {"role": "user", "content": ""},
                {"role": "user", "content": "hola"},
            ])
        sessions = session_manager.list_sessions()
        assert len(sessions) == 1
        fallback_id = sessions[0]["id"]
        assert "hola" in [m["content"] for m in session_manager.get_session(fallback_id).messages]

        # Same API key, nothing storable at all: must not erase the above.
        with patch("httpx.AsyncClient", return_value=_OllamaCapture(reply="ok2")):
            _post(client, [{"role": "user", "content": ""}])

        contents = [m["content"] for m in session_manager.get_session(fallback_id).messages]
        assert "hola" in contents, (
            f"the fallback thread was wiped by a request with nothing to mirror (got {contents})"
        )
        # What this test does NOT claim: that the thread is left alone. The
        # API-key-hash id never reaches the collision guard, so the reply is
        # appended here — an assistant turn with no user turn before it. The
        # erasure is fixed; the ghost turn is filed. Asserted so the gap is
        # visible in the test, not just in a finding.
        assert contents[-1] == "ok2", (
            "pre-existing: the reply is appended to the unvetted fallback thread. "
            "If this now fails the ghost turn is fixed — update this test."
        )


# ─── End to end: streaming generators persist their own turn ──────────────

class TestStreamingEnginesMirrorToSession:
    def _collect(self, gen):
        async def _run():
            return [chunk async for chunk in gen]
        return asyncio.run(_run())

    def test_mlx_stream_persists_assistant_turn(self, session_manager):
        from core.endpoints.chat_engines.mlx import _mlx_stream_generator
        from core.endpoints.chat_engines._common import mirror_v1_conversation

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_mlx", [{"role": "user", "content": "hola"}])

        async def fake_chat(**kwargs):
            cb = kwargs.get("stream_callback")
            if cb:
                cb("Hola des de MLX")
            return {"response": "Hola des de MLX", "tokens": 3}

        mock_mlx = MagicMock()
        mock_mlx.chat = fake_chat

        self._collect(_mlx_stream_generator(
            mock_mlx, [{"role": "user", "content": "hola"}], "system", "mlx-local",
            app_state=app_state, user_msg="hola", session_id="sess_mlx",
        ))

        session = session_manager.get_session("sess_mlx")
        assert session.messages[-1]["role"] == "assistant"
        assert session.messages[-1]["content"] == "Hola des de MLX"

    def test_llama_cpp_stream_persists_assistant_turn(self, session_manager):
        from core.endpoints.chat_engines.llama_cpp import _llama_cpp_stream_generator
        from core.endpoints.chat_engines._common import mirror_v1_conversation

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_llama", [{"role": "user", "content": "hola"}])

        async def fake_chat(**kwargs):
            cb = kwargs.get("stream_callback")
            if cb:
                cb("Hola des de llama.cpp")
            return {"response": "Hola des de llama.cpp", "tokens": 4}

        mock_llama = MagicMock()
        mock_llama.chat = fake_chat

        self._collect(_llama_cpp_stream_generator(
            mock_llama, [{"role": "user", "content": "hola"}], "system", "llama-cpp-local",
            app_state=app_state, user_msg="hola", session_id="sess_llama",
        ))

        session = session_manager.get_session("sess_llama")
        assert session.messages[-1]["role"] == "assistant"
        assert session.messages[-1]["content"] == "Hola des de llama.cpp"

    def test_ollama_stream_persists_assistant_turn(self, session_manager):
        from core.endpoints.chat_engines.ollama import _ollama_stream_generator
        from core.endpoints.chat_engines._common import mirror_v1_conversation

        app_state = MagicMock(session_manager=session_manager)
        mirror_v1_conversation(app_state, "sess_ollama", [{"role": "user", "content": "hola"}])

        ollama_lines = [
            json.dumps({"message": {"content": "Hola "}, "done": False}),
            json.dumps({"message": {"content": "des de Ollama"}, "done": True, "done_reason": "stop"}),
        ]

        async def _aiter():
            for line in ollama_lines:
                yield line

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=_aiter())

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)

        with patch("httpx.AsyncClient", return_value=mock_client):
            self._collect(_ollama_stream_generator(
                "http://localhost/api/chat", {"model": "test", "messages": []},
                app_state=app_state, user_msg="hola", session_id="sess_ollama",
            ))

        session = session_manager.get_session("sess_ollama")
        assert session.messages[-1]["role"] == "assistant"
        assert session.messages[-1]["content"] == "Hola des de Ollama"
