"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/intent_patterns.py
Description: Memory intent patterns and their detection, as module functions.

The triggers and the detection they drive are data plus pure functions: no
instance state, nothing that needs a helper to exist. Both doors read them
from here (ADR-007 C3.0); MemoryHelper keeps thin forwarders until C3.1.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


# Intent patterns for memory operations (Catalan + Spanish + English)
# Patterns that indicate user wants to SAVE something
SAVE_TRIGGERS = [
    # Catalan — at the end of the message
    r',?\s*(ho\s+)?pots\s+guardar\??$',
    r',?\s*(ho\s+)?pots\s+recordar\??$',
    r',?\s*guarda[\-\']?ho\??$',
    r',?\s*desa[\-\']?ho\??$',
    # Catalan — at the beginning of the message ("Recorda que X")
    r'^recorda\s+que\s+',
    r'^guarda\s+que\s+',
    r'^apunta\s+que\s+',
    # Catalan — with "memòria" anywhere in the message
    r'\bguardar?\b.*mem[oò]ria',
    r'\brecordar?\b.*mem[oò]ria',
    r'\bdesa\b.*mem[oò]ria',
    r'\bapunta\b.*mem[oò]ria',
    # Spanish — at the end of the message
    r',?\s*lo\s+puedes\s+guardar\??$',
    r',?\s*puedes\s+guardar(lo)?\??$',
    r',?\s*lo\s+puedes\s+recordar\??$',
    r',?\s*puedes\s+recordar(lo)?\??$',
    r',?\s*gu[aá]rda(lo)?\??$',
    r',?\s*recu[eé]rda(lo)?\??$',
    # Spanish — at the beginning of the message ("Recuerda que X")
    r'^recuerda\s+que\s+',
    r'^guarda\s+que\s+',
    r'^apunta\s+que\s+',
    # Spanish — with "memoria"
    r'\bguardar?\b.*memoria',
    r'\brecordar?\b.*memoria',
    # English — at the end of the message
    r',?\s*(can\s+you\s+)?(please\s+)?save\s+(it|this|that)\??$',
    r',?\s*(can\s+you\s+)?(please\s+)?remember\s+(it|this|that)\??$',
    r',?\s*save\s+it\??$',
    # English — at the beginning of the message ("Remember that X")
    r'^remember\s+that\s+',
    r'^save\s+that\s+',
    # English — with "memory"
    r'\bsave\b.*memory',
    r'\bremember\b.*memory',
]

RECALL_PATTERNS = [
    # Catalan
    r'\b(busca|cerca|recupera)\b',
    r'\bqu[eè]\s+saps\s+(sobre|de)\b',
    r'\b(recordes|et\s+recordes)\b',
    r'\bcom\s+(em\s+)?dic\b',
    r'\bquin\s+[eé]s\s+(el\s+)?(meu\s+)?nom\b',
    # Spanish
    r'\b(busca|recupera)\b',
    r'\bqu[eé]\s+sabes\s+(sobre|de|acerca)\b',
    r'\b(recuerdas|te\s+acuerdas)\b',
    r'\bc[oó]mo\s+me\s+llamo\b',
    r'\bcu[aá]l\s+es\s+(el\s+)?(mi\s+)?nombre\b',
    r'\bcu[aá]l\s+es\s+(el\s+)?nombre\s+del\s+(usuario|usurio)\b',
    # English
    r'\b(search|find|recall)\b',
    r'\bwhat\s+do\s+you\s+know\s+(about|on)\b',
    r'\b(do\s+you\s+remember)\b',
    r'\bwhat\s*(is|\'s)\s+my\s+name\b',
]

