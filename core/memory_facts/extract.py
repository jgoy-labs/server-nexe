"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/extract.py
Description: The memory tags a model emits, read in the core (ADR-007 C3.2).

A model marks what it wants remembered with [MEM_SAVE: ...] and what it wants
forgotten with [MEM_DELETE: ...] (plus the variants some models emit instead).
Reading them was the web UI's alone: through /v1 the tags reached the client
raw and nothing was ever stored. This module is that reading, for both doors.

What did NOT move: the model-format cleanup (<think>, harmony tags, the
analysis/final split). That is the UI's own postprocessing and belongs to C4.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import re as _re
import tomllib
from functools import lru_cache
from pathlib import Path

from core.log_redact import redact_user_content

logger = logging.getLogger(__name__)

MEM_SAVE_MAX_LEN = 200
MEM_SAVE_MIN_LEN = 5

# Whitelist: unicode letters, digits, spaces, and safe punctuation ( . , ; : ! ? ' " - + / = % $ € @ # & ( ) )
_MEM_SAVE_ALLOWED_CHARS = _re.compile(
    r"^[\w\s\.\,\;\:\!\?\'\"\-\+\/\=\%\$\€\@\#\&\(\)]+$",
    _re.UNICODE,
)
# Explicit forbidden characters (additional defense)
_MEM_SAVE_FORBIDDEN = _re.compile(r"[\x00-\x1f\x7f<>\[\]\{\}\|`\\]")
# Strict format: must start with [MEM_SAVE: and end with ] without nested bracket
_MEM_SAVE_STRICT_RE = _re.compile(r'\[MEM_SAVE:\s*([^\[\]\n\r\t]{1,250})\]')
# Bug B-mem-visible: gpt-oss:20b emits [MEMORIA: ...] instead of [MEM_SAVE: ...].
# We normalize [MEMORIA: ...] → [MEM_SAVE: ...] in clean_response to process them
# as normal MEM_SAVEs, and strip them from visible output so the user doesn't see them.
_MEMORIA_RE = _re.compile(r'\[MEMORIA:\s*([^\[\]\n\r\t]{1,250})\]', _re.IGNORECASE)

# ─── Bug 18 — MEM_DELETE tag extractor ────────────────────────────────────────
# Format: [MEM_DELETE: <text>] — the model emits this tag when the user asks
# to forget a fact. The pipeline extracts it, calls delete_from_memory(), and strips
# it from the visible response. Fallback if intent detection from the message fails.
_MEM_DELETE_RE = _re.compile(r'\[MEM_DELETE:\s*([^\[\]\n\r\t]{1,250})\]')
# Normalize variants: [OLVIDA: ...], [OBLIT: ...] → [MEM_DELETE: ...]
_OBLIT_RE = _re.compile(r'\[(OLVIDA|OBLIT|FORGET):\s*([^\[\]\n\r\t]{1,250})\]', _re.IGNORECASE)

# ─── #1135 — an example from the instructions is not a fact ──────────────────
# The persona prompt (personality/server.toml) teaches the tags by example:
# `[MEM_DELETE: descripció del fet]`, `[MEM_DELETE: L'usuari es diu ‹nom›]`,
# `[MEM_SAVE: ...]`. Asked how it works, a model explains them — and the quote
# reached the server as a real tag (live 03/10: `[MEM_DELETE: ...]` armed the
# dialog, and the 0.20 delete search offered whichever entry came closest).
# Models quote loosely, so matching the literal examples is not enough
# (review 03/10: «L'usuari es diu ...», «el fet», «the fact» all passed). A
# content names no fact when it has no letter or digit, carries a template
# slot (‹nom›, <name>, a lone «...», {nom}), is made only of template words,
# or is one of the prompt's own examples with its slot left unfilled. The
# examples are read from server.toml, not copied: one added there is covered.
_SLOT = object()
_WORD_RE = _re.compile(r"[^\W_]+")
_EXAMPLE_SLOT_RE = _re.compile(r"‹[^›]*›|<[^<>]*>")
_TEMPLATE_SLOT_RE = _re.compile(
    r"[‹›]"                                  # ‹nom›: guillemets only ever mark a slot
    r"|<\s*[^\W\d_]\w*\s*>"                # <name> — not «<3» or «Python > Java»
    r"|(?:^|\s)(?:\.{2,}|…)(?=\s|$)"        # a lone «...» standing for the fact
)
_DECORATED_WORD_RE = _re.compile(r"[{«(\[“\"]\s*([^\W\d_]+)\s*[}»)\]”\"]")
_TEMPLATE_WORDS = frozenset({
    # the generic nouns of the examples and of «Vols que esborri '[fet concret]'?»
    "fet", "fets", "descripció", "descripcio", "concret", "concreta", "complet", "completa",
    "hecho", "hechos", "descripción", "descripcion", "concreto", "completo",
    "fact", "facts", "description", "specific", "full", "complete",
    # the slots of the examples, without their marks
    "nom", "edat", "lloc", "nombre", "edad", "lugar", "name", "age", "place",
    # what holds them together
    "el", "la", "els", "les", "los", "las", "un", "una", "l", "d", "del", "de",
    "the", "a", "an", "of", "to", "delete", "forget", "save", "user", "usuari", "usuario",
})


