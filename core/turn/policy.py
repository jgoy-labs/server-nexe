"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/policy.py
Description: Product decisions about a turn, in the core (ADR-007 C3.5).

Not mechanics: choices. Whether a turn that cleaned down to nothing but
[MEM_SAVE:] tags earns a second LLM call (D3), what the model is told when it
gets one, and what the user reads when it does not. They lived inside the web
UI plugin, so /v1 answered such a turn with an empty body while /ui/chat
re-prompted — the same model output, two different products.

The generators that SPEND the second call stay at each door: they talk to that
door's engine and write to that door's wire, which is exactly what the core
must not know about.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os as _os

REPROMPT_OVERRIDE = {
    "ca": "\n\nIMPORTANT: La memòria ja s'ha guardat correctament. Ara respon de forma natural al missatge de l'usuari. NO emetis [MEM_SAVE:] — ja està fet. Simplement conversa.",
    "es": "\n\nIMPORTANTE: La memoria ya se ha guardado correctamente. Ahora responde de forma natural al mensaje del usuario. NO emitas [MEM_SAVE:] — ya está hecho. Simplemente conversa.",
    "en": "\n\nIMPORTANT: Memory has been saved successfully. Now respond naturally to the user's message. Do NOT emit [MEM_SAVE:] tags — already done. Just have a normal conversation.",
}


def mem_save_fallback_text(mem_saves: list) -> str:
    """Confirmation shown when a turn cleans down to ONLY [MEM_SAVE: ...].

    #856: both chat paths need the exact same text — the streaming path
    (re-prompt → this fallback) and the non-streaming one, which used to strip
    the tag unconditionally and answer 200 with an EMPTY body. Single source so
    the two can never drift again.

    Returns "" when there is nothing to confirm: no facts, no fabricated text.
    """
    facts = [f.strip() for f in mem_saves if f and f.strip()]
    if not facts:
        return ""
    return "Memòria desada: " + ", ".join(facts)


ENV_REPROMPT_IF_ONLY_MEMSAVE = "NEXE_REPROMPT_IF_ONLY_MEMSAVE"


def reprompt_enabled() -> bool:
    """D3 (ADR-007 §6, C2.5): whether a turn that cleaned down to ONLY
    [MEM_SAVE: ...] gets a second LLM call trying for a real conversational
    reply (`_yield_reprompt`), or goes straight to the canned confirmation
    (`_mem_save_fallback_text`). A product decision, not a bug fix — default
    ON keeps today's behaviour; OFF trades the extra call for a plainer UX.
    Read fresh each call (no caching): a runtime toggle takes effect on the
    next turn, same as every other env-backed switch in this codebase.
    """
    raw = _os.environ.get(ENV_REPROMPT_IF_ONLY_MEMSAVE, "true").strip().lower()
    return raw not in ("0", "false", "no", "off")
