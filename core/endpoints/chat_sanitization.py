"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_sanitization.py
Description: SSE token and RAG context sanitization for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import re
import unicodedata

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# SSE TOKEN SANITIZATION - Strip null bytes and control chars from streaming
# ═══════════════════════════════════════════════════════════════════════════

# Control chars to strip (except \n, \t, \r which are valid in text).
# F3.2 BUG-NC-14: extend coverage to DEL (\x7f) and C1 control range (\x80-\x9f).
# Some terminals and SSE consumers interpret C1 bytes as escape sequence
# initiators (NEL, CSI, OSC) — letting them through allows model-influenced
# byte injection into client logs/terminals.
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]')

def _sanitize_sse_token(token: str) -> str:
    """Remove null bytes and control characters from SSE token content.

    Strips C0 control range except \\n (\\x0a), \\t (\\x09), \\r (\\x0d) which
    are valid in text. Defends against malicious model output that injects
    control bytes into the streamed `delta.content` field.

    SCOPE: this function targets the user-untrusted text path — the model
    output token — AND any string carried in an `error` SSE chunk (R6-04 part
    2, v1.0.4-beta). All three backends (mlx, llama_cpp, ollama) pipe model
    `content` and `error` strings through here before placing them in the SSE
    chunk dict. Other chunk fields (`finish_reason`, `delta={}`, model name)
    are Python-controlled trusted values and need not be sanitized.

    Why also `error`: while `json.dumps` escapes C0 bytes on the wire as
    `\\uXXXX`, `JSON.parse` on the client side reverses the escape and yields
    the raw null byte. `str(e)` from MLX or llama-cpp can carry model-tainted
    text in the exception chain (token text echoed back in the message), so
    the same defense applies. Ollama error strings are i18n constants but are
    sanitized for uniformity (defense-in-depth).

    If a future chunk path adds a NEW user-untrusted field (e.g. tool-call
    arguments echoed back, reasoning_content from thinking models), pass it
    through this function before json.dumps. The regression test
    `tests/test_sse_sanitize_coverage.py` enforces that `delta.content` and
    `error` chunks are always sanitized in the three backends to prevent
    silent drift.
    """
    if not token:
        return token
    return _CONTROL_CHAR_RE.sub('', token)

# ═══════════════════════════════════════════════════════════════════════════
# RAG CONTEXT SANITIZATION - Prevent prompt injection via retrieved content
# ═══════════════════════════════════════════════════════════════════════════

# Maximum characters for RAG context injection
MAX_RAG_CONTEXT_LENGTH = 4000

# RAG context window control — prevent RAG from overflowing the model's context
MAX_CONTEXT_RATIO = float(os.environ.get('NEXE_MAX_CONTEXT_RATIO', '0.3'))
DEFAULT_CONTEXT_WINDOW = int(os.environ.get('NEXE_DEFAULT_CONTEXT_WINDOW', '8192'))
CHARS_PER_TOKEN_ESTIMATE = 4  # Conservative estimate (~4 chars per token)

def _estimate_tokens(text: str) -> int:
    """Rough token estimation based on character count."""
    return len(text) // CHARS_PER_TOKEN_ESTIMATE

# Patterns that could indicate prompt injection attempts in retrieved content
# C23 v1.0.4: CJK and mathematical brackets not collapsed by NFKC — map explicitly
# so that _RAG_INJECTION_PATTERNS (ASCII-only) capture them after normalization.
# Pairs: open → [,  close → ]
_NON_NFKC_BRACKET_MAP = str.maketrans({
    "「": "[", "」": "]",   # CJK corner bracket
    "『": "[", "』": "]",   # CJK white corner bracket
    "〔": "[", "〕": "]",   # TORTOISE SHELL bracket
    "⟦": "[", "⟧": "]",   # MATHEMATICAL WHITE SQUARE bracket (U+27E6/U+27E7)
})

