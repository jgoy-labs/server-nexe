"""One system prompt for both chat doors (ADR-007, C4.2).

Until here the prompt was assembled twice. `/ui/chat` built it in
`routes_chat.py` — collection-toggle notes, sticky reply language, the date
phrase, the unconditional RAG rule — and reached back INTO the API's route
module for the base prompt (`from core.endpoints.chat import
_get_system_prompt`, a plugin importing the other door's endpoint). `/v1`
built a shorter version of the same thing inside
`_build_rag_and_system_prompt`, which is why `core/turn/folded.py` counted
`system_prompt` as folded at that door. This module is where that behaviour
now lives, once, and the inverted import is gone: `get_system_prompt` is here,
and `core/endpoints/chat.py` imports it from the core like everyone else.

**What this changes for `/v1` (visible, and declared).** The collection-toggle
notes (#851) were a UI-only truth: with the documentation collection switched
off, retrieval correctly returned nothing while the static system prompt kept
promising documentation — and models improvised. The API door had the same
`rag_collections` field in its schema and none of the notes. One
`finalize_system_prompt` for both doors means an API turn that disables a
collection now says so in the prompt too.

**What did NOT converge here, and why (measured).** The sticky reply language
keeps two stores: `/ui/chat` writes it on the `ChatSession` object
(`session.lang`/`lang_pending`), `/v1` keys an LRU by the derived session id
(`core/endpoints/chat.py::_resolve_request_lang`, #854 — that door had no
session object when it was written). `resolve_session_lang` below is the UI's
half; making the API door share the same store is a change to #854's own
design and to the sixteen tests that pin it
(`tests/core/endpoints/test_f854_sticky_lang_openai.py`), not a move — see the
result of C4.2. The POLICY is already asserted identical by that file's
`TestPolicyParityWithWebUIRoute`.

**Imports.** Everything comes from `core/`. Two of them are function-local and
say why: `core.endpoints.chat_sanitization` and `core.lifespan` both drag in
`core/endpoints/__init__.py`, which eagerly imports `.v1` → `.chat` → this
module — a cycle that closes on a half-initialised `core.turn.prompt` the
moment anything imports it first. The same escape hatch `_trim_rag_context`
documents in `core/endpoints/chat.py` for the same package.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from core.chat_prompt import EMERGENCY_SYSTEM_PROMPT, build_system_prompt_with_time
from core.lang_detect import (
    STICKY_SWITCH_MIN_CHARS,
    decide_reply_lang,
    detect_user_lang,
    fallback_lang as _fallback_lang,  # noqa: F401 — re-exported: turn_adapters imports it from here
)
from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION


def _get_system_prompt(app_state: Any, lang: Optional[str] = None) -> str:
    """
    Select the system prompt by language and model tier.

    Priority:
    1. server.toml [personality.prompt].<lang>_<tier>
    2. server.toml [personality.prompt].<lang>_full  (tier fallback)
    3. server.toml [personality.prompt].en_full       (neutral fallback)
    4. Hardcoded minimum prompt
    """
    if lang is None:
        lang = os.getenv("NEXE_LANG", "en")

    config = getattr(app_state, "config", {}) or {}
    prompts = config.get("personality", {}).get("prompt", {})

    tier = os.getenv("NEXE_PROMPT_TIER", "full")
    lang_short = lang.split("-")[0].lower()  # "ca-ES" → "ca"

    # Look up specific prompt → fallback to full → fallback to en → minimum
    for key in [f"{lang_short}_{tier}", f"{lang_short}_full", "en_full"]:
        prompt = prompts.get(key, "")
        if prompt:
            return prompt

    return EMERGENCY_SYSTEM_PROMPT




# ─── Collection-toggle prompt overrides (2026-07-04) ──────────────────────────
# The RAG layer honours the UI collection toggles (rag_collections in the body),
# but the static system prompt kept promising documentation/memories — so models
# happily improvised "knowledge" with the collection OFF (found live: docs
# disabled, RAG correctly empty, Qwen3.5-27B still answered doc questions from
# the prompt's claims). Until 1.0.8 unifies collection state across every
# surface (single source of truth: retrieval + prompt + UI), these
# recency-positioned notes make the prompt tell the truth per request.
# rag_collections absent/None (old clients, API users) = everything enabled.
_COLLECTIONS_OFF_NOTES = {
    # NB: never name literal tags here — a small model reads "[MEM_SAVE:]" in a
    # note and starts echoing/inventing tag variants (seen live: [MEM_OBLIT:]).
    MEMORY_COLLECTION: {
        "ca": "NOTA CRÍTICA: L'usuari ha DESACTIVAT la memòria personal. No tens accés a cap record. NO afirmis recordar res de l'usuari, NO prometis desar ni oblidar res, i NO escriguis cap tag de memòria. Si no t'ho pregunten, no en parlis.",
        "es": "NOTA CRÍTICA: El usuario ha DESACTIVADO la memoria personal. No tienes acceso a ningún recuerdo. NO afirmes recordar nada del usuario, NO prometas guardar ni olvidar nada, y NO escribas ningún tag de memoria. Si no te lo preguntan, no lo menciones.",
        "en": "CRITICAL NOTE: The user has DISABLED personal memory. You have no access to any memories. Do NOT claim to remember anything about the user, do NOT promise to save or forget anything, and do NOT write any memory tag. Do not bring it up unless asked.",
    },
    DOCS_COLLECTION: {
        "ca": "NOTA CRÍTICA: L'usuari ha DESACTIVAT la base de coneixement (documentació de server-nexe). NO tens accés a la documentació: si et demanen detalls, digues que la col·lecció està desactivada. NO inventis contingut de la documentació.",
        "es": "NOTA CRÍTICA: El usuario ha DESACTIVADO la base de conocimiento (documentación de server-nexe). NO tienes acceso a la documentación: si piden detalles, di que la colección está desactivada. NO inventes contenido de la documentación.",
        "en": "CRITICAL NOTE: The user has DISABLED the knowledge base (server-nexe documentation). You have NO access to the documentation: if asked for details, say the collection is disabled. Do NOT invent documentation content.",
    },
    KNOWLEDGE_COLLECTION: {
        "ca": "NOTA CRÍTICA: L'usuari ha DESACTIVAT els documents pujats. NO tens accés als seus documents: no en citis ni n'inventis contingut.",
        "es": "NOTA CRÍTICA: El usuario ha DESACTIVADO los documentos subidos. NO tienes acceso a sus documentos: no cites ni inventes su contenido.",
        "en": "CRITICAL NOTE: The user has DISABLED uploaded documents. You have NO access to their documents: do not cite or invent their content.",
    },
}
_ALL_RAG_COLLECTIONS = tuple(_COLLECTIONS_OFF_NOTES)


def _collections_prompt_overrides(lang, rag_collections) -> str:
    """Truth-telling prompt notes for every collection the user switched OFF.

    Appended at the END of the system prompt (recency: small models obey the
    closest instruction). Returns "" when rag_collections is None (all on).
    """
    if rag_collections is None:
        return ""
    _lk = (lang or "en")[:2]
    if _lk not in ("ca", "es", "en"):
        _lk = "en"
    notes = [
        _COLLECTIONS_OFF_NOTES[c][_lk]
        for c in _ALL_RAG_COLLECTIONS
        if c not in rag_collections
    ]
    return ("\n\n" + "\n".join(notes)) if notes else ""


# #850: threshold for switching the sticky language. Short acks and borrowings ("ok
# thanks"=9, "thanks a lot"=12, "merci!"=6) stay below it; a genuine switch is
# a full sentence ("can we switch to English?" >= 25). 2.5x lang_detect's
# _MIN_DETECT_CHARS: the zone where lingua is reliable.
_STICKY_LANG_MIN_SWITCH_CHARS = STICKY_SWITCH_MIN_CHARS  # one constant, core.lang_detect


def _resolve_session_lang(session, user_text: str) -> str:
    """#850: sticky reply language per session (thinking_enabled pattern).

    The CRITICAL directive goes AT THE START of the system prompt: every language
    flip invalidates the prefix from token 0 (a full re-prefill; on llama.cpp,
    a GGUF reload). Policy (tightened by the adversarial review):
    - the 1st REAL detection seeds the sticky; the fallback (NEXE_LANG) is returned
      but NEVER seeded — a guess is not pinned, the 1st real detection will decide.
    - the switch threshold is measured on the NATURAL TEXT (code/URLs stripped):
      "thanks mate https://…" is not a language switch.
    - switch on the 1st clear message (Jordi's decision, 25/09): the 2-turn
      hysteresis was removed when detection started requiring confidence
      (`core.lang_detect._MIN_RELATIVE_DISTANCE`) — noise no longer arrives
      here as a detection, and a genuine switch must not pay a turn of delay.
    - #1143: a short line seeds only the install language, and a language the
      user asks for by name wins at once — `core.lang_detect.decide_reply_lang`,
      the one decision both doors make.
    """
    # #1143: the decision is core.lang_detect.decide_reply_lang, shared with
    # /v1; this door keeps it on the ChatSession.
    lang, new_sticky = decide_reply_lang(getattr(session, "lang", None), user_text)
    if new_sticky and session is not None:
        session.lang = new_sticky
        session.lang_pending = None
    return lang


def _finalize_system_prompt(system_prompt: str, lang: str, rag_collections=None) -> str:
    """Suffixes shared by EVERY turn: collection overrides + the RAG rule.

    #851: the RAG security rule is static and UNCONDITIONAL — any
    conditional suffix splits the prefix-cache namespace
    (identity_hash covers the whole system prompt). The continue branch stays
    coherent as a side effect: it no longer depends on whether the turn carried context.
    """
    # Deferred: `core.endpoints.chat_sanitization` executes `core/endpoints/
    # __init__.py`, which eagerly imports `.v1` -> `.chat` -> this module.
    from core.endpoints.chat_sanitization import append_rag_security_rule

    system_prompt += _collections_prompt_overrides(lang, rag_collections)
    return append_rag_security_rule(system_prompt, lang)



def _build_system_prompt_with_time(
    message: str = "", _now=None, lang_hint: Optional[str] = None, app_state: Any = None
) -> tuple[str, str]:
    """Read system prompt from server.toml, adapt to the user's language and
    inject current datetime.

    Resolves the base prompt (server.toml, via ``_get_system_prompt`` above —
    which lived in the OTHER door's route module until C4.2, and was reached
    from the plugin by an inverted import) and hands it to the shared
    ``core.chat_prompt.build_system_prompt_with_time`` for the date phrase and
    language reinforcement.

    ``app_state`` (C4.2) is the state the door already has on its request; the
    turn's steps pass ``ctx.app_state``. ``None`` falls back to the process
    singleton, which is what every caller did before this parameter existed.
    The two are the same object's config in production: `lifespan.py`
    assigns ``app.state.config = server_state.config``.

    ``lang_hint`` (#850) is always sent by the call site (the sticky
    per-session language); it is required, not detected from ``message``,
    matching the only way this has ever actually been called in production.

    Returns (system_prompt, lang).
    """
    _lang = lang_hint or detect_user_lang(message, fallback=os.getenv("NEXE_LANG", "en"))
    try:
        if app_state is None:
            # Deferred: `core.lifespan` pulls the whole server in, and this
            # module is imported while `core.turn` is still initialising.
            from core.lifespan import get_server_state
            app_state = get_server_state()
        base_system_prompt = _get_system_prompt(app_state, _lang)
    except Exception:
        base_system_prompt = EMERGENCY_SYSTEM_PROMPT
    system_prompt = build_system_prompt_with_time(base_system_prompt, _lang, _now=_now)
    return system_prompt, _lang


def turn_system_prompt(
    *, lang: Optional[str], rag_collections=None, base: Optional[str] = None,
    message: str = "", app_state: Any = None, _now=None,
) -> str:
    """The `system_prompt` step of a turn, at either door (C4.2).

    ``base`` is the system message the CLIENT supplied, when it did: `/v1`
    accepts one and has always used it as-is, so it does NOT get the date
    phrase — only the shared finalisation. Without one, the prompt is built
    from server.toml exactly as `/ui/chat` builds it.

    The door decides `lang` (its own sticky-language store, see the module
    docstring) and `rag_collections` (its own field); everything after that is
    the same for both, which is what makes the collection notes and the RAG
    security rule reach the API door at last.
    """
    if base is None:
        base, _ = _build_system_prompt_with_time(
            message, lang_hint=lang, app_state=app_state, _now=_now,
        )
    return _finalize_system_prompt(base, lang, rag_collections)
