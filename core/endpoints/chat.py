"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat.py
Description: Unified Chat Endpoint with RAG support & Streaming.
             Orchestrator — delegates to submodules.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import time
from collections import OrderedDict
from uuid import uuid4
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from core.security.auth_dependencies import require_api_key
from core.security.input_sanitizers import validate_string_input

from .chat_schemas import Message, ChatCompletionRequest
from core.log_redact import redact_user_content
from core.context_presentation import ContextShape, frame_for
from .chat_sanitization import (
    _sanitize_rag_context,
    _sanitize_sse_token,
    context_turns_for,
    note_turns_for,
    MAX_RAG_CONTEXT_LENGTH,
    MAX_CHAT_INPUT_LENGTH,
    DEFAULT_CONTEXT_WINDOW,
    CHARS_PER_TOKEN_ESTIMATE,
)
from .chat_rag import (
    build_rag_context,
    _rag_result_to_text,
    _RAG_CONTEXT_LABELS,
    RAG_DOCS_THRESHOLD,
    RAG_KNOWLEDGE_THRESHOLD,
    RAG_MEMORY_THRESHOLD,
)
from .chat_engines.routing import (
    _normalize_engine,
    _get_preferred_engine,
    _engine_available,
    _resolve_engine,
    raise_if_terminal,
    resolve_engine_cascade,
)
from .chat_engines.ollama import (
    _forward_to_ollama,
    _ollama_stream_generator,
    _ollama_tags_cache,
    TAGS_CACHE_TTL,
    _OLLAMA_STREAM_TIMEOUT,
    _OLLAMA_ERRORS,
)
from .chat_engines.mlx import _forward_to_mlx, _mlx_stream_generator
from .chat_engines.llama_cpp import _forward_to_llama_cpp, _llama_cpp_stream_generator
from .chat_engines._common import persist_v1_turn, served_model_of
from core.dependencies import limiter
from core.turn.adapters_api import api_adapters
from core.turn.recall import _build_rag_context as recall_for_turn
from core.turn.prompt import turn_system_prompt
from core.turn.context import TurnContext
from core.turn.post_commit import queue_for
from core.turn.run import run_turn
from core.lang_detect import (
    detect_user_lang_or_none as _detect_lang_or_none,
    fallback_lang as _fallback_lang,
    natural_text_len,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# --- #854: sticky reply language (same policy as #850 on the web UI route) ---
# The language decides the CRITICAL directive that OPENS the system prompt, so
# recomputing it per request rewrote the prompt from token 0 mid-conversation:
# a new trie node on MLX, _destroy + GGUF reload on llama.cpp — for the same
# session_id the engines key their prefix cache by. Policy (commit 8f67d6a6,
# #850): the fallback is returned but NEVER seeded, the switch gate measures
# the NATURAL text (code/URLs out), and a switch needs two consecutive
# detections of the same new language.
#
# This route has no ChatSession to hang the state on, so it keeps an LRU keyed
# by the very session_id the engines use (derive_session_id) — stickiness and
# prefix cache then share one scope by construction. The policy is duplicated
# rather than imported because core must not depend on a plugin; the parity
# test in tests/core/endpoints/test_f854_sticky_lang_openai.py fails if either
# copy drifts (the shared home would be core.lang_detect — see the finding).
_STICKY_LANG_MIN_SWITCH_CHARS = 25
_SESSION_LANG_MAX = 256
_SESSION_LANG: "OrderedDict[str, dict]" = OrderedDict()


def _reset_session_lang_state() -> None:
    """Drop every remembered session language — test isolation only.

    The map is process-local state with no lifecycle of its own; nothing in the
    server calls this. Tests that drive the route must, or a session language
    seeded by one test decides the system prompt of the next.
    """
    _SESSION_LANG.clear()


def _resolve_request_lang(session_key: str, user_text: str) -> str:
    """Reply language for this turn: sticky per session_key (#854).

    Mirrors plugins/web_ui_module/api/routes_chat._resolve_session_lang.
    """
    detected = _detect_lang_or_none(user_text)
    state = _SESSION_LANG.get(session_key)
    if state is None:
        # A guess never locks the session — the first REAL detection decides.
        if detected is None:
            return _fallback_lang(None)
        _SESSION_LANG[session_key] = {"lang": detected, "pending": None}
        while len(_SESSION_LANG) > _SESSION_LANG_MAX:
            _SESSION_LANG.popitem(last=False)
        return detected

    _SESSION_LANG.move_to_end(session_key)
    sticky = state["lang"]
    if (
        detected
        and detected != sticky
        and natural_text_len(user_text) >= _STICKY_LANG_MIN_SWITCH_CHARS
    ):
        if state["pending"] == detected:
            state["lang"] = detected
            state["pending"] = None
            return detected
        state["pending"] = detected
        return sticky
    if detected == sticky and state["pending"] is not None:
        state["pending"] = None  # the conversation reaffirms the sticky language
    return sticky


# --- System Prompt ---
# C4.2: `_get_system_prompt` lives in `core/turn/prompt.py` now, with the rest
# of the turn's prompt assembly. It moved because the OTHER door had to import
# it from here — a plugin reaching into this route module (`routes_chat.py`'s
# `from core.endpoints.chat import _get_system_prompt`), which is exactly the
# inverted dependency C4 exists to remove. This module reaches it the same way
# everyone else does now: through `turn_system_prompt`.


# --- Helper Functions ---

def _validate_chat_request(body: ChatCompletionRequest) -> None:
    """Validate the request's own fields: the routing params, and the content
    of the messages this door did NOT receive from the user.

    C4.1: the USER's text is no longer sanitized here. It goes through
    `core.turn.validate.sanitize_user_text` in the turn's `sanitize` step
    (`core/turn/adapters_api.py`), which is the same chain `/ui/chat` runs —
    that is what unfolds `sanitize` at this door. Two consequences, both
    intended:

    * `apply_user_text_sanitizer` still gates every user message, one step
      later in the same turn, before anything is persisted or sent to a model;
    * user content is validated with `allow_html=True` (the 31/08 decision,
      quoted in `core/turn/validate.py`), while a system/assistant message the
      CLIENT supplies keeps the escaping default it has always had — that
      decision was about the user's message reaching the model, and about
      nothing else.
    """
    if body.model is not None:
        body.model = validate_string_input(body.model, max_length=200, context="param")
    if body.engine is not None:
        body.engine = validate_string_input(body.engine, max_length=50, context="param")
    for _msg in body.messages:
        if _msg.role is not None:
            _msg.role = validate_string_input(_msg.role, max_length=50, context="param")
        if _msg.content is not None and _msg.role != "user":
            _msg.content = validate_string_input(_msg.content, max_length=MAX_CHAT_INPUT_LENGTH, context="chat")


async def _fetch_rag_context(
    body: ChatCompletionRequest, app_state: Any, server_lang: str,
    *, has_document: bool = False,
) -> tuple[str, list[tuple[str, float]]]:
    """Retrieve RAG context text for the last user message, if RAG is enabled.

    Returns (context_text, rag_items) — rag_items is [(collection, score), ...]
    for the results actually used; empty when RAG is off or found nothing.

    `has_document` (C4.3) is whether this turn's session carries an attached
    document. It reaches the same `collections_for_turn` the web door uses, so
    the rule that a document replaces its own collection — and ONLY its own —
    is the turn's and not one door's.
    """
    if not body.use_rag:
        return "", []
    last_user_msg = next((m.content for m in reversed(body.messages) if m.role == "user"), None)
    if not last_user_msg:
        return "", []
    # MC-109/111: the user's message must not land in plain in the log file.
    logger.info("RAG Search for: %s", redact_user_content(last_user_msg))
    # C4.2: the retrieval itself is the turn's `recall` step, shared with
    # /ui/chat (`core/turn/recall.py`). What stays this door's is the question
    # of WHETHER to recall — `use_rag` is a field of this schema alone.
    from core.turn.recall import collections_for_turn
    text, _count, items = await recall_for_turn(
        last_user_msg, app_state=app_state, lang=server_lang,
        collections=collections_for_turn(body.rag_collections, has_document=has_document),
        threshold_override=body.rag_threshold,
    )
    return text, items


def _ensure_system_message(messages: list, system_prompt: str) -> None:
    """Put the turn's system prompt at the head of the messages list (in-place).

    C4.2: the prompt itself is built by the turn's `system_prompt` step
    (`core/turn/prompt.py::turn_system_prompt`), which is where the date phrase,
    the collection-toggle notes and the unconditional RAG rule are added — the
    same function `/ui/chat` runs. This only places it: a client that sent its
    own system message keeps it (finalised), and one that sent none gets the
    server's.
    """
    if messages and messages[0]['role'] == 'system':
        messages[0]['content'] = system_prompt
    else:
        messages.insert(0, {"role": "system", "content": system_prompt})


def _system_prompt_for_turn(body: ChatCompletionRequest, app_state: Any, server_lang: str) -> str:
    """This door's `system_prompt` step: what the turn's system message says.

    A client-supplied system message is the base when there is one — this door
    has always used it as-is, so it does NOT get the date phrase; without one
    the prompt comes from server.toml exactly as the web UI builds it. Both go
    through the same finalisation (collection notes + RAG security rule).
    """
    client_system = None
    if body.messages and body.messages[0].role == 'system':
        client_system = body.messages[0].content
    return turn_system_prompt(
        lang=server_lang, rag_collections=body.rag_collections,
        base=client_system, app_state=app_state,
    )


def get_effective_context_window(engine: str, app_state: Any = None) -> int:
    """MC-090: the RAG token budget must reflect the context window the serving
    engine actually uses, not a fixed 8192.

    #965: this now asks the live engine through its own ``get_context_window()``
    instead of special-casing Ollama here, and the old
    ``min(auto_num_ctx(), DEFAULT_CONTEXT_WINDOW)`` cap is gone. That cap read as
    "never more than the user asked for", but nothing sets
    ``NEXE_DEFAULT_CONTEXT_WINDOW`` anywhere in the product — so in practice it
    meant "always 8192", and a 128 GB machine planned its RAG budget for a
    quarter of the window its model could hold. MLX and llama.cpp were not
    adjusted at all before this; now all three answer for themselves.

    ``app_state`` is optional: without it there is no live module to ask and the
    documented default stands.
    """
    from core.context_window import resolve_context_window
    return resolve_context_window(engine, app_state)


#: Chars held back for the model's reply in this door's budget. Named because
#: `_history_chars_for_budget` and the `compute_context_budget` call below have
#: to subtract the SAME number: two literals that split one total are two
#: literals that drift apart, and the drift would be silent — the document
#: would just start fitting a little worse than the arithmetic says.
V1_RESPONSE_BUFFER_CHARS = 500


def _history_chars_for_budget(
    history_chars: int, document_chars: int,
    max_context_chars: int, system_chars: int, message_chars: int,
) -> int:
    """How much of the client's history the budget should count (C4.4).

    All of it, unless a document is attached and counting all of it would
    leave the document no room. The turn's document does not lose to history
    that `_fit_v1_messages_to_window` (#976) is about to drop anyway — that
    was the old behaviour and it cost the document whole, silently, for turns
    the very next step then trimmed.

    A history that already fits under the cap comes back untouched, so the
    ordinary turn computes exactly the budget it always did. Lives on its own
    rather than inside `_trim_rag_context` because that function was at the
    complexity ceiling and this is a question with its own name.
    """
    if document_chars <= 0:
        return history_chars
    cap = max(
        0,
        max_context_chars - system_chars - message_chars
        - V1_RESPONSE_BUFFER_CHARS - document_chars,
    )
    if history_chars <= cap:
        return history_chars
    logger.info(
        "Document attached: history counted as %d of %d chars for the budget "
        "(the rest is dropped by the window fit anyway)",
        cap, history_chars,
    )
    return cap


def _trim_rag_context(
    safe_context: str, messages: list, effective_ctx_window: int = None,
    document_chars: int = 0, scaffold_chars: int = 0,
) -> str:
    """Trim RAG context to what the turn's budget actually leaves for it.

    ``effective_ctx_window`` (MC-090) is the real context window of the serving
    engine; when None it falls back to ``DEFAULT_CONTEXT_WINDOW`` (back-compat).

    F-D block 4. This is the SECOND of two limits, not the only one: the
    caller has already run ``_sanitize_rag_context``, whose ceiling of
    ``max(4000, window x MAX_CONTEXT_RATIO x 4)`` both doors share and which
    this does not replace. What this used to be was a redundant re-application
    of that same 30% ratio, plus a 256-token emergency brake that cut the
    context to a magic 1000 chars. Neither looked at the turn as a whole: no
    room was reserved for anything else, so an oversized history shipped to
    the engine untouched while the retrieved context — the part that had a
    limit — took the blame. llama.cpp answers an oversized prompt with a
    ValueError, not a truncation.

    Now the retrieved context is also bounded by what the turn has left
    (``compute_context_budget``, the same function /ui/chat uses): the prompt
    gets PROMPT_BUDGET_RATIO of the window, 500 chars are held back for the
    answer, and what remains after the system prompt, the history and the
    message bounds the RAG payload. Where the old code cut to 1000 chars it
    now drops the context and says so — an answer that does not fit is not
    made to fit by keeping a thousand characters of it.

    What is bounded is the PAYLOAD, not the block that reaches the prompt:
    the wrapper (nonce'd delimiters plus an assistant ack turn) is not counted,
    so the assembled prompt runs a few hundred chars past the budget it just
    computed. Filed as #999 rather than fixed here, because the wrapper is
    shared and counting it changes what /ui/chat ships too. The other half of
    that overrun WAS ours and is fixed: the security rule is now appended
    before the budget is taken, as /ui/chat has always done.

    ``history_ratio=0`` on purpose, and that half of the reasoning still
    holds: the floor exists to stop a big attached document from crowding out
    earlier turns (Bug 32), and reserving a share of the budget for a history
    that is complete (the client sent all of it; it will not grow inside this
    request) reserves it for nobody.

    The OTHER half — "this path has no documents, ``document_chars`` is always
    0 here" — stopped being true at #1078, when `budget` started folding an
    attached document into this same block. What that left behind was worse
    than the sentence: the budget counted the client's history whole, went
    negative on it, and dropped the retrieved block with the document inside,
    while ``_fit_v1_messages_to_window`` (#976) ran next and dropped those same
    old turns anyway. The document was given up for history that was already
    on its way out.

    So ``document_chars`` arrives now, and when it is set the history that
    enters the arithmetic is CAPPED at what is left once the document has its
    place. Not a bigger budget — the same one, told the truth about what is in
    it. With no document the numbers are byte-for-byte what they were.

    No numbers in this docstring, deliberately. Three earlier versions of it
    quoted measured tables and all three drifted — one described a budget
    difference as lost retrieval, one counted a path production does not take,
    one left out a 490-char rule it named in the same sentence. The figures
    live in tests/core/test_fd_block4_budget_shared.py, where they are
    executable and fail when they stop being true.
    """
    # Deferred import, same reason context_budget defers core.context_window:
    # core/endpoints/__init__.py eagerly pulls .v1 -> .chat, so a module-level
    # import here closes a cycle the moment anything imports core.context_budget
    # first (core.context_budget -> chat_sanitization -> core.endpoints.__init__
    # -> .chat -> core.context_budget, still half-initialised).
    from core.context_budget import (
        compute_context_budget,
        resolve_max_context_chars,
    )

    ctx_window = effective_ctx_window if effective_ctx_window is not None else DEFAULT_CONTEXT_WINDOW

    # Same split the UI route feeds the budget: the system prompt, the history
    # before this turn, and the message being answered.
    system_chars = sum(len(m.get('content', '') or '') for m in messages if m.get('role') == 'system')
    _non_system = [m for m in messages if m.get('role') != 'system']
    message_chars = len(_non_system[-1].get('content', '') or '') if _non_system else 0
    history_chars = sum(len(m.get('content', '') or '') for m in _non_system[:-1])

    # C4.4: the framing prose is part of what this turn ships, so it comes out
    # of the same budget the payload does, and it comes out FIRST — everything
    # below has to reason about the same total, or the history cap would be
    # computed against room that is already spoken for. Subtracted and never
    # branched on: this function sits one point under the complexity ceiling,
    # and an `if` here would put it on the baseline for an arithmetic detail.
    max_context_chars = resolve_max_context_chars(window_tokens=ctx_window) - scaffold_chars

    history_chars = _history_chars_for_budget(
        history_chars, document_chars, max_context_chars, system_chars, message_chars,
    )

    budget = compute_context_budget(
        max_context_chars=max_context_chars,
        system_chars=system_chars,
        history_chars=history_chars,
        message_chars=message_chars,
        document_chars=document_chars,
        history_ratio=0.0,  # see the docstring
        response_buffer=V1_RESPONSE_BUFFER_CHARS,
    )
    available_chars = budget["available_chars"]

    if available_chars <= 0:
        # #965's lesson: silent context loss is the bug. The UI route warns here
        # too (_inject_context_into_messages) — same event, same visibility.
        # Naming the document matters: this warning used to say "retrieved
        # context" for a block that had the user's own upload inside it.
        logger.warning(
            "Dropping retrieved context%s: budget exhausted (available_chars=%d, history=%d)",
            " INCLUDING THE ATTACHED DOCUMENT" if document_chars > 0 else "",
            available_chars, history_chars,
        )
        return ""

    if len(safe_context) > available_chars:
        logger.info(
            "RAG context trimmed to the turn budget: %d -> %d chars", len(safe_context), available_chars
        )
        safe_context = safe_context[:available_chars]

    return safe_context


def _insert_before_last_user(messages: list, turns: list[dict]) -> bool:
    """Splice `turns` immediately before the last user-role message, in place.

    Shared tail for every kind of scaffolding this door injects (doc/RAG
    block, #1081 image note): the client's array only ever gets turns
    inserted before its own last user message, never appended after it.
    Returns whether anything was spliced in.
    """
    if not turns:
        return False
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]['role'] == 'user':
            messages[i:i] = turns
            return True
    return False


