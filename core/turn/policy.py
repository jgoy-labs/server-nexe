"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/policy.py
Description: Product decisions about a turn, in the core (ADR-007 C3.5, C4.5).

Not mechanics: choices. Whether a turn that cleaned down to nothing but
[MEM_SAVE:] tags earns a second LLM call (D3), what the model is told when it
gets one, and what the user reads when it does not. They lived inside the web
UI plugin, so /v1 answered such a turn with an empty body while /ui/chat
re-prompted — the same model output, two different products.

C4.5 (26/09): the second call is SPENT here too. Until now each door kept its
own generator for it (`_yield_reprompt` in the plugin, nothing at /v1): one
counted the call twice, one never, and both ran it outside the engine gate,
after `generate` had given its slot back. `reprompt_chunks` is the one place
that decides, takes a slot, filters the model's second answer and counts the
call (I8) — only when an engine was really asked. What stays at each door is
`call`: how THAT door reaches its engine, which is exactly what the core must
not know about.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import os as _os
import re as _re
import time
from typing import Any, AsyncIterator, Callable, Optional

from core.turn.budget import record_llm_call
from core.turn.context import TurnContext
from core.turn.gate import GateBusy, Priority, _gate_wait_s, gate_for
from core.turn.stream import StreamGuard
from core.turn.text import think as text_think

logger = logging.getLogger(__name__)

REPROMPT_OVERRIDE = {
    "ca": "\n\nIMPORTANT: La memòria ja s'ha guardat correctament. Ara respon de forma natural al missatge de l'usuari. NO emetis [MEM_SAVE:] — ja està fet. Simplement conversa.",
    "es": "\n\nIMPORTANTE: La memoria ya se ha guardado correctamente. Ahora responde de forma natural al mensaje del usuario. NO emitas [MEM_SAVE:] — ya está hecho. Simplemente conversa.",
    "en": "\n\nIMPORTANT: Memory has been saved successfully. Now respond naturally to the user's message. Do NOT emit [MEM_SAVE:] tags — already done. Just have a normal conversation.",
}

#: A tag the model repeats in its SECOND answer is noise, never a new fact:
#: the facts were read from the first one, before the re-prompt was decided.
_MEM_SAVE_TAG_RE = _re.compile(r"\[MEM_SAVE:[^\[\]\n\r\t]{1,250}\]")


def reprompt_system_prompt(system_prompt: str, lang: Optional[str]) -> str:
    """The turn's system prompt plus the override, in the turn's language."""
    short = (lang or "ca")[:2]
    return system_prompt + REPROMPT_OVERRIDE.get(short, REPROMPT_OVERRIDE["en"])


def empty_reply_text(lang: Optional[str]) -> str:
    """What the user reads when the model wrote only tags and no second reply
    came — the re-prompt is off, the engine was busy, or its second answer was
    empty too.

    Decision of 26/09 (C4.5): a neutral, translated acknowledgement. The text
    this replaces — «Memòria desada: X» — was built from the model's tags
    BEFORE `memory.write` ran, so it called "saved" a fact the server could
    still refuse (the same lie #1098 removed from the badge), and it spoke
    Catalan whatever the conversation's language. What memory kept is said by
    the server's own note, `[MEM:n:facts]`, and nowhere else.
    """
    # Deferred: importing core.memory_facts runs its package __init__, which
    # reaches core.endpoints and back into core.turn — a cycle if this module
    # is the first one loaded (same reason `core/turn/text/clean.py` defers).
    from core.memory_facts.intent_texts import text as _t

    return _t("reply.ack", lang=lang)


ENV_REPROMPT_IF_ONLY_MEMSAVE = "NEXE_REPROMPT_IF_ONLY_MEMSAVE"


