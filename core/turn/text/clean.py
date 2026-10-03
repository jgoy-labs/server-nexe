"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/text/clean.py
Description: The model's whole reply, cleaned (C4.4, moved from routes_chat.py).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re as _re

from core.turn.text.chunks import ANGLE_TAG_RE, PIPE_TAG_RE

# Context headers the model may echo back (compiled once).
CTX_HEADERS_RE = _re.compile(
    # (?:FI\s+)?CONTEXT(?:\s+hex)? covers [CONTEXT], [FI CONTEXT] and the
    # nonce'd B030 variants ([CONTEXT a1b2c3d4], [FI CONTEXT a1b2c3d4]).
    # #1063: DOCUMENT ADJUNTAT only had its Catalan spelling here, unlike every
    # other label above — added ATTACHED DOCUMENT / DOCUMENTO ADJUNTO now that
    # the header itself can be emitted in any of the three. Pre-existing and
    # separate from that fix: `core/turn/assemble.py`'s header line has never
    # carried brackets ("DOCUMENT ADJUNTAT (file):", not "[DOCUMENT ADJUNTAT]"),
    # so this branch does not strip it in ANY language — only a model that
    # echoes the bracketed shape back verbatim is caught. Not closed here.
    r'\[(?:(?:FI\s+)?CONTEXT(?:\s+[0-9a-f]{6,16})?|MEMORIA DE L\'USUARI|MEMORIA DEL USUARIO|'
    # #1124: the Spanish labels end in N (chat_rag.py sends DOCUMENTACION
    # TECNICA); they were never stripped.
    r'USER MEMORY|DOCUMENTACI(?:ÓN?|ON?) DEL SISTEMA|SYSTEM DOCUMENTATION|'
    r'DOCUMENTACI(?:ÓN?|ON?) T[EÈÉ]CNICA|TECHNICAL DOCUMENTATION|'
    r'DOCUMENT ADJUNTAT|ATTACHED DOCUMENT|DOCUMENTO ADJUNTO|'
    # #1144: the note an earlier image leaves in the history (core/turn/image_memory.py).
    r'IMATGE ADJUNTA|IMAGEN ADJUNTA|ATTACHED IMAGE|'
    r'FI DOCUMENT|END DOCUMENT|FIN DOCUMENTO|'
    # #1102: the header of each recalled item, `[Font: personal_memory]`
    # (core/endpoints/chat_rag.py), copied into the answer. Its source is an
    # identifier — a collection, a file, a channel: personal_memory,
    # manual.pdf, chat-cli — so a citation the model writes in words,
    # "[Font: Wikipedia]", is not one.
    # Bounded like the stream's hold (core/turn/text/tags.py), so the two agree.
    r'(?-i:Font): (?=[\w.\-]{1,100}\])[\w.\-]*[_.\-][\w.\-]*|'
    # #1125: the time line in front of every user message (core/chat_prompt.py),
    # and the on-demand clock /v1 still uses, echoed back.
    r'(?:HORA DEL MISSATGE|HORA DEL MENSAJE|MESSAGE TIME|HORA ACTUAL DEL SISTEMA|CURRENT SYSTEM TIME): [^\]\n]{1,80})\]',
    _re.IGNORECASE
)

def is_harmony(text: str) -> bool:
    """True for gpt-oss (harmony) output: channel tags, or the bare shape they
    leave once stripped, which starts with the channel name `analysis` —
    lowercase, as the channel is named, so "Analysis of…" is prose."""
    return "<|channel|>" in text or text.lstrip().startswith("analysis")


def final_section(text: str) -> str:
    """The answer section of a harmony reply (tags already stripped).

    Only called on text `is_harmony` recognised BEFORE its tags were
    stripped. The cut used to run on every reply and searched for "final"
    anywhere, so a reply lost everything before the word: "Primer rega.
    Finalment, adoba." → "ment, adoba." (#1093). Inside the analysis channel
    the last `assistant final` wins over a "final" in the reasoning.
    """
    stripped = text.strip()
    _last = None
    for _last in _re.finditer(r'assistant\s*final\s*', stripped, _re.IGNORECASE):
        pass
    if _last is not None:
        return stripped[_last.end():].strip()
    _m = _re.search(r'final\s*([\s\S]+)$', stripped, _re.IGNORECASE)
    if _m:
        return _m.group(1).strip()
    return _re.sub(r'^analysis\s*', '', stripped, flags=_re.IGNORECASE).strip()