def _inject_rag_context_into_messages(
    messages: list, context_text: str, server_lang: str,
    effective_ctx_window: int = None, document_chars: int = 0,
    has_rag: bool = False, app_state=None, has_image: bool = False,
) -> bool:
    """Inject RAG/document/image scaffolding before the last user message (in-place).

    Returns whether RAG/document context was actually injected. The caller
    reports RAG as active from that, not from having retrieved something:
    since F-D block 4 the turn's budget can leave no room at all, and a
    server that answers "X-Nexe-RAG-Status: active" after dropping the
    context is telling the client the model saw sources it never saw.
    `has_image` (#1081) does not affect this flag: the image note is
    independent trusted scaffolding, never untrusted retrieved content.

    B030 (RT-01): the retrieved content is wrapped in nonce'd delimiters with a
    data-not-instructions intro, and the system message gets the static RAG
    security rule. _sanitize_rag_context escapes forged delimiters inside the
    content, so only this runtime can emit a valid [CONTEXT <id>] pair.

    B030 layer 2d (turn separation): the wrapped block travels in a separate
    user turn + assistant data-only acknowledgement, inserted BEFORE the last
    user message — the user's question arrives clean and keeps its authority,
    instead of the document speaking with the user's voice. The image note
    (#1081) follows the same rule with its own neutral ack (`note_turns_for`)
    and is spliced in closest to the real message, after any doc/RAG block.
    """
    _injected = False
    # #1081: built BEFORE the trim, because what the note pair occupies is
    # part of what this turn ships — the same reason `legend`/`closing` are
    # counted below. Leaving it out let the assembled prompt grow past the
    # budget by ~200 chars on every image turn, which is exactly the promise
    # `WRAPPER_SLACK` exists to keep honest (ADR-009).
    _note_turns = note_turns_for(app_state, server_lang, has_image=has_image)
    _note_chars = sum(len(t.get("content") or "") for t in _note_turns)
    if context_text and messages:
        framing = frame_for(
            app_state,
            ContextShape(
                lang=server_lang, has_document=document_chars > 0, has_rag=has_rag,
            ),
        )
        # Asked here only for its LENGTH: the payload has to be trimmed BEFORE
        # the turns are composed, and what the prose occupies is part of what
        # the turn ships. `context_turns_for` asks again for the words
        # themselves — the same answer, because the port is text selection and
        # not I/O by contract (`core/context_presentation/port.py`), so a
        # presenter with state would be breaking that contract, not this call
        # site.
        safe_context = _sanitize_rag_context(context_text, effective_ctx_window)
        safe_context = _trim_rag_context(
            safe_context, messages, effective_ctx_window, document_chars,
            len(framing.legend) + len(framing.closing) + _note_chars,
        )
        if safe_context:
            # F-D block 4: the trim can come back empty (the turn's budget is
            # spent), where before it always kept at least a slice. Injecting
            # the turn pair anyway would hand the model a "use this retrieved
            # information:" block with nothing in it — and cost a
            # prefix-cache miss to say nothing. _trim_rag_context has already
            # logged why.
            turns = context_turns_for(
                app_state, safe_context, server_lang,
                has_document=document_chars > 0, has_rag=has_rag,
            )
            _injected = _insert_before_last_user(messages, turns)
    # #1081: independent of the RAG/document branch above — a turn can carry
    # an image with no document and no retrieval, and `note_turns_for`
    # returns `[]` (a no-op splice) when there is nothing to say.
    if _note_turns and not _insert_before_last_user(messages, _note_turns):
        # The splice reports "nothing inserted" and the old `for...else` here
        # used to act on exactly that signal. Dropping the return value would
        # leave the model told nothing about an image it is about to receive.
        logger.warning(
            "Image note dropped: no user message in the request to insert it before",
        )
    # #851: la regla de seguretat s'arma INCONDICIONALMENT al caller
    # (_build_rag_and_system_prompt) — aquí només corria amb context i
    # partia el namespace de la caché de prefix entre torns amb/sense RAG.
    return _injected


