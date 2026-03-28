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

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# SSE TOKEN SANITIZATION - Strip null bytes and control chars from streaming
# ═══════════════════════════════════════════════════════════════════════════

# Control chars to strip (except \n and \t which are valid in text)
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

def _sanitize_sse_token(token: str) -> str:
    """Remove null bytes and control characters from SSE token content."""
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
_RAG_INJECTION_PATTERNS = [
    re.compile(r'\[/?INST\]', re.IGNORECASE),           # Instruction markers
    re.compile(r'<\|/?system\|>', re.IGNORECASE),       # System role markers
    re.compile(r'<\|/?user\|>', re.IGNORECASE),         # User role markers
    re.compile(r'<\|/?assistant\|>', re.IGNORECASE),    # Assistant role markers
    re.compile(r'###\s*(system|user|assistant)', re.IGNORECASE),  # Role headers
    re.compile(r'\[CONTEXT[^\]]*\]', re.IGNORECASE),    # Our own context markers
]

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

    # 1. Truncate to prevent context overflow
    sanitized = context[:MAX_RAG_CONTEXT_LENGTH]
    if len(context) > MAX_RAG_CONTEXT_LENGTH:
        sanitized += "\n[...truncat]"
        logger.warning("RAG context truncated from %d to %d chars", len(context), MAX_RAG_CONTEXT_LENGTH)

    # 2. Remove prompt injection patterns
    for pattern in _RAG_INJECTION_PATTERNS:
        sanitized = pattern.sub('[FILTERED]', sanitized)

    # 3. Escape our own delimiter markers to prevent context breakout
    sanitized = sanitized.replace('[/CONTEXT]', '[/CONTEXT_ESCAPED]')
    sanitized = sanitized.replace('[CONTEXT', '[CONTEXT_ESCAPED')

    return sanitized