_RAG_INJECTION_PATTERNS = [
    re.compile(r'\[/?INST\]', re.IGNORECASE),           # Instruction markers
    re.compile(r'<\|/?system\|>', re.IGNORECASE),       # System role markers
    re.compile(r'<\|/?user\|>', re.IGNORECASE),         # User role markers
    re.compile(r'<\|/?assistant\|>', re.IGNORECASE),    # Assistant role markers
    re.compile(r'###\s*(system|user|assistant)', re.IGNORECASE),  # Role headers
    re.compile(r'\[CONTEXT[^\]]*\]', re.IGNORECASE),    # Our own context markers
    # Bug #18 P0: memory tags in RAG content can escalate to unauthorized deletes/saves.
    # A malicious uploaded document can embed [MEM_DELETE: ...] — the LLM may copy it
    # into its response, which the pipeline then executes. Neutralize at ingest + retrieval.
    re.compile(r'\[MEM_DELETE:[^\]]{1,250}\]', re.IGNORECASE),
    re.compile(r'\[MEM_SAVE:[^\]]{1,250}\]', re.IGNORECASE),
    re.compile(r'\[(?:OLVIDA|OBLIT|FORGET):[^\]]{1,250}\]', re.IGNORECASE),  # MEM_DELETE aliases
    re.compile(r'\[MEMORIA:[^\]]{1,250}\]', re.IGNORECASE),                   # MEM_SAVE alias (gpt-oss)
]

def _filter_rag_injection(text: str) -> str:
    """
    Filter prompt injection patterns from text WITHOUT truncating.

    Use this for content being INDEXED (upload/ingest path) where truncation
    would cause data loss. The full sanitization (_sanitize_rag_context) with
    truncation should only be applied at RETRIEVAL time (chat endpoint).

    B6 r4: applies NFKC Unicode normalization before regex match to neutralize
    fullwidth (`［］`), halfwidth-fullwidth letters and similar compatibility
    bypass attempts. The returned text reflects the normalized form (RAG
    indexing is a one-way pipeline — callers must accept this).

    Known gaps:
        - Homoglyph attacks (Cyrillic М vs Latin M) are out of scope — would
          require a transliteration layer (over-engineering for current threat).

    Args:
        text: Raw text to filter

    Returns:
        Text NFKC-normalized with injection patterns removed but full length preserved
    """
    if not text:
        return ""

    # NFKC: collapses fullwidth/compat variants to ASCII canonical forms.
    # Example: ［ (U+FF3B) → [ (U+005B). MUST happen before regex match —
    # patterns are ASCII-only and would miss fullwidth bypasses otherwise.
    filtered = unicodedata.normalize("NFKC", text)
    # C23: CJK/mathematical brackets not normalised by NFKC — map explicitly.
    filtered = filtered.translate(_NON_NFKC_BRACKET_MAP)
    for pattern in _RAG_INJECTION_PATTERNS:
        filtered = pattern.sub('[FILTERED]', filtered)

    filtered = filtered.replace('[/CONTEXT]', '[/CONTEXT_ESCAPED]')
    filtered = filtered.replace('[CONTEXT', '[CONTEXT_ESCAPED')

    return filtered


def _sanitize_rag_context(context: str) -> str:
    """
    Sanitize RAG retrieved content before injecting into prompt.

    SECURITY: RAG content comes from user-stored data and could contain
    prompt injection attempts. This function:
    1. Truncates to MAX_RAG_CONTEXT_LENGTH
    2. Removes known prompt injection patterns
    3. Escapes delimiter characters

    Args:
        context: Raw context text from RAG retrieval

    Returns:
        Sanitized context safe for prompt injection
    """
    if not context:
        return ""

    # F3.2 BUG-NC-32: NFKC + CJK/mathematical bracket map ALSO at retrieval time.
    # `_filter_rag_injection` (ingest path) already normalizes, but stored content
    # predating that fix — or content stored via a different write path — could
    # still contain fullwidth/compat variants. Normalizing at retrieval closes
    # the bypass for both fresh and legacy data.
    context = unicodedata.normalize("NFKC", context)
    context = context.translate(_NON_NFKC_BRACKET_MAP)

    # 1. Truncate to prevent context overflow (dynamic based on model context window)
    max_chars = max(MAX_RAG_CONTEXT_LENGTH, int(DEFAULT_CONTEXT_WINDOW * MAX_CONTEXT_RATIO * CHARS_PER_TOKEN_ESTIMATE))
    sanitized = context[:max_chars]
    if len(context) > max_chars:
        sanitized += "\n[...truncat]"
        logger.warning("RAG context truncated from %d to %d chars (window=%d, ratio=%.1f)", len(context), max_chars, DEFAULT_CONTEXT_WINDOW, MAX_CONTEXT_RATIO)

    # 2. Remove prompt injection patterns
    for pattern in _RAG_INJECTION_PATTERNS:
        sanitized = pattern.sub('[FILTERED]', sanitized)

    # 3. Escape our own delimiter markers to prevent context breakout
    sanitized = sanitized.replace('[/CONTEXT]', '[/CONTEXT_ESCAPED]')
    sanitized = sanitized.replace('[CONTEXT', '[CONTEXT_ESCAPED')

    return sanitized