def _assemble_v1_messages(
    body: ChatCompletionRequest, system_prompt: str, context_text: str,
    clock_line: str, server_lang: str, effective_ctx_window: int = None,
    document_chars: int = 0, has_rag: bool = False, app_state=None,
    has_image: bool = False,
) -> tuple[list[dict], str]:
    """The `budget` step at this door: the messages list the engine is given.

    C4.2: this is what is LEFT of `_build_rag_and_system_prompt` once the three
    steps it used to fold ran for themselves. Retrieval arrives as
    ``context_text`` (the `recall` step), the system message arrives built
    (`system_prompt`), and the clock line arrives resolved (`clock`) — this
    places them, fits the retrieved block to what the turn's budget leaves, and
    reports what actually reached the model.

    ``effective_ctx_window`` (MC-090) is the serving engine's real context
    window, used to size the RAG token budget; None falls back to
    DEFAULT_CONTEXT_WINDOW.

    Returns (messages, injected_context_text). The second value is the
    retrieved text ONLY when it actually reached the prompt: since F-D block 4
    the turn's budget can drop it, and this returns "" then. It drives
    X-Nexe-RAG-Status, so it has to mean "the model was given this", not
    "retrieval found this".
    """
    messages = [m.model_dump() for m in body.messages]

    # #851: the static data-not-instructions rule is armed by
    # `turn_system_prompt`, UNCONDITIONALLY and BEFORE the injection — which is
    # the order /ui/chat has always used, and the reason the rule is counted in
    # the system_chars the turn's budget is computed from. Arming it afterwards
    # left 457-514 chars (language-dependent) outside that budget, so /v1
    # planned a prompt ~490 chars smaller than the one it then sent.
    _ensure_system_message(messages, system_prompt)

    _injected = _inject_rag_context_into_messages(
        messages, context_text, server_lang, effective_ctx_window, document_chars,
        has_rag, app_state, has_image=has_image,
    )

    # F-D block 1: clock on demand — parity with the UI route. Never the
    # system prompt (would poison the prefix cache for the whole
    # conversation); only this turn's user message diverges in the cache.
    if clock_line and messages and messages[-1]['role'] == 'user':
        messages[-1]['content'] = f"{clock_line}\n\n{messages[-1]['content']}"

    # The second value drives X-Nexe-RAG-Status: report what the model was
    # actually given, not what retrieval found.
    return messages, (context_text if _injected else "")


