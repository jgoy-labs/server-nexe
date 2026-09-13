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
    # No newline, tab, control char or bracket
    if _MEM_SAVE_FORBIDDEN.search(text):
        return False
    # Character whitelist
    if not _MEM_SAVE_ALLOWED_CHARS.match(text):
        return False
    # Do not allow injection keywords (case-insensitive)
    _lowered = text.lower()
    _bad_keywords = (
        'mem_save', 'system prompt', 'ignore previous',
        'ignore all previous', 'override instruction',
        '<script', 'javascript:', 'onerror=', 'onload=',
    )
    for kw in _bad_keywords:
        if kw in _lowered:
            return False
    # If MEM_SAVE is exactly the user message (or contains it literally),
    # it is suspicious: the LLM has "echoed" the prompt.
    if user_input:
        _user_clean = user_input.strip().lower()
        if _user_clean and (_lowered == _user_clean or (len(_user_clean) > 10 and _user_clean in _lowered)):
            return False
    return True


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
    clean = _MEMORIA_RE.sub(lambda m: f'[MEM_SAVE: {m.group(1)}]', text)
    clean = _OBLIT_RE.sub(lambda m: f'[MEM_DELETE: {m.group(2)}]', clean)

    deletes: list = []
    raw_deletes = _MEM_DELETE_RE.findall(clean)
    if raw_deletes:
        clean = _re.sub(r'\[MEM_DELETE:[^\[\]\n\r\t]{1,250}\]\s*', '', clean).strip()
        for fact in raw_deletes:
            fact = fact.strip()
            if not fact or len(fact) < 3:
                continue
            logger.info("MEM_DELETE (model tag): pending confirmation for %s", redact_user_content(fact))
            deletes.append(fact)

    facts = _extract_safe_mem_saves(clean, user_input=user_input)
    clean = _re.sub(r'\[MEM_SAVE:[^\[\]\n\r\t]{1,250}\]\s*', '', clean).strip()
    # Last pass: invented [MEM_*] variants must never reach the client.
    clean = _strip_unknown_mem_tags(clean)
    return clean, facts, deletes