_THINK_TAG_RE = _re.compile(r"</?think>")


def strip_think_blocks(text: str) -> str:
    """Remove every closed <think>…</think> block, NESTED ones included.

    A model that reasons about a text containing "<think>" quotes the tags
    inside its own block. The old non-greedy regex closed the block at the
    first quoted "</think>" and the rest of the reasoning reached the reply
    (seen live on /v1 with Qwen3.5 on MLX, 24/09). Depth counts now. As
    before: the whitespace after a block goes with it, and an UNCLOSED block
    is left as it is (a starved reply is #984's to close).
    """
    out: list[str] = []
    depth, last, start = 0, 0, 0
    for m in _THINK_TAG_RE.finditer(text):
        if m.group() == "<think>":
            if depth == 0:
                out.append(text[last:m.start()])
                start = m.start()
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                last = m.end()
                while last < len(text) and text[last].isspace():
                    last += 1
    out.append(text[start:] if depth else text[last:])
    return "".join(out)


def clean_model_text(text: str) -> str:
    """The model's answer, with everything else it wrote removed.

    C4.4: ONE cleaner where there were three — the UI's streaming one, its
    non-streaming one and the compactor's — so a reply is cleaned the same
    way whichever path it took. The union of the three: none of their
    patterns is dropped (tests/core/turn/text/test_clean_union.py).
    """
    text = strip_think_blocks(text)
    # the compactor's: a <|thinking|> PAIR goes with its content
    text = _re.sub(r"<\|thinking\|>[\s\S]*?<\|/thinking\|>\s*", "", text)
    harmony = is_harmony(text)
    text = PIPE_TAG_RE.sub('', text)
    text = ANGLE_TAG_RE.sub('', text)
    text = final_section(text) if harmony else text.strip()
    # #1124: a source caption that only held labels goes with them — through
    # the stream's own filter, so the stored reply is what the screen showed.
    # Deferred: captions.py imports this module.
    from core.turn.text.captions import drop_source_captions

    text = drop_source_captions(text)
    return CTX_HEADERS_RE.sub('', text).strip()


def clean_full_response(full_response: str, user_input: str = "") -> tuple[str, list, list]:
    """Clean the full response and extract MEM_SAVE and MEM_DELETE tags.

    Returns (clean_response, mem_saves, mem_deletes).
    The PENDING_DELETE yield must be done by the caller.
    """
    # Deferred: importing core.memory_facts runs its package __init__, which
    # reaches core.endpoints and back here — a cycle if this module is first.
    from core.memory_facts import extract as memory_extract

    clean_response = clean_model_text(full_response)
    # C3.2: reading the model's memory tags is the core's job now — the same
    # reading /v1 does, so a tag means the same thing at both doors.
    return memory_extract.extract_memory_tags(clean_response, user_input=user_input)


# Placeholder persisted for a think-only assistant turn (B125).
THINK_ONLY_PLACEHOLDER = "…"


def think_only_placeholder(clean_response: str, full_response: str) -> str:
    """B125: keep an assistant turn even when the model produced only thinking.

    When the model emits a turn that cleans down to nothing (e.g. think-only
    output), no assistant message gets persisted. ``get_context_messages()``
    then sees two consecutive ``user`` turns and drops the newer one as a
    duplicate role — silently losing the user's next message. Returning a
    placeholder keeps the user/assistant alternation intact.

    A genuinely empty turn (``full_response`` empty, e.g. an upstream
    exception) is left untouched so nothing spurious is saved.
    """
    if not clean_response and full_response:
        return THINK_ONLY_PLACEHOLDER
    return clean_response