async def _dispatch_to_engine(
    engine: str, messages: list[dict], body: ChatCompletionRequest,
    request: Request, app_state: Any, last_user_msg: Optional[str], session_id: Optional[str] = None,
    cancel_event: Any = None, images: Optional[list[str]] = None,
) -> Any:
    """Route the chat request to the resolved backend engine (Ollama, MLX, or llama.cpp).

    ``session_id`` (F-C) is only threaded to Ollama here: MLX and llama.cpp
    derive it themselves from the RAW client request (they need it either
    way), so passing it again would just be a second, redundant derivation.

    ``cancel_event`` (#1041, C2.5): only MLX/llama.cpp take it — they are the
    in-process engines whose token loop can check it. Ollama keeps its own
    ``httpx`` timeout (a deadline shorter than that timeout still wins,
    since either one ending the call is enough).

    ``images`` (#1081): a single base64 string in a list, same shape
    the UI door's `_start_engine_call` has always passed — which engine
    actually reads it is that engine's own decision, never this door's.
    """
    if engine.lower() == "ollama":
        return await _forward_to_ollama(
            messages, body, app_state, last_user_msg, session_id=session_id, images=images,
        )
    elif engine.lower() == "mlx":
        return await _forward_to_mlx(messages, body, request, cancel_event=cancel_event, images=images)
    elif engine.lower() in ["llama_cpp", "llama.cpp", "llamacpp"]:
        return await _forward_to_llama_cpp(messages, body, request, cancel_event=cancel_event, images=images)
    else:
        return await _forward_to_ollama(
            messages, body, app_state, last_user_msg, session_id=session_id, images=images,
        )


