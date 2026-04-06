"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/pipeline/gate.py
Description: Gate heuristic — fast discard of non-memorizable messages.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_LENGTH = int(os.environ.get("NEXE_MEMORY_MIN_LENGTH", "20"))
UNIQUE_TOKEN_RATIO_MIN = 0.3

# Stopwords (multilingual basic set)
STOPWORDS = frozenset({
    # Catalan
    "el", "la", "els", "les", "un", "una", "uns", "unes", "de", "del", "dels",
    "a", "al", "als", "en", "amb", "per", "que", "i", "o", "no", "si", "jo",
    "tu", "ell", "ella", "nosaltres", "vosaltres", "ells", "elles", "em", "et",
    "es", "ens", "us", "ho", "hi", "ha", "he", "has", "han", "ser", "estar",
    "fer", "dir", "anar", "com", "mes", "molt", "poc", "tot", "be", "ja",
    # Spanish
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "a", "al", "en", "con", "por", "para", "que", "y", "o", "no", "si",
    "yo", "tu", "el", "ella", "nosotros", "vosotros", "ellos", "ellas",
    "me", "te", "se", "nos", "os", "lo", "le", "les", "ha", "he", "has",
    "han", "ser", "estar", "hacer", "decir", "como", "mas", "muy", "poco",
    "todo", "bien", "ya", "pero", "es", "son",
    # English
    "the", "a", "an", "of", "to", "in", "for", "on", "with", "at", "by",
    "from", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "can", "this", "that", "these", "those", "it", "its", "he", "she", "they",
    "we", "you", "i", "my", "your", "his", "her", "our", "their", "what",
    "which", "who", "when", "where", "how", "not", "but", "and", "or", "if",
    "so", "just", "also", "very", "really", "ok", "okay",
})

# High-importance patterns that bypass length check (multilingual)
HIGH_IMPORTANCE_PATTERNS = [
    # Identity patterns
    re.compile(r"\b(soc|soy|i\s+am|em\s+dic|me\s+llamo|my\s+name)\b", re.IGNORECASE),
    # Possession/state
    re.compile(r"\b(tinc|tengo|i\s+have)\b", re.IGNORECASE),
    # Health/safety
    re.compile(r"(al[·.]?l[eè]rgi|al[eé]rgi|allerg)", re.IGNORECASE),
    # Restrictions
    re.compile(r"\b(no\s+puc|no\s+puedo|i\s+can'?t|no\s+menjo|no\s+como)\b", re.IGNORECASE),
    # Location
    re.compile(r"\b(visc\s+a|vivo\s+en|i\s+live\s+in)\b", re.IGNORECASE),
]


@dataclass
class GateResult:
    """Result of the gate evaluation."""

    passed: bool
    reason: str
    score: float = 0.0


class Gate:
    """
    Heuristic gate — discards 70-80% of non-memorizable messages.

    Cost: ~0, <3ms. No ML models.
    """

    def __init__(self, min_length: int = MIN_LENGTH):
        self._min_length = min_length

    def evaluate(
        self,
        text: str,
        is_user_message: bool = True,
        is_mem_save: bool = False,
    ) -> GateResult:
        """
        Evaluate whether a message should pass the gate.

        Args:
            text: The message text
            is_user_message: True if from user, False if model-generated
            is_mem_save: True if this is a MEM_SAVE from the model

        Returns:
            GateResult with passed=True if message should continue to extractor
        """
        if not text or not text.strip():
            return GateResult(passed=False, reason="empty", score=0.0)

        clean = text.strip()

        # Model-generated messages are rejected unless MEM_SAVE
        if not is_user_message and not is_mem_save:
            return GateResult(passed=False, reason="model_generated", score=0.0)

        # Check high-importance patterns first (bypass length)
        has_high_importance = self._has_high_importance(clean)

        # Length check (bypassed by high-importance patterns)
        if len(clean) < self._min_length and not has_high_importance:
            return GateResult(passed=False, reason="too_short", score=0.1)

        # Purely a question with no assertion
        if self._is_pure_question(clean) and not has_high_importance:
            return GateResult(passed=False, reason="pure_question", score=0.1)

        # Token uniqueness ratio (repetitive content)
        tokens = clean.lower().split()
        if len(tokens) > 3:
            unique_ratio = len(set(tokens)) / len(tokens)
            if unique_ratio < UNIQUE_TOKEN_RATIO_MIN:
                return GateResult(passed=False, reason="repetitive", score=0.1)

        # Calculate informative density
        score = self._info_density(tokens)
        if has_high_importance:
            score = max(score, 0.7)

        return GateResult(passed=True, reason="accepted", score=score)

    def _has_high_importance(self, text: str) -> bool:
        """Check if text matches high-importance patterns."""
        for pattern in HIGH_IMPORTANCE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    @staticmethod
    def _is_pure_question(text: str) -> bool:
        """Check if text is purely a question with no factual assertion."""
        stripped = text.rstrip()
        if not stripped.endswith("?"):
            return False
        # Contains assertion markers -> not pure question
        assertion_markers = re.compile(
            r"\b(soc|soy|i\s+am|tinc|tengo|i\s+have|visc|vivo|i\s+live|"
            r"em\s+dic|me\s+llamo|my\s+name|recordes\s+que|recuerdas\s+que|"
            r"remember\s+that)\b",
            re.IGNORECASE,
        )
        if assertion_markers.search(text):
            return False
        return True

    @staticmethod
    def _info_density(tokens: list) -> float:
        """Calculate informative density (content words / total words)."""
        if not tokens:
            return 0.0
        content_words = [t for t in tokens if t not in STOPWORDS]
        ratio = len(content_words) / len(tokens)
        return min(1.0, ratio)


__all__ = ["Gate", "GateResult"]