# Bug #18 P0: explicit "clear all memory" patterns.
# These must be checked BEFORE DELETE_TRIGGERS — otherwise "Oblida tot" matches
# ^oblida\s+(que\s+)? with content="tot", and delete_from_memory("tot", thr=0.70)
# then semantic-searches "tot" and deletes ~5 arbitrary facts instead of wiping
# the collection. The pipeline handles clear_all with a 2-turn confirmation.
CLEAR_ALL_TRIGGERS = [
    # Catalan
    r'^oblida\s+(ho\s+)?tot\b',
    r'^oblida-ho\s+tot\b',
    r'^esborra\s+(la\s+)?mem[oò]ria\s+(sencera|entera)\b',
    r'^esborra\s+tot(\s+el\s+que\s+saps)?\b',
    r'^esborra-ho\s+tot\b',
    r'^elimina\s+(la\s+)?mem[oò]ria\s+(sencera|entera)\b',
    # Spanish
    r'^olv[ií]da(lo)?\s+todo\b',
    r'^borra\s+(la\s+)?memoria\s+(entera|completa)\b',
    r'^borra\s+todo(\s+lo\s+que\s+sabes)?\b',
    r'^b[oó]rralo\s+todo\b',
    r'^elimina\s+(la\s+)?memoria\s+(entera|completa)\b',
    # English
    r'^forget\s+everything\b',
    r'^delete\s+all\s+memor(y|ies)\b',
    r'^erase\s+all\s+memor(y|ies)\b',
    r'^wipe\s+(all\s+)?(my\s+)?memor(y|ies)\b',
    r'^clear\s+(all\s+)?(my\s+)?memor(y|ies)\b',
    # B028 (RT-02): natural wipe phrasings that previously fell through to the
    # PARTIAL delete path and erased an arbitrary fact without confirmation.
    # "esborra tota la meva memòria, oblida-ho tot" matched none of the anchored
    # patterns above ("tota" ≠ "tot\b") and became delete(content="tota la meva
    # memòria..."). Any wipe-shaped phrase must arm the 2-turn confirmation.
    # Catalan — "esborra/elimina/buida ... tota la (meva) memòria"
    r'^(esborra|elimina|buida|neteja)\b.{0,40}\btota\s+la\s+(meva\s+)?mem[oò]ria\b',
    r'\boblida[\s\-]ho\s+tot\b',
    r'\besborra[\s\-]ho\s+tot\b',
    r'^oblida\s+tot\s+el\s+que\s+saps\b',
    # Spanish — "borra/elimina/limpia ... toda la/mi memoria"
    r'^(borra|elimina|limpia|vac[ií]a)\b.{0,40}\btoda\s+(la\s+|mi\s+)?memoria\b',
    r'\bolv[ií]dalo\s+todo\b',
    r'\bb[oó]rralo\s+todo\b',
    r'^olvida\s+todo\s+lo\s+que\s+sabes\b',
    # English — "delete/erase/clear/wipe ... all (of) my memory/memories"
    r'^(delete|erase|clear|wipe|remove)\b.{0,40}\ball\s+(of\s+)?(my\s+)?memor(y|ies)\b',
    r'\bforget\s+everything\b',
    r'^forget\s+all\s+you\s+know\b',
]

# Confirmation patterns for the 2-turn clear_all flow. Matched only when the
# session has session._pending_clear_all == True.
CLEAR_ALL_CONFIRM_TRIGGERS = [
    # Catalan
    r'\bs[ií][\s,]+(confirma|esborra|continua)',
    r'\bs[ií][\s,]+(ho\s+)?esborra[\-\']?(ho)?\s+tot\b',
    r'^s[ií][,.]?\s*$',
    r'^confirmo\b',
    r'^endavant\b',
    # Spanish
    r'\bs[ií][\s,]+(confirma|borra|continua)',
    r'\bs[ií][\s,]+(lo\s+)?borra(lo)?\s+todo\b',
    r'^s[ií][,.]?\s*$',
    r'^confirmo\b',
    # English
    r'\byes[\s,]+(confirm|delete|continue)',
    r'\byes[\s,]+(delete|wipe|clear|erase)\s+(all|everything)',
    r'^yes[,.]?\s*$',
    r'^confirm\b',
    r'^go\s+ahead\b',
]