def _persist_v1_turn_from_response(
    response: Any, background_tasks: BackgroundTasks, app_state: Any, session_id: str
) -> None:
    """Queue the assistant's reply to be mirrored into its /v1 session (F-C).

    Covers the non-streaming request/response shape only. A streaming
    response persists its own turn inside the SSE generator, at the point
    the full text becomes available (mirrors the pre-F-A
    ``_schedule_episodic_memory``, now targeting the session mirror instead
    of episodic memory).
    """
    if isinstance(response, StreamingResponse):
        return
    try:
        content = ""
        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
            if not content:
                content = response.get("message", {}).get("content", "")
        if content:
            background_tasks.add_task(persist_v1_turn, app_state, session_id, content)
    except Exception as e:
        logger.error("Failed to schedule /v1 session mirror: %s", e, exc_info=True)


def _record_engine_metrics(engine: str, engine_status: str, start_time: float) -> None:
    """Emit Prometheus counters and histogram for the chat engine invocation."""
    try:
        from core.metrics.registry import CHAT_ENGINE_REQUESTS, CHAT_ENGINE_DURATION
        CHAT_ENGINE_REQUESTS.labels(engine=engine, status=engine_status).inc()
        CHAT_ENGINE_DURATION.labels(engine=engine).observe(time.time() - start_time)
    except Exception as e:
        logger.debug("Chat engine metrics update failed: %s", e)


