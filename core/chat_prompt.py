"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/chat_prompt.py
Description: System prompt time assembly shared by /v1 and /ui/chat (F-D
             blocks 1-2): the natural-language date phrase for the system
             prompt, the on-demand clock line for a single turn, and the
             orchestrator that appends both to an already-resolved base
             prompt. Previously duplicated only on the UI path — /v1 had
             neither, so an API conversation never knew today's date and
             could not answer "what time is it".

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re as _re

from core.lang_detect import append_language_reminder, prepend_language_directive

# Bug B iter-2 (2026-05-21 nit): natural-language date phrase localised
# to the user's language. Replaces the iter-1 "Now: Thursday 2026-05-21
# ..." technical header, which small MLX models (Qwen3-4B-4bit empirically
# returned date -1 and omitted the weekday) interpreted as metadata rather
# than a fact to copy. A natural conversational phrase is much more likely
# to be reproduced verbatim by the model. Hardcoded maps (no setlocale)
# keep this thread-safe under asyncio interleaving.
WEEKDAYS_BY_LANG: dict[str, list[str]] = {
    "ca": ["dilluns", "dimarts", "dimecres", "dijous", "divendres", "dissabte", "diumenge"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
MONTHS_BY_LANG: dict[str, list[str]] = {
    # Index 0 is an empty sentinel — datetime.month is 1..12.
    "ca": ["", "gener", "febrer", "març", "abril", "maig", "juny",
           "juliol", "agost", "setembre", "octubre", "novembre", "desembre"],
    "es": ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
           "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "en": ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}
DATE_PHRASE_BY_LANG: dict[str, str] = {
    # B007: DAY granularity only — the phrase lives inside the system prompt,
    # which is the head of every tokenized prompt. Any faster-changing value
    # (hh:mm:ss) makes identity_hash and the token prefix change every second,
    # so no prefix cache (MLX trie/VLM state, llama.cpp ModelPool, Ollama's
    # internal cache) can ever hit. Clock questions are answered on demand via
    # time_context_line() injected into that single turn instead.
    "ca": "Avui és {dow}, {day} de {month} de {year}.",
    "es": "Hoy es {dow}, {day} de {month} de {year}.",
    "en": "Today is {dow}, {month} {day}, {year}.",
}

# B007/D-A: the current time is read from the system ONLY when the user asks
# for it, and travels inside that turn's user message (ephemeral — the session
# persists the raw message, so the cache diverges only on that turn).
TIME_INTENT_RE = _re.compile(
    r"(quina\s+hora|hora\s+(és|es\s+ara|tenim)"
    r"|qu[eé]\s+hora"
    r"|what(\s+is|'s)?\s+the\s+time|what\s+time|current\s+time)",
    _re.IGNORECASE,
)
TIME_PHRASE_BY_LANG: dict[str, str] = {
    "ca": "[Hora actual del sistema: {hm} ({tz}) — llegida ara mateix]",
    "es": "[Hora actual del sistema: {hm} ({tz}) — leída ahora mismo]",
    "en": "[Current system time: {hm} ({tz}) — read just now]",
}


def time_context_line(message: str, lang: str, _now=None) -> str:
    """Return a one-line current-time note when the user asks the time, else ''.

    Injected as a prefix of that turn's user message (never the system prompt),
    so the prefix cache only diverges on the turn that actually needs the clock.
    """
    if not message or not TIME_INTENT_RE.search(message):
        return ""
    if _now is None:
        from datetime import datetime as _dt
        _now = _dt.now().astimezone()
    base = lang if lang in TIME_PHRASE_BY_LANG else "en"
    return TIME_PHRASE_BY_LANG[base].format(
        hm=_now.strftime("%H:%M"), tz=_now.strftime("%Z")
    )


def format_now_natural(_now, _lang: str) -> str:
    """Build a natural-language date phrase in the user's language.

    Normalises BCP-47 variants (``ca-ES`` → ``ca``, ``en-US`` → ``en``) to
    match how the rest of the chat pipeline resolves language. Unknown
    languages fall back to English. ``_now`` must be a timezone-aware
    ``datetime`` (caller already does ``.astimezone()``).
    """
    base = _lang.split("-")[0].lower() if _lang else "en"
    if base not in DATE_PHRASE_BY_LANG:
        base = "en"
    dow = WEEKDAYS_BY_LANG[base][_now.weekday()]
    month = MONTHS_BY_LANG[base][_now.month]
    # B007: day granularity only — no time-of-day here, ever (see the guard
    # test test_b007_system_prompt_stable.py; the clock goes via
    # time_context_line on demand).
    return DATE_PHRASE_BY_LANG[base].format(
        dow=dow,
        day=_now.day,
        month=month,
        year=_now.year,
    )


# #1022: the last-resort system prompt, when no configured one can be reached.
# It lived twice, and the two copies had drifted: /v1 said "an AI assistant"
# and /ui/chat said "a local AI assistant". The local wording wins — every
# engine server-nexe can serve (MLX, llama.cpp, Ollama) runs on the machine,
# so it is the true one of the two, and it is the one that keeps a model from
# offering to look something up on the web. The two fallbacks are nested
# rather than parallel: this is what `_get_system_prompt` returns when
# server.toml configures no prompt, AND what the UI falls back to when
# `_get_system_prompt` itself cannot be reached at all.
EMERGENCY_SYSTEM_PROMPT = "You are Nexe, a local AI assistant. Respond clearly and helpfully."


def build_system_prompt_with_time(base_system_prompt: str, lang: str, _now=None) -> str:
    """Append the language directive and today's date to a resolved base prompt.

    F-D blocks 1-2: shared by ``/v1`` (``core.endpoints.chat``) and
    ``/ui/chat`` (``plugins.web_ui_module``) — both already resolve the
    turn's reply language before calling this (sticky-language, #850/#854),
    so this takes the final ``lang``, not a message to detect it from.

    Returns the finished system prompt (language directive + base + date +
    a recency-reinforced language reminder at the end — small models obey
    the instruction closest to generation).
    """
    prompt = prepend_language_directive(base_system_prompt, lang)
    if _now is None:  # injectable clock for tests (B007 stability guard)
        from datetime import datetime as _dt
        _now = _dt.now().astimezone()
    # The datetime phrase only has ca/es/en variants; use 'en' for other langs.
    date_lang = lang if lang in ("ca", "es", "en") else "en"
    prompt = prompt + "\n\n" + format_now_natural(_now, date_lang)
    prompt = append_language_reminder(prompt, lang)
    return prompt


__all__ = [
    "EMERGENCY_SYSTEM_PROMPT",
    "WEEKDAYS_BY_LANG",
    "MONTHS_BY_LANG",
    "DATE_PHRASE_BY_LANG",
    "TIME_INTENT_RE",
    "TIME_PHRASE_BY_LANG",
    "time_context_line",
    "format_now_natural",
    "build_system_prompt_with_time",
]
