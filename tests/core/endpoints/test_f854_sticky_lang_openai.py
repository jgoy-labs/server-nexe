"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_f854_sticky_lang_openai.py
Description: #854 — the OpenAI-compatible route recomputed the reply language on
             EVERY request, so a short off-language ack flipped the whole system
             prompt (the CRITICAL directive sits at token 0) mid-session and
             invalidated the prefix cache the route itself keys by session_id
             (new trie node on MLX, _destroy + GGUF reload on llama.cpp).

             Same policy as #850 on the web UI route (commit 8f67d6a6): the
             fallback is returned but never seeded, the switch gate measures the
             NATURAL text, and a switch needs two consecutive detections.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.endpoints.chat as ce
import plugins.web_ui_module.api.routes_chat as rc

API_KEY = "test-f854-key"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Module-level caches must not leak between tests (or into other files):
    the #854 language LRU, and the Ollama /api/tags cache (a real local Ollama
    warms it and the mocked model list would never be consulted). The model
    env vars go too — on a developer machine they name real local models that
    the mocked /api/tags does not list (404 instead of a chat)."""
    for _var in ("NEXE_MODEL_ENGINE", "NEXE_OLLAMA_MODEL", "NEXE_DEFAULT_MODEL"):
        monkeypatch.delenv(_var, raising=False)
    ce._reset_session_lang_state()
    ce._ollama_tags_cache["models"] = None
    ce._ollama_tags_cache["ts"] = 0.0
    yield
    ce._reset_session_lang_state()
    ce._ollama_tags_cache["models"] = None
    ce._ollama_tags_cache["ts"] = 0.0


# ── Policy: identical rules to #850, with detection mocked (deterministic) ───

class TestStickyLangPolicy:

    def test_first_real_detection_seeds_the_session(self, monkeypatch):
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        assert ce._resolve_request_lang("s1", "una frase prou llarga en català") == "ca"
        # second turn, no detection at all → the seeded language holds
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: None)
        assert ce._resolve_request_lang("s1", "ok") == "ca"

    def test_fallback_is_returned_but_never_seeded(self, monkeypatch):
        """A guess must not lock the session before the first real detection."""
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: None)
        monkeypatch.setenv("NEXE_LANG", "en")
        assert ce._resolve_request_lang("s1", "ok") == "en"
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        assert ce._resolve_request_lang("s1", "una frase llarga en català") == "ca"

    def test_degenerate_nexe_lang_still_returns_en(self, monkeypatch):
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: None)
        monkeypatch.setenv("NEXE_LANG", "-es")
        assert ce._resolve_request_lang("s1", "ok") == "en"

    def test_short_ack_never_flips(self, monkeypatch):
        """The #854 case: NEXE_LANG=en, Catalan session, a 'gràcies!' ack."""
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        assert ce._resolve_request_lang("s1", "hola, com estàs avui?") == "ca"
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "en")
        assert ce._resolve_request_lang("s1", "thanks a lot") == "ca"

    def test_url_padded_ack_never_flips(self, monkeypatch):
        """The gate measures natural text: a long link is not language."""
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        ce._resolve_request_lang("s1", "hola, com estàs avui?")
        msg = "thanks mate https://github.com/jgoy-labs/server-nexe/issues/1"
        assert len(msg) >= ce._STICKY_LANG_MIN_SWITCH_CHARS  # the RAW length lies
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "en")
        assert ce._resolve_request_lang("s1", msg) == "ca"

    def test_single_long_foreign_turn_does_not_flip(self, monkeypatch):
        """One pasted English traceback must not invalidate the prefix."""
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        ce._resolve_request_lang("s1", "hola, com estàs avui?")
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "en")
        trace = "TypeError: cannot read property of undefined at Object.render at main"
        assert ce._resolve_request_lang("s1", trace) == "ca"

    def test_two_consecutive_detections_flip(self, monkeypatch):
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        ce._resolve_request_lang("s1", "hola, com estàs avui?")
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "en")
        assert ce._resolve_request_lang("s1", "can we please switch to english now?") == "ca"
        assert ce._resolve_request_lang("s1", "yes, from now on let's continue in english") == "en"

    def test_reaffirming_sticky_clears_the_candidate(self, monkeypatch):
        detections = iter(["ca", "en", "ca", "en"])
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: next(detections))
        long_msg = "aquesta és una frase prou llarga per superar el llindar del gate"
        ce._resolve_request_lang("s1", long_msg)          # ca → seeds
        ce._resolve_request_lang("s1", long_msg)          # en → candidate
        ce._resolve_request_lang("s1", long_msg)          # ca → candidate dropped
        assert ce._resolve_request_lang("s1", long_msg) == "ca"  # en again → no flip

    def test_sessions_are_independent(self, monkeypatch):
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        assert ce._resolve_request_lang("s1", "hola, com estàs avui?") == "ca"
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "de")
        assert ce._resolve_request_lang("s2", "hallo, wie geht es dir heute?") == "de"
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: None)
        assert ce._resolve_request_lang("s1", "ok") == "ca"
        assert ce._resolve_request_lang("s2", "ok") == "de"