def _inject_response_headers(
    response: Any, engine: str, context_text: str, preferred_fallback: Optional[str],
    fallback_reason: str = "preferred_unavailable",
) -> Any:
    """Add ``X-Nexe-*`` headers (engine, RAG status, fallback) to the response.

    ``fallback_reason`` used to be the hardcoded string above, which was true
    while the only way to end up on another engine was that the one asked for
    was not live. Since F-D block 5 the cascade also moves on when an engine
    fails mid-turn, and reporting THAT as "preferred_unavailable" tells the
    client something that did not happen — the sibling vocabulary
    (fallback_to_ollama) already calls it "execution_failed".
    """
    if isinstance(response, StreamingResponse):
        if "X-Nexe-Engine" not in response.headers:
            response.headers["X-Nexe-Engine"] = engine
        response.headers["X-Nexe-RAG-Status"] = "active" if context_text else "inactive"
        if preferred_fallback and "X-Nexe-Fallback-From" not in response.headers:
            response.headers["X-Nexe-Fallback-From"] = preferred_fallback
            response.headers["X-Nexe-Fallback-Reason"] = fallback_reason
    elif isinstance(response, dict):
        response.setdefault("nexe_engine", engine)
        response.setdefault("nexe_rag_status", "active" if context_text else "inactive")
        if preferred_fallback:
            response.setdefault(
                "nexe_fallback",
                {"from": preferred_fallback, "to": engine, "reason": fallback_reason},
            )
    return response