# Patterns that indicate user wants to DELETE/FORGET something
DELETE_TRIGGERS = [
    # Catalan — at the beginning ("Oblida que X", "Esborra que X")
    r'^oblida\s+(que\s+)?',
    r'^esborra\s+(que\s+)?',
    r'^elimina\s+(que\s+)?',
    # Catalan — at the end ("..., oblida-ho", "..., esborra-ho")
    r',?\s*(ho\s+)?pots\s+oblidar\??$',
    r',?\s*(ho\s+)?pots\s+esborrar\??$',
    r',?\s*oblida[\-\']?ho\??$',
    r',?\s*esborra[\-\']?ho\??$',
    # Catalan — with "memòria"
    r'\boblidar?\b.*mem[oò]ria',
    r'\besborrar?\b.*mem[oò]ria',
    r'\beliminar?\b.*mem[oò]ria',
    # Spanish — at the beginning
    r'^olvida\s+(que\s+)?',
    r'^borra\s+(que\s+)?',
    r'^elimina\s+(que\s+)?',
    # Spanish — at the end
    r',?\s*(lo\s+)?puedes\s+olvidar\??$',
    r',?\s*(lo\s+)?puedes\s+borrar\??$',
    r',?\s*olv[ií]da(lo)?\??$',
    r',?\s*b[oó]rra(lo)?\??$',
    # Spanish — with "memoria"
    r'\bolvidar?\b.*memoria',
    r'\bborrar?\b.*memoria',
    # English — at the beginning
    r'^forget\s+(that\s+)?',
    r'^delete\s+(that\s+)?',
    r'^erase\s+(that\s+)?',
    # English — at the end
    r',?\s*(can\s+you\s+)?(please\s+)?forget\s+(it|this|that)\??$',
    r',?\s*(can\s+you\s+)?(please\s+)?delete\s+(it|this|that)\??$',
    r',?\s*forget\s+it\??$',
    # English — with "memory"
    r'\bforget\b.*memory',
    r'\bdelete\b.*memory',
    r'\berase\b.*memory',
    # Catalan — mid-sentence ("Pots esborrar que...", "Vull que oblidis que...")
    r'\bpots\s+(esborrar|oblidar|eliminar)\s+(que\s+)?',
    r'\bvull\s+que\s+(esborris|oblidis|eliminis)\s+(que\s+)?',
    r'\bpodries\s+(esborrar|oblidar|eliminar)\s+(que\s+)?',
    # Spanish — mid-sentence ("Puedes borrar que...", "Quiero que olvides que...")
    r'\bpuedes\s+(borrar|olvidar|eliminar)\s+(que\s+)?',
    r'\bquiero\s+que\s+(borres|olvides|elimines)\s+(que\s+)?',
    r'\bpodr[ií]as\s+(borrar|olvidar|eliminar)\s+(que\s+)?',
    # English — mid-sentence ("Can you delete that...", "I want you to forget...")
    r'\bcan\s+you\s+(delete|forget|erase|remove)\s+(that\s+)?',
    r'\b(i\s+want|i\'d\s+like)\s+you\s+to\s+(forget|delete|erase|remove)\s+(that\s+)?',
    r'\b(please\s+)?(delete|forget|erase|remove)\s+that\b',
]

# Patterns that indicate user wants to LIST/SEE stored memories
LIST_TRIGGERS = [
    # Catalan
    r'qu[eè]\s+record[ea]s\s+(de\s+mi|sobre\s+mi)',
    r'qu[eè]\s+saps\s+(de\s+mi|sobre\s+mi)',
    r'quines\s+mem[oò]ries\s+tens',
    r'mostra\s+(la\s+)?mem[oò]ria',
    r'llista\s+(les\s+)?mem[oò]ries',
    r'qu[eè]\s+tens\s+guardat',
    # Spanish
    r'qu[eé]\s+recuerdas\s+(de\s+m[ií]|sobre\s+m[ií])',
    r'qu[eé]\s+sabes\s+(de\s+m[ií]|sobre\s+m[ií])',
    r'qu[eé]\s+memorias\s+tienes',
    r'muestra\s+(la\s+)?memoria',
    r'lista\s+(las\s+)?memorias',
    r'qu[eé]\s+tienes\s+guardado',
    # English
    r'what\s+do\s+you\s+remember\s+(about\s+me)?',
    r'what\s+do\s+you\s+know\s+about\s+me',
    r'list\s+(my\s+)?memories',
    r'show\s+(my\s+)?memor(y|ies)',
    r'what\s+have\s+you\s+saved',
]