class TestStickyLangMemoryBound:
    """A per-session map on a long-running server must not grow forever."""

    def test_lru_evicts_the_oldest_session(self, monkeypatch):
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        for i in range(ce._SESSION_LANG_MAX + 10):
            ce._resolve_request_lang(f"s{i}", "hola, com estàs avui?")
        assert len(ce._SESSION_LANG) == ce._SESSION_LANG_MAX
        assert "s0" not in ce._SESSION_LANG
        assert f"s{ce._SESSION_LANG_MAX + 9}" in ce._SESSION_LANG

    def test_touching_a_session_keeps_it_alive(self, monkeypatch):
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: "ca")
        ce._resolve_request_lang("keep-me", "hola, com estàs avui?")
        for i in range(ce._SESSION_LANG_MAX - 1):
            ce._resolve_request_lang(f"s{i}", "hola, com estàs avui?")
            ce._resolve_request_lang("keep-me", "hola, com estàs avui?")
        ce._resolve_request_lang("overflow", "hola, com estàs avui?")
        assert "keep-me" in ce._SESSION_LANG


class TestPolicyParityWithWebUIRoute:
    """Anti-drift: two implementations, one policy (#850/#854).

    The web UI keeps its state on the ChatSession; this route has no session
    object and keys an LRU by the derived session_id. The DECISIONS must be
    identical — if either side is tweaked in isolation, this goes red.
    """

    def test_same_threshold_constant(self):
        assert ce._STICKY_LANG_MIN_SWITCH_CHARS == rc._STICKY_LANG_MIN_SWITCH_CHARS

    def test_same_decisions_over_a_realistic_conversation(self, monkeypatch):
        from types import SimpleNamespace

        turns = [
            ("hola, què em pots explicar del temps d'avui?", "ca"),
            ("gràcies!", None),                                    # short ack
            ("thanks a lot", "en"),                                # short, detected
            ("TypeError: cannot read property of undefined at x", "en"),  # candidate
            ("i encara una altra pregunta ben llarga en català", "ca"),   # drops it
            ("can we please switch to english now?", "en"),        # candidate
            ("yes, from now on let's continue in english", "en"),  # flip
            ("and one more question in english, please", "en"),
        ]
        detections = iter([d for _, d in turns])
        monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: next(detections))
        mine = [ce._resolve_request_lang("s1", text) for text, _ in turns]

        detections2 = iter([d for _, d in turns])
        monkeypatch.setattr(rc, "_detect_lang_or_none", lambda m: next(detections2))
        session = SimpleNamespace(lang=None, lang_pending=None)
        theirs = [rc._resolve_session_lang(session, text) for text, _ in turns]

        assert mine == theirs, (
            f"#854 policy drifted from #850: {mine} != {theirs}"
        )


# ── End to end: the system prompt must not flip between turns ───────────────

def _make_app():
    app = FastAPI()
    app.state.config = {"personality": {"prompt": {
        "ca_full": "PROMPT-CA", "en_full": "PROMPT-EN",
    }}}
    app.state.modules = {"ollama_module": MagicMock()}

    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(ce.router)
    return app


class _OllamaCapture:
    """httpx.AsyncClient double that records every /api/chat payload."""

    def __init__(self):
        self.payloads = []

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
        self.payloads.append(json)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"message": {"content": "ok"}, "done": True}
        return resp