def _fit_v1_messages_to_window(
    messages: list[dict], window_tokens: Optional[int], body: ChatCompletionRequest
) -> list[dict]:
    """#976: the prompt this door assembles must fit the engine's window too.

    /ui/chat carries the system prompt beside the turns; /v1 carries it as
    messages[0] (OpenAI shape). Split it off, fit the turns, put it back — so
    both doors enforce the same invariant with the same function instead of two
    lookalikes.

    The reply reserve is what the client asked for (``max_tokens``); a client
    asking for more than the engine holds is clamped inside the shared function,
    not here.

    Deferred import for the cycle documented in _inject_rag_context_into_messages.
    """
    if not messages:
        return messages
    from core.context_budget import fit_prompt_to_window

    system_msg = messages[0] if messages[0].get("role") == "system" else None
    turns = messages[1:] if system_msg else messages
    fitted, _trimmed = fit_prompt_to_window(
        (system_msg.get("content") or "") if system_msg else "",
        turns,
        window_tokens or DEFAULT_CONTEXT_WINDOW,
        reply_budget_tokens=body.max_tokens or 0,
    )
    return ([system_msg] + fitted) if system_msg else fitted


async def _dispatch_through_cascade(
    body: ChatCompletionRequest, request: Request, messages: list[dict],
    last_user_msg: Optional[str], session_id: str, engine: str,
    preferred_fallback: Optional[str], *, cancel_event: Any = None,
    images: Optional[list[str]] = None,
) -> tuple:
    """Try the resolved engine, then the rest of the cascade. Returns
    ``(response, engine_that_answered, fallback_from, fallback_reason,
    model_that_answered)``.

    ``images`` (#1081): threaded unchanged to every candidate in the
    cascade — an image that one engine cannot read is not a reason to skip
    it, the same "the engine decides" rule the UI door has always followed.

    The last element is #1054: the engine's NAME is not the model's, and the
    turn's LLM counter had no way to reach the second one — every streamed /v1
    call was logged with ``model=null`` while the UI door logged the real name.
    Read off the response the forwarder just built (`served_model_of`), so no
    forwarder signature changes and a patched double that returns a bare dict
    keeps working.

    F-D block 5. This door used to dispatch exactly once: whatever the single
    engine raised became the client's error, while /ui/chat quietly walked down
    its list and answered. The list and the policy are now the same at both
    doors (resolve_engine_cascade / should_try_next_engine), and the response
    headers name the engine that actually answered rather than the one that was
    picked.

    An HTTPException is never retried — that is how the forwarders report a
    backend that is down, and it is the answer, not a crash. What IS retried is
    an engine failing at this moment: a corrupt model, an out-of-memory, a
    driver. This is now the ONLY fallback mechanism (#1036, C2.4): the MLX and
    llama.cpp forwarders used to catch their own execution errors and jump
    straight to Ollama, a second mechanism that pre-empted this cascade and
    skipped llama.cpp entirely — removed, so every failure (including one
    raised before a streaming response's first byte) lands here.
    """
    cascade = resolve_engine_cascade(body.engine, request.app.state) or [engine]
    last_exc: Optional[BaseException] = None
    reason = "preferred_unavailable"
    for candidate in cascade:
        start_time = time.time()
        try:
            # #976, per engine: the prompt was fitted to the window of the engine
            # that was RESOLVED, and this loop can hand it to a different one.
            # Falling back from a 32k engine to a 2048 one with the first one's
            # prompt is the very crash the fit guard exists to prevent — and it
            # would only appear on the fallback path, which is the one nobody
            # exercises. Fitting an already-fitted list to a bigger window
            # returns it unchanged.
            attempt_messages = _fit_v1_messages_to_window(
                messages, get_effective_context_window(candidate, request.app.state), body
            )
            response = await _dispatch_to_engine(
                candidate, attempt_messages, body, request, request.app.state, last_user_msg, session_id,
                cancel_event=cancel_event, images=images,
            )
        except Exception as exc:
            _record_engine_metrics(candidate, "error", start_time)
            raise_if_terminal(exc, candidate)
            logger.warning("Engine %s failed (%s); trying the next in the cascade", candidate, exc)
            last_exc = exc
            # From here on a fallback is not "the one you asked for was not
            # live" — it is "it was live and it broke".
            reason = "execution_failed"
            continue
        _record_engine_metrics(candidate, "success", start_time)
        if candidate != engine and not preferred_fallback:
            preferred_fallback = engine
        return response, candidate, preferred_fallback, reason, served_model_of(response)

    # Every live engine failed with something retryable.
    raise last_exc if last_exc is not None else RuntimeError("no engine available")