# Compiled once at import: the triggers never change at runtime, and every
# door detects against the same objects.
SAVE_RE = [re.compile(p, re.IGNORECASE) for p in SAVE_TRIGGERS]
RECALL_RE = [re.compile(p, re.IGNORECASE) for p in RECALL_PATTERNS]
DELETE_RE = [re.compile(p, re.IGNORECASE) for p in DELETE_TRIGGERS]
LIST_RE = [re.compile(p, re.IGNORECASE) for p in LIST_TRIGGERS]
CLEAR_ALL_RE = [re.compile(p, re.IGNORECASE) for p in CLEAR_ALL_TRIGGERS]
CLEAR_ALL_CONFIRM_RE = [re.compile(p, re.IGNORECASE) for p in CLEAR_ALL_CONFIRM_TRIGGERS]


def detect_save_intent(message: str) -> Optional[str]:
    """Return extracted content if message matches a save trigger, else None.

    Triggers at END: "Em dic Claude, guarda-ho" → content = before trigger
    Triggers at START: "Recorda que em dic Claude" → content = after trigger
    """
    for pattern in SAVE_RE:
        match = pattern.search(message)
        if match:
            if match.start() == 0:
                content = message[match.end():].strip()
            else:
                content = message[:match.start()].strip().rstrip(',').strip()
            if content:
                return content
    return None


def detect_delete_intent(message: str) -> Optional[str]:
    """Return extracted content if message matches a delete trigger, else None.

    "Oblida que em dic Claude" → "em dic Claude"
    "Pots esborrar que tinc 8 anys?" → "tinc 8 anys"
    """
    for pattern in DELETE_RE:
        match = pattern.search(message)
        if match:
            content_after = message[match.end():].strip().rstrip('?!').strip()
            content_before = message[:match.start()].strip().rstrip(',').strip()
            if match.start() == 0:
                content = content_after
            elif not content_after:
                content = content_before
            else:
                content = content_after
            if content:
                return content
    return None


def detect_intent(message: str) -> Tuple[str, Optional[str]]:
    """
    Detect user intent in message.

    Args:
        message: User message text

    Returns:
        Tuple of (intent, extracted_content)
        intent can be: 'save', 'recall', 'delete', 'list', 'clear_all', 'chat'
    """
    save_content = detect_save_intent(message)
    if save_content:
        return ('save', save_content)

    # Bug #18 P0: check for "clear all memory" BEFORE delete.
    # "Oblida tot" would otherwise match ^oblida\s+(que\s+)? with content="tot",
    # which semantic-searches "tot" and deletes arbitrary facts.
    for pattern in CLEAR_ALL_RE:
        if pattern.search(message):
            return ('clear_all', None)

    delete_content = detect_delete_intent(message)
    if delete_content:
        return ('delete', delete_content)

    # Check for LIST intent (before recall — "que recordes de mi?" matches both)
    for pattern in LIST_RE:
        if pattern.search(message):
            return ('list', None)

    for pattern in RECALL_RE:
        if pattern.search(message):
            return ('recall', message)

    return ('chat', None)


def matches_clear_all_confirm(message: str) -> bool:
    """Return True if message confirms a pending clear_all operation.

    Called from the chat pipeline only when session._pending_clear_all is True.
    Accepts short affirmations ('sí', 'yes', 'confirmo') and explicit phrases
    ('sí, esborra-ho tot', 'yes delete everything'). See CLEAR_ALL_CONFIRM_TRIGGERS.
    """
    msg = message.strip()
    for pattern in CLEAR_ALL_CONFIRM_RE:
        if pattern.search(msg):
            return True
    return False