def reprompt_enabled() -> bool:
    """D3 (ADR-007 §6, C2.5): whether a turn that cleaned down to ONLY
    [MEM_SAVE: ...] gets a second LLM call trying for a real conversational
    reply (`reprompt_chunks`), or goes straight to the neutral acknowledgement
    (`empty_reply_text`). A product decision, not a bug fix — default ON keeps
    today's behaviour; OFF trades the extra call for a plainer UX. Read fresh
    each call (no caching): a runtime toggle takes effect on the next turn,
    same as every other env-backed switch in this codebase.
    """
    raw = _os.environ.get(ENV_REPROMPT_IF_ONLY_MEMSAVE, "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


#: How a door asks its engine once more: it receives the system prompt with the
#: override and returns the engine's raw chunks (dicts or strings, the shapes
#: `text_think.extract_reprompt_chunk_content` reads) — or None when this door
#: cannot call this engine again (the web door's MLX/llama.cpp path runs through
#: a queue and a worker thread that was never wired for a second call).
RepromptCall = Callable[[str], Optional[AsyncIterator[Any]]]


async def reprompt_chunks(
    ctx: TurnContext,
    facts: list,
    *,
    call: Optional[RepromptCall],
    engine_name: str,
    model: Optional[str],
) -> AsyncIterator[str]:
    """The second LLM call of a turn that produced only [MEM_SAVE:] tags,
    yielded as clean text chunks (no reasoning, no tags) — D3, one policy for
    every door (C4.5).

    Yields nothing when: there is nothing to confirm, the flag is off, no
    engine slot is free within the gate's wait, or the door cannot call this
    engine again. The caller reads an empty result as "no second reply" and
    falls back to `empty_reply_text`. Errors from the engine end the stream
    quietly (logged), as the door generators always did.

    Two things the doors used to get wrong live here now, measured 26/09:

    * The call runs INSIDE the engine gate. `generate` has already released
      its slot when `postprocess` runs, so this takes one again, like the
      atomiser does (`_atomiser_slot`) — two doors re-prompting at once no
      longer means two generations on one GPU.
    * I8 counts the call only when an engine was really asked. The streaming
      door counted it whenever the reply was empty and had facts (even with
      the flag off, even when the shape check skipped the engine); the JSON
      door never counted it. Now: one entry, step "reprompt", with the model.
    """
    facts = _facts_to_confirm(facts)
    if not facts or not reprompt_enabled():
        return
    if ctx.resume:
        # C4.6: the answer being resumed is mid-sentence; a second generation
        # would open a new assistant turn inside it. Nothing to confirm with.
        return
    if call is None:
        logger.info("Re-prompt skipped: %s has no way to call its engine again from this door", engine_name)
        return
    gate = gate_for(ctx.app_state)
    slot = await _take_slot(gate, ctx.turn_id)
    if slot is None:
        return
    started = time.monotonic()
    asked = False
    produced = 0
    try:
        stream = call(reprompt_system_prompt(ctx.system_prompt, ctx.lang))
        if stream is None:
            logger.info("Re-prompt skipped: %s cannot be called again by this door (engine shape)", engine_name)
            return
        asked = True
        logger.info("Re-prompt: empty after MEM_SAVE, re-calling %s", model or engine_name)
        async for content in _visible_text(stream):
            produced += len(content)
            yield content
    except Exception as exc:
        logger.warning("Re-prompt failed: %s", exc)
    finally:
        if asked:
            record_llm_call(
                ctx, step="reprompt", engine=engine_name, model=model,
                ms=(time.monotonic() - started) * 1000.0,
            )
            logger.info("Re-prompt done: %d chars back from %s", produced, model or engine_name)
        await gate.release(slot)


def second_answer_text(parts: list) -> str:
    """The second answer as one text, with the tags a model repeats removed.

    `reprompt_chunks` strips a tag per chunk, which is what the streaming wire
    can do; a tag split across chunks ("[MEM_SAVE: el color" / " preferit…]")
    survives that and, live on 26/09 (gemma4:e4b, second answer = the tag
    again), reached the JSON client raw. The joined text is where the whole tag
    is visible — so whatever is left after this is what the user reads, or ""
    and the caller falls back to `empty_reply_text`.
    """
    text = _MEM_SAVE_TAG_RE.sub("", "".join(parts))
    text = _re.sub(r"\[MEM_DELETE:[^\[\]\n\r\t]{1,250}\]", "", text)
    return text.strip()


def _facts_to_confirm(facts: list) -> list:
    """The tags worth a second call: non-empty, stripped."""
    return [f.strip() for f in facts if f and f.strip()]


async def _take_slot(gate, turn_id: str):
    """A USER_TURN slot for the second call, or None when the gate stays busy
    for the whole wait — then there is no second call, and nothing to count."""
    try:
        return await gate.acquire(Priority.USER_TURN, holder=turn_id, timeout=_gate_wait_s())
    except GateBusy:
        logger.info("Re-prompt skipped: no engine slot free for turn %s", turn_id)
        return None


async def _visible_text(stream) -> AsyncIterator[str]:
    """The engine's raw chunks as text the user may see: thinking-only chunks
    dropped, <think> blocks filtered across chunk boundaries (B124), a tag the
    model repeats removed. Whatever shape the door's engine speaks.

    #1039: the second answer never passes through `engine_events`, so it gets
    the same guard here — no control characters, and a runaway reply ends at
    the ceiling (the caller logs it and falls back like any failed re-prompt)."""
    in_think = False
    guard = StreamGuard()
    async for raw in stream:
        content, skip = text_think.extract_reprompt_chunk_content(raw)
        if skip:
            continue
        content, _ = guard.take(content, "")
        content, in_think = text_think.filter_reprompt_think_tags(content, in_think)
        if in_think:
            continue
        content = _MEM_SAVE_TAG_RE.sub("", content)
        if content:
            yield content