@pytest.mark.usefixtures("_clean_state")
class TestSystemPromptStableAcrossTurns:

    def _post(self, client, capture, text, session_id="sess-854"):
        with patch("httpx.AsyncClient", return_value=capture), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")):
            return client.post(
                "/chat/completions",
                json={
                    "messages": [{"role": "user", "content": text}],
                    "engine": "ollama", "stream": False, "use_rag": False,
                },
                headers={
                    "X-Api-Key": API_KEY,
                    "X-Session-Id": session_id,
                    "Content-Type": "application/json",
                },
            )

    def test_short_ack_does_not_flip_the_system_prompt(self, monkeypatch):
        """#854 live shape: NEXE_LANG=en + Catalan conversation + 'gràcies!'.

        Pre-fix the ack fell below the detection floor, resolved to the env
        fallback 'en' and rewrote the system from token 0.
        """
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
        monkeypatch.setenv("NEXE_LANG", "en")
        capture = _OllamaCapture()
        client = TestClient(_make_app(), raise_server_exceptions=False)

        r1 = self._post(client, capture, "hola, què em pots explicar del temps d'avui?")
        r2 = self._post(client, capture, "gràcies!")
        assert r1.status_code == 200 and r2.status_code == 200

        systems = [
            next(m["content"] for m in p["messages"] if m["role"] == "system")
            for p in capture.payloads
        ]
        assert len(systems) == 2
        assert systems[0] == systems[1], (
            "#854: a short ack rewrote the system prompt mid-session"
        )
        assert "PROMPT-CA" in systems[0], "the Catalan turn must drive the prompt"

    def test_different_sessions_keep_their_own_language(self, monkeypatch):
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
        monkeypatch.setenv("NEXE_LANG", "en")
        capture = _OllamaCapture()
        client = TestClient(_make_app(), raise_server_exceptions=False)

        self._post(client, capture, "hola, què em pots explicar del temps d'avui?",
                   session_id="sess-ca")
        self._post(client, capture, "hello, could you explain today's weather?",
                   session_id="sess-en")
        self._post(client, capture, "gràcies!", session_id="sess-ca")
        self._post(client, capture, "thanks!", session_id="sess-en")

        systems = [
            next(m["content"] for m in p["messages"] if m["role"] == "system")
            for p in capture.payloads
        ]
        assert systems[0] == systems[2], "the Catalan session flipped"
        assert systems[1] == systems[3], "the English session flipped"
        assert systems[0] != systems[1], "both sessions collapsed onto one language"

    def test_session_key_falls_back_to_the_api_key_without_the_header(self, monkeypatch):
        """No X-Session-Id: the key is derived exactly like the prefix cache
        the engines use (derive_session_id), so stickiness and cache agree."""
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
        monkeypatch.setenv("NEXE_LANG", "en")
        capture = _OllamaCapture()
        client = TestClient(_make_app(), raise_server_exceptions=False)

        with patch("httpx.AsyncClient", return_value=capture), \
             patch("memory.memory.api.v1.get_memory_api", side_effect=Exception("no memory")):
            for text in ("hola, què em pots explicar del temps d'avui?", "gràcies!"):
                client.post(
                    "/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": text}],
                        "engine": "ollama", "stream": False, "use_rag": False,
                    },
                    headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
                )

        systems = [
            next(m["content"] for m in p["messages"] if m["role"] == "system")
            for p in capture.payloads
        ]
        assert len(systems) == 2 and systems[0] == systems[1]
        assert len(ce._SESSION_LANG) == 1
        assert next(iter(ce._SESSION_LANG)).startswith("sess_")


def test_env_default_still_applies_to_a_brand_new_session(monkeypatch):
    """No regression: a first turn with no detectable language still follows
    NEXE_LANG (the documented behaviour of the route)."""
    monkeypatch.setattr(ce, "_detect_lang_or_none", lambda m: None)
    monkeypatch.setenv("NEXE_LANG", "es")
    ce._reset_session_lang_state()
    assert ce._resolve_request_lang("brand-new", "ok") == "es"
    assert os.getenv("NEXE_LANG") == "es"
