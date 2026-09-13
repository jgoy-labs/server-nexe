"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/_common.py
Description: Shared helpers for engine forwarding (MLX, Llama.cpp).

Extracts duplicated logic: message parsing, session ID derivation,
OpenAI response formatting, and Ollama fallback.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request

from ..chat_sanitization import _sanitize_sse_token

logger = logging.getLogger(__name__)


def _msg_field(m: Any, field: str) -> Optional[str]:
    """Read ``field`` off a message that is either a dict or a pydantic Message.

    ``/v1`` messages arrive as pydantic ``Message`` objects (attribute access);
    engine-internal message lists are plain dicts (``.get``). F-C derives the
    thread id from the client's raw request, so it must accept both shapes.
    """
    return m.get(field) if isinstance(m, dict) else getattr(m, field, None)


def extract_last_user_msg(messages: List[Dict]) -> Optional[str]:
    """Return the content of the last user message, or None."""
    return next(
        (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
        None,
    )


def extract_first_user_msg(messages) -> Optional[str]:
    """Return the content of the FIRST user message, or None (F-C).

    Deliberately the first *user* message, not the first element of the list:
    the first element is very often a ``system`` message, and clients tend to
    reuse the same system prompt across otherwise-unrelated conversations —
    keying on it would collide different conversations into one thread, the
    opposite of what F-C fixes.
    """
    if not messages:
        return None
    for m in messages:
        if _msg_field(m, "role") == "user":
            return _msg_field(m, "content")
    return None


def separate_messages(messages: List[Dict]) -> Tuple[str, List[Dict]]:
    """Split messages into (system_msg, user_messages).

    System messages are concatenated into a single string; all other
    messages are returned unchanged in order.
    """
    system_msg = ""
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_msg = msg.get("content", "")
        else:
            user_messages.append(msg)
    return system_msg, user_messages


def _stripped_turns(messages) -> List[Tuple[str, str]]:
    """(role, content) of the user/assistant turns that carry content — the
    shape mirror_v1_conversation persists to session.messages, so it is the
    only thing comparable between a raw /v1 request and a saved ChatSession.

    Empty content is skipped on BOTH sides, and that is the whole point: the
    mirror is built from this same function, so a turn it drops can never be
    counted here. Counting one here that the mirror discards shifts every
    later turn by one position, and _is_coherent_continuation compares by
    position — a legitimate continuation would then be judged a collision and
    diverted to an "_alt" id on every single turn. A client sends an empty
    turn whenever a generation produced no text, and a tool-calling client
    must send "" (not null) because Message.content is a required str.
    """
    return [
        (role, content)
        for role, content in (
            (_msg_field(m, "role"), _msg_field(m, "content")) for m in (messages or [])
        )
        if role in ("user", "assistant") and content
    ]


def _is_coherent_continuation(existing: List[Tuple[str, str]], incoming: List[Tuple[str, str]]) -> bool:
    """True if ``incoming`` can be the SAME conversation continuing a session
    that already holds ``existing`` (F-C collision guard).

    F-C's contract is that the client resends the full history every call,
    so a real continuation is always at least as long as what is already
    saved, and matches it turn-for-turn over the overlap. An empty
    ``existing`` (a session just created) is trivially coherent — there is
    nothing yet to compare against.
    """
    if not existing:
        return True
    if len(incoming) < len(existing):
        return False
    return all(e == i for e, i in zip(existing, incoming[: len(existing)]))


_COLLISION_SUFFIX = "_alt"
_MAX_SESSION_ID_PROBES = 5


def _resolve_mirror_session_id(app_state: Any, candidate_id: str, incoming_turns: List[Tuple[str, str]]) -> str:
    """Find the session id F-C should actually mirror this turn into.

    Walks candidate_id, candidate_id_alt, candidate_id_alt_alt... and stops
    at the first one that either does not exist yet, or is already a
    coherent continuation of ``incoming_turns`` — i.e. the first one this
    call actually has permission to overwrite.

    Two different conversations that land on the same candidate_id (same
    first user message, or an ``X-Session-Id`` borrowed from another
    conversation) must never merge or clobber each other; each gets its own
    ``_alt`` id, derived the same way every time, so the "diverted"
    conversation keeps growing as ONE thread from here on.

    An EMPTY ``incoming_turns`` is checked like any other (it used to
    short-circuit here): a request with nothing storable — every turn empty,
    or system-only — is not a continuation of a thread that already holds
    turns, so _is_coherent_continuation rejects it on length and it diverts.
    Skipping the check instead handed a borrowed ``X-Session-Id`` straight
    through, and persist_v1_turn (which has no way of knowing the mirror
    declined to write) would then append this turn's reply to that unrelated
    conversation.

    That protection reaches only the ids that arrive here, which means only
    the ones derived from a header or a first user message. When there is no
    usable first user message and no header, derive_session_id returns the
    API-key hash WITHOUT calling this function, so a request with nothing
    storable still lands unchecked on that thread and persist_v1_turn still
    appends its reply there. Filed, not fixed here: the clean cure is for a
    request with nothing to mirror to carry no session id at all, and the id
    also feeds language and engine stickiness.

    Best-effort: any failure inspecting session storage (no session_manager,
    a simulated Request in tests, corrupted state) falls back to
    candidate_id unchanged — this check must never be the reason a chat
    request fails.
    """
    try:
        session_mgr = getattr(app_state, "session_manager", None)
        if session_mgr is None:
            return candidate_id
        probe = candidate_id
        for _ in range(_MAX_SESSION_ID_PROBES):
            existing_session = session_mgr.get_session(probe)
            existing_turns = _stripped_turns(existing_session.messages) if existing_session else []
            if not existing_session or _is_coherent_continuation(existing_turns, incoming_turns):
                if probe != candidate_id:
                    logger.warning(
                        "F-C: session_id %s collided with an unrelated conversation; "
                        "mirroring into %s instead", candidate_id, probe,
                    )
                return probe
            probe = f"{probe}{_COLLISION_SUFFIX}"
        logger.warning(
            "F-C: session_id %s collided %d times in a row (rare N-way collision); "
            "using %s anyway", candidate_id, _MAX_SESSION_ID_PROBES, probe,
        )
        return probe
    except Exception as e:
        logger.error("F-C: collision check failed for %s, using it unchanged: %s", candidate_id, e)
        return candidate_id


def derive_session_id(req: Request, messages=None) -> str:
    """Derive the thread id for this conversation (F-C).

    ``X-Session-Id`` wins when the client sends it. Otherwise the id is
    derived from the conversation's first USER message: since an OpenAI
    client resends the full history on every call, the first message stays
    constant while a conversation grows, so repeated calls map to the same
    thread — and two different conversations (even from the same API key,
    the old bug) do not collide.

    Either way, the candidate id is checked against what is actually saved
    under it (:func:`_resolve_mirror_session_id`): a client that reuses the
    same first message across unrelated conversations (a fixed greeting, an
    agent framework's constant opening prompt) or sends an ``X-Session-Id``
    that belongs to a different, longer conversation (e.g. one open in the
    UI/Tauri) is diverted to a ``_alt`` id instead of overwriting it. The
    one residual, accepted case: two unrelated conversations sharing the
    same first message are indistinguishable in the single instant before
    either has a second turn — it self-corrects as soon as either one's
    second turn (almost never byte-identical) arrives.

    Known limit (accepted, Jordi 31/08): a client that truncates its own
    history (sliding window) changes the first message and starts a new
    thread. The cost is one extra thread in the list, never a merged or
    corrupted conversation. A client that wants a stable id regardless
    sends ``X-Session-Id``, which always wins (subject to the same
    collision check above).

    Falls back to the API-key hash only when there is no first user message
    to key on (e.g. an empty or system-only ``messages`` list) — the
    pre-F-C behaviour, kept as the last resort rather than colliding every
    message-less caller into one thread. This fallback is NOT subject to
    the collision check: it is the pre-existing, accepted one-thread-per-key
    degenerate case.
    """
    header = req.headers.get("x-session-id")
    if header:
        candidate = header
    else:
        first_user_msg = extract_first_user_msg(messages)
        if not first_user_msg:
            _api_key = (req.headers.get("x-api-key") or req.headers.get("authorization", "")).encode()
            return f"sess_{hashlib.sha256(_api_key).hexdigest()[:16]}"
        candidate = f"sess_{hashlib.sha256(first_user_msg.encode('utf-8')).hexdigest()[:16]}"

    app_state = getattr(getattr(req, "app", None), "state", None)
    return _resolve_mirror_session_id(app_state, candidate, _stripped_turns(messages))


def mirror_v1_conversation(app_state: Any, session_id: str, messages) -> None:
    """Overwrite the mirrored session's history with what the API client sent (F-C).

    ``/v1`` is stateless: the client resends the full conversation on every
    call, and IS the source of truth. This makes the session a read mirror
    rebuilt from that history each time — never a second source that could
    drift from what the client believes the conversation is. System messages
    are not stored, matching the UI session convention (the system prompt is
    built at generation time, not persisted as a turn), and neither are turns
    with empty content — :func:`_stripped_turns` decides both, so what is
    written here and what the collision guard compares can never drift apart.

    ``session_id`` is expected to already have passed the collision check in
    :func:`derive_session_id`. Do not call this with a session_id from
    anywhere else: for an id that did pass, this overwrites whatever is there
    without asking again. The one thing it decides for itself is the empty
    case below — the collision check does not see every id (see
    :func:`_resolve_mirror_session_id`), so refusing to write an empty history
    cannot be delegated upstream.

    Best-effort: a session write must never break the chat response.
    """
    if not app_state or not session_id or not messages:
        return
    try:
        session_mgr = getattr(app_state, "session_manager", None)
        if session_mgr is None:
            # Not a normal state: the lifespan exposes the manager on app.state
            # (`_expose_session_manager`). Say so — this exact silence hid, from
            # 31/08 to 06/09/2026, that no /v1 thread was reaching disk.
            logger.warning("F-C: no session_manager on app state — /v1 thread %s not mirrored", session_id)
            return
        turns = _stripped_turns(messages)
        if not turns:
            # Nothing storable in this request (every turn empty, or only
            # system turns): a mirror of nothing must not erase a thread that
            # already exists. The collision guard covers most ids, but not
            # all — derive_session_id's API-key-hash fallback is documented as
            # never collision-checked, and a request with no usable first user
            # message lands exactly there. Returning also avoids creating an
            # empty session for a request with no content.
            return
        session = session_mgr.get_or_create_session(session_id)
        now = datetime.now(timezone.utc).isoformat()
        session.messages = [
            {"role": role, "content": content, "timestamp": now} for role, content in turns
        ]
        session_mgr.save_session(session_id)
    except Exception as e:
        logger.error("F-C: failed to mirror /v1 conversation into session %s: %s", session_id, e)


def persist_v1_turn(app_state: Any, session_id: str, response_text: str, *, partial: bool = False) -> None:
    """Append the assistant's reply to the mirrored session and save it (F-C).

    Called once the full reply text is known — after the non-streaming
    response returns, or at the end of a streaming generator. Best-effort:
    same policy as :func:`mirror_v1_conversation`, and as the pre-F-A
    background memory save this replaces functionally.

    `partial` (#1040, C2.4): the stream errored mid-generation and this is
    whatever reached the client before that — the caller (the MLX/llama.cpp
    stream generators) still calls this instead of dropping the text, so an
    interrupted /v1 reply is not silently lost from the mirrored session.
    """
    if not app_state or not session_id or not response_text or not response_text.strip():
        return
    try:
        session_mgr = getattr(app_state, "session_manager", None)
        if session_mgr is None:
            logger.warning("F-C: no session_manager on app state — /v1 assistant turn for %s not persisted", session_id)
            return
        session = session_mgr.get_or_create_session(session_id)
        session.add_message("assistant", response_text, partial=partial)
        session_mgr.save_session(session_id)
    except Exception as e:
        logger.error("F-C: failed to persist /v1 assistant turn to session %s: %s", session_id, e)


def resolve_loaded_model_name(module, fallback: str) -> str:
    """Return the basename of the model actually loaded by a single-model engine.

    MLX and llama.cpp run one fixed model (NEXE_MLX_MODEL / NEXE_LLAMA_CPP_MODEL)
    and ignore the per-request ``model`` field. Echoing ``request.model`` back
    would lie about which model answered (B075-C3): a client asking for
    ``"gpt-4"`` would see ``"gpt-4"`` while a local Qwen/Gemma actually ran.

    This returns the real loaded model's *basename* — never the absolute
    ``model_path``, which leaks the home directory (see the warnings in each
    engine's ``config.py``). When no model is loaded (e.g. ``_node`` is ``None``
    pre-onboarding) it falls back to the stable engine literal, matching the
    previous behaviour for the unconfigured case.
    """
    node = getattr(module, "_node", None)
    model_path = getattr(getattr(node, "config", None), "model_path", "")
    if isinstance(model_path, str) and model_path:
        return Path(model_path).name
    return fallback


#: Where a forwarder writes the model it is serving a STREAM with. An internal
#: attribute on the response object, deliberately not a header: the name
#: already travels inside every SSE chunk, and a second public spelling of it
#: would be a promise this door then has to keep.
_SERVED_MODEL_ATTR = "nexe_served_model"


def mark_served_model(response, model_name: str):
    """Record which model is answering, and hand the response straight back.

    Every forwarder resolves this name synchronously, before it builds the
    `StreamingResponse` — and then dropped it, so the turn's LLM counter wrote
    `model=null` for every streamed /v1 call while the UI door logged the real
    name (#1054). The JSON shape needs nothing: `build_openai_response` already
    writes `"model"`.
    """
    setattr(response, _SERVED_MODEL_ATTR, model_name)
    return response


def served_model_of(response) -> Optional[str]:
    """The model that answered: the `"model"` field of a JSON response, the
    attribute above for a stream, and `None` for a test double that carries
    neither — an unknown name is logged as unknown, never guessed."""
    if isinstance(response, dict):
        return response.get("model") or None
    return getattr(response, _SERVED_MODEL_ATTR, None)


def extract_engine_text(result) -> str:
    """Extract text content from a non-streaming engine result (dict or str)."""
    if isinstance(result, dict):
        if "message" in result and "content" in result["message"]:
            return result["message"]["content"]
        if "content" in result:
            return result["content"]
        if "response" in result:
            return result["response"]
        return ""
    if isinstance(result, str):
        return result
    return ""


def build_openai_response(result: dict, model_name: str, engine_prefix: str) -> dict:
    """Build an OpenAI-compatible chat completion response from an engine result."""
    return {
        "id": f"{engine_prefix}-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": _sanitize_sse_token(result.get("response", "")),
            },
            # The engines already compute this (MLX carries it in its result
            # dict, and _compute_continuable reads the same field). Hardcoding
            # "stop" told an OpenAI client a ceiling-cut answer was complete,
            # so it never asked for the tail. Anything the engine cannot
            # answer for still degrades to "stop".
            #
            # The VLM path is excluded on purpose: mlx_vlm reports no
            # finish_reason, so vlm_runner guesses one from "gen_tokens hit the
            # ceiling exactly" — a guess it documents as false-positive on an
            # EOS that lands on the limit, and justifies by the marker being
            # informative-only. A VLM model makes EVERY turn take that path
            # (the dispatch keys on model capability, not on the request), so
            # propagating the guess here would turn it into a contract signal
            # telling clients to resume answers that are complete — on a path
            # that refuses continue_final outright.
            "finish_reason": (
                "length"
                if result.get("finish_reason") == "length" and not result.get("vlm")
                else "stop"
            ),
        }],
        "usage": {
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("tokens", 0),
            "total_tokens": result.get("context_used", 0),
        },
    }