# --- Main Endpoint ---

@router.post("/chat/completions", dependencies=[Depends(require_api_key)], summary="Chat completion with RAG support and engine auto-routing", operation_id="chat_completions")
@limiter.limit("20/minute")
async def chat_completions(body: ChatCompletionRequest, request: Request, background_tasks: BackgroundTasks) -> Any:
    """
    Unified Chat Completion endpoint.
    Supports:
    - RAG (Retrieval Augmented Generation)
    - Auto-routing to engines (Ollama, MLX, Llama.cpp)

    ADR-007 (C1.2): this door no longer decides the order of the turn. It
    builds a `TurnContext` and lets `run_turn` walk `TURN_STEPS`; every step
    is an adapter in `core/turn/adapters_api.py` wrapping the same functions
    this body used to call in the same order. `ctx.wire` is what the client
    gets — a dict, or the `StreamingResponse` the engine forwarder built.
    Exceptions propagate untouched (a 400 from validation stays a 400).
    """
    ctx = TurnContext(
        turn_id=uuid4().hex,
        entry="api",
        # C4.1 (#1044): WHO the route dependency authenticated. `require_api_key`
        # records it on the request (`auth_dependencies._remember_principal`);
        # the turn's `authorize` step refuses a missing one, and refuses the
        # `dev-mode-bypass` label too. Nothing wrote this field before C4.1.
        principal=getattr(getattr(request, "state", None), "principal", None),
        streaming=bool(body.stream),
        body=body,
        request=request,
        app_state=request.app.state,
    )
    # C3.3: /v1 gets the post-commit queue too — memory.write leaves the
    # critical path here as well, instead of running inline or not at all.
    await run_turn(ctx, api_adapters(background_tasks), post_commit=queue_for(request.app.state))
    return ctx.wire


# Re-exports for backwards compatibility (used by tests and other modules
# that import from core.endpoints.chat instead of the original submodule).
# Adding __all__ silences ruff F401 for these intentional re-exports.
__all__ = [
    "router",
    "chat_completions",
    # Re-exported from .chat_schemas
    "Message",
    "ChatCompletionRequest",
    # Re-exported from .chat_sanitization
    "_sanitize_rag_context",
    "_sanitize_sse_token",
    "MAX_RAG_CONTEXT_LENGTH",
    "DEFAULT_CONTEXT_WINDOW",
    "CHARS_PER_TOKEN_ESTIMATE",
    # Re-exported from .chat_rag
    "build_rag_context",
    "_rag_result_to_text",
    "_RAG_CONTEXT_LABELS",
    "RAG_DOCS_THRESHOLD",
    "RAG_KNOWLEDGE_THRESHOLD",
    "RAG_MEMORY_THRESHOLD",
    # Re-exported from .chat_engines.routing
    "_normalize_engine",
    "_get_preferred_engine",
    "_engine_available",
    "_resolve_engine",
    # Re-exported from .chat_engines.ollama
    "_forward_to_ollama",
    "_ollama_stream_generator",
    "_ollama_tags_cache",
    "TAGS_CACHE_TTL",
    "_OLLAMA_STREAM_TIMEOUT",
    "_OLLAMA_ERRORS",
    # Re-exported from .chat_engines.mlx
    "_forward_to_mlx",
    "_mlx_stream_generator",
    # Re-exported from .chat_engines.llama_cpp
    "_forward_to_llama_cpp",
    "_llama_cpp_stream_generator",
]