def _is_template_word(word: str) -> bool:
    return word in _TEMPLATE_WORDS or (len(word) == 1 and word.isalpha())


def _example_tokens(example: str) -> list:
    """`L'usuari té ‹edat› anys` → ["l", "usuari", "té", _SLOT, "anys"]."""
    tokens: list = []
    for i, part in enumerate(_EXAMPLE_SLOT_RE.split(example.casefold())):
        if i:
            tokens.append(_SLOT)
        tokens.extend(_WORD_RE.findall(part))
    return tokens


@lru_cache(maxsize=1)
def _example_skeletons() -> tuple:
    """The prompt's tag examples that have a slot, as token patterns."""
    path = Path(__file__).resolve().parents[2] / "personality" / "server.toml"
    try:
        prompts = tomllib.loads(path.read_text(encoding="utf-8"))["personality"]["prompt"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Memory tags: cannot read the prompt's examples (%s); the generic rules still apply", exc)
        return ()
    found = set()
    for prompt in (v for v in prompts.values() if isinstance(v, str)):
        for example in _re.findall(r"\[(?:MEM_SAVE|MEM_DELETE):\s*([^\[\]\n]*)\]", prompt):
            if _EXAMPLE_SLOT_RE.search(example):
                found.add(tuple(_example_tokens(example)))
    return tuple(found)


def _slot_fillers(pattern: tuple, words: list):
    """What fills each slot when `words` follows `pattern` (a slot takes 0–3
    words), or None when it does not follow it."""
    if not pattern:
        return [] if not words else None
    head, rest = pattern[0], pattern[1:]
    if head is _SLOT:
        for n in range(min(3, len(words)) + 1):
            tail = _slot_fillers(rest, words[n:])
            if tail is not None:
                return [words[:n], *tail]
        return None
    return _slot_fillers(rest, words[1:]) if words and words[0] == head else None


def _is_an_unfilled_example(words: list) -> bool:
    for pattern in _example_skeletons():
        fillers = _slot_fillers(pattern, words)
        if fillers is not None and all(_is_template_word(w) for f in fillers for w in f):
            return True
    return False


def is_example_not_fact(text: str) -> bool:
    """True when a memory tag's content is a placeholder taught by the
    instructions, not something the user said (#1135)."""
    folded = (text or "").casefold()
    words = _WORD_RE.findall(folded)
    if _TEMPLATE_SLOT_RE.search(folded):
        return True
    if any(m.group(1) in _TEMPLATE_WORDS for m in _DECORATED_WORD_RE.finditer(folded)):
        return True
    # «el fet», «the fact», «nom» — and no word at all («-», «?!»): all of
    # nothing is template, on purpose.
    if all(_is_template_word(w) for w in words):
        return True
    return _is_an_unfilled_example(words)  # «L'usuari es diu nom» / «… X» / «… »


# ─── #1135 — a tag inside code is a quotation ────────────────────────────────
# Asked how its memory works, the 9B showed the format with the user's real
# name: «El format és: `[MEM_SAVE: L'usuari es diu Jordi]`» (live 03/10; the
# web showed «El format és: ``.» once the tag was stripped). Code formatting
# is the model saying "this is what it looks like", not "do it": the tag is
# not run, and the span goes with it.
#: Review 04/10: `~~~` fences, a fence the model never closed (CommonMark: it
#: runs to the end), and ``double`` backticks are code too.
_CODE_SPAN_RE = _re.compile(r"```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)|``[^`\n]+``|`[^`\n]+`", _re.DOTALL)
_EMPTY_FENCE_RE = _re.compile(r"(?:```|~~~)[\w+-]*")
_ANY_MEM_TAG_RE = _re.compile(
    r"\[(?:MEM_SAVE|MEM_DELETE|MEMORIA|OBLIT|OLVIDA|FORGET)\s*:[^\[\]\n\r\t]{0,250}\]", _re.IGNORECASE,
)


def _drop_quoted_tags(text: str) -> str:
    def _unquote(m):
        span = m.group(0)
        if not _ANY_MEM_TAG_RE.search(span):
            return span
        logger.info("Memory tag inside code: a quotation, not executed (#1135)")
        rest = _ANY_MEM_TAG_RE.sub("", span)
        return "" if not _EMPTY_FENCE_RE.sub("", rest).strip("`~ \n") else rest
    return _CODE_SPAN_RE.sub(_unquote, text)


_UNKNOWN_MEM_TAG_RE = _re.compile(
    r'\[(?:MEM|MEMORIA)_?[A-Z_]{2,24}:\s*[^\[\]\n\r\t]{0,250}\]\s*'
)


def _strip_unknown_mem_tags(text: str) -> str:
    """Remove residual invented memory tags from the visible response."""
    def _log_and_drop(m):
        logger.info("Unknown memory tag stripped (not executed): %s",
                    redact_user_content(m.group(0)[:80]))
        return ""
    return _UNKNOWN_MEM_TAG_RE.sub(_log_and_drop, text).strip()

_ATOMIC_SUBJECT_CA = _re.compile(r"^(L'usuari[a]?|El usuari[a]?)\s+", _re.IGNORECASE)
_ATOMIC_SUBJECT_ES = _re.compile(r"^(El usuario|La usuaria)\s+", _re.IGNORECASE)
_ATOMIC_SUBJECT_EN = _re.compile(r"^(The user|User)\s+", _re.IGNORECASE)
# Verbs that start a NEW PREDICATE — distinguish "i té 8 anys" (split) from "i els macarrons" (list)
_ATOMIC_SPLIT_CA = _re.compile(
    r"\s+i\s+(?=(?:té|es diu|li agrada|li agraden|viu|treballa|estudia|és|fa|ha|parla|prefereix|utilitza|coneix|vol|sap|necessita|juga|llegeix|escriu|porta)\b)",
    _re.IGNORECASE,
)
_ATOMIC_SPLIT_ES = _re.compile(
    r"\s+y\s+(?=(?:tiene|se llama|le gusta|le gustan|vive|trabaja|estudia|es|hace|ha|habla|prefiere|utiliza|conoce|quiere|sabe|necesita|juega|lee|escribe|lleva)\b)",
    _re.IGNORECASE,
)
_ATOMIC_SPLIT_EN = _re.compile(
    r"\s+and\s+(?=(?:is|has|lives|works|studies|likes|prefers|uses|knows|speaks|understands|plays|reads|writes|does|wants|needs|wears)\b)",
    _re.IGNORECASE,
)


def _split_atomic_fact(fact: str) -> list:
    """Split a combined MEM_SAVE fact into atomic facts when safe to do so.

    Example: "L'usuari es diu Aran i té 8 anys"
         →  ["L'usuari es diu Aran", "L'usuari té 8 anys"]
    Non-split: "L'usuari li agrada la vainilla i els macarrons"  (list, not two predicates)
    """
    for split_re, subject_re in (
        (_ATOMIC_SPLIT_CA, _ATOMIC_SUBJECT_CA),
        (_ATOMIC_SPLIT_ES, _ATOMIC_SUBJECT_ES),
        (_ATOMIC_SPLIT_EN, _ATOMIC_SUBJECT_EN),
    ):
        m = subject_re.match(fact)
        if not m:
            continue
        parts = split_re.split(fact)
        if len(parts) < 2:
            continue
        subject = m.group(1)
        result = []
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            if i > 0 and not subject_re.match(part):
                part = f"{subject} {part}"
            result.append(part)
        if len(result) >= 2:
            return result
    return [fact]


def _is_valid_mem_save_text(text: str, user_input: str = "") -> bool:
    """
    Bug 17 — Strictly validates the text of a MEM_SAVE extracted from the LLM.

    Args:
        text: content between [MEM_SAVE: ...]
        user_input: original user message — if MEM_SAVE is exactly the same
                    we treat it as suspicious (probable echo/injection)

    Returns:
        True if safe to save, False if it should be rejected.
    """
    if not isinstance(text, str):
        return False
    text = text.strip()
    if not text:
        return False
    if len(text) < MEM_SAVE_MIN_LEN or len(text) > MEM_SAVE_MAX_LEN:
        return False
    # #1135: "[MEM_SAVE: descripció completa]" quoted from the instructions
    # was stored as a memory (measured 03/10: five of the save examples).
    if is_example_not_fact(text):
        return False
    # No newline, tab, control char or bracket
    if _MEM_SAVE_FORBIDDEN.search(text):
        return False
    # Character whitelist
    if not _MEM_SAVE_ALLOWED_CHARS.match(text):
        return False
    return not _is_injection_or_echo(text, user_input)


_INJECTION_KEYWORDS = (
    'mem_save', 'system prompt', 'ignore previous',
    'ignore all previous', 'override instruction',
    '<script', 'javascript:', 'onerror=', 'onload=',
)


def _is_injection_or_echo(text: str, user_input: str) -> bool:
    """Bug 17: an injection keyword, or the user's message echoed back as the
    fact (the LLM repeating the prompt) — out of _is_valid_mem_save_text so it
    stays under the complexity gate (#1135 added a check there)."""
    _lowered = text.lower()
    if any(kw in _lowered for kw in _INJECTION_KEYWORDS):
        return True
    _user_clean = (user_input or "").strip().lower()
    return bool(_user_clean) and (
        _lowered == _user_clean or (len(_user_clean) > 10 and _user_clean in _lowered)
    )


def _extract_safe_mem_saves(text: str, user_input: str = "") -> list:
    """
    Bug 17 — Safely extracts and validates all [MEM_SAVE: ...] from a text.
    Applies atomicity splitting: [MEM_SAVE: X i Y] → [X, Y] when Y is a new predicate.

    Returns:
        List of valid strings to save (potentially empty).
    """
    if not isinstance(text, str) or not text:
        return []
    matches = _MEM_SAVE_STRICT_RE.findall(text)
    result = []
    for m in matches:
        m = m.strip()
        if not _is_valid_mem_save_text(m, user_input):
            continue
        for atomic in _split_atomic_fact(m):
            if _is_valid_mem_save_text(atomic, user_input):
                result.append(atomic)
    return result


def extract_memory_tags(text: str, user_input: str = "") -> tuple[str, list, list]:
    """Read the model's memory tags out of `text`.

    Returns (clean_text, facts, deletes): the text with every memory tag
    removed, the facts safe to store, and the facts the model asked to forget.
    The caller decides what to do with them — this only reads.
    """
    clean = _drop_quoted_tags(text)
    clean = _MEMORIA_RE.sub(lambda m: f'[MEM_SAVE: {m.group(1)}]', clean)
    clean = _OBLIT_RE.sub(lambda m: f'[MEM_DELETE: {m.group(2)}]', clean)

    deletes: list = []
    raw_deletes = _MEM_DELETE_RE.findall(clean)
    if raw_deletes:
        clean = _re.sub(r'\[MEM_DELETE:[^\[\]\n\r\t]{1,250}\]\s*', '', clean).strip()
        for fact in raw_deletes:
            fact = fact.strip()
            if not fact or len(fact) < 3:
                continue
            if is_example_not_fact(fact):
                logger.info("MEM_DELETE (model tag): an example from the instructions, not a fact — ignored (#1135): %s",
                            redact_user_content(fact))
                continue
            # Read, not armed yet: deletes.arm_pending_deletes logs the arming.
            logger.info("MEM_DELETE (model tag): asked to forget %s", redact_user_content(fact))
            deletes.append(fact)

    facts = _extract_safe_mem_saves(clean, user_input=user_input)
    clean = _re.sub(r'\[MEM_SAVE:[^\[\]\n\r\t]{1,250}\]\s*', '', clean).strip()
    # Last pass: invented [MEM_*] variants must never reach the client.
    clean = _strip_unknown_mem_tags(clean)
    return clean, facts, deletes
