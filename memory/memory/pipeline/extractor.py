"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/pipeline/extractor.py
Description: Heuristic fact extractor — zero LLM, works always.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import re
from typing import List, Optional

from ..models.memory_entry import ExtractedFact

logger = logging.getLogger(__name__)

# First person + state verb patterns (multilingual)
IDENTITY_PATTERNS = [
    # "Em dic X" / "Me llamo X" / "My name is X"
    (
        re.compile(
            r"(?:em\s+dic|me\s+llamo|my\s+name\s+is|i'?m\s+called)\s+([A-ZÀÁÈÉÍÒÓÚÜ][a-zàáèéíòóúüç]+(?:\s+[A-ZÀÁÈÉÍÒÓÚÜ][a-zàáèéíòóúüç]+)*)",
            re.IGNORECASE,
        ),
        "name",
        lambda m: m.group(1).strip(),
    ),
    # "Visc a X" / "Vivo en X" / "I live in X"
    (
        re.compile(
            r"(?:visc\s+a|vivo\s+en|i\s+live\s+in)\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "location",
        lambda m: m.group(1).strip().rstrip("."),
    ),
    # "Soc X" / "Soy X" / "I am a X" (occupation)
    (
        re.compile(
            r"(?:soc\s+(?:un\s+|una\s+)?|soy\s+(?:un\s+|una\s+)?|i\s+am\s+(?:a\s+|an\s+)?)(\w[\w\s]{2,30}?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "occupation",
        lambda m: m.group(1).strip().rstrip("."),
    ),
    # "Treballo a/en X" / "Trabajo en X" / "I work at X"
    (
        re.compile(
            r"(?:treballo?\s+(?:a|en)|trabajo\s+en|i\s+work\s+(?:at|for))\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "company",
        lambda m: m.group(1).strip().rstrip("."),
    ),
    # "Tinc X anys" / "Tengo X años" / "I am X years old"
    (
        re.compile(
            r"(?:tinc|tengo)\s+(\d{1,3})\s+(?:anys|años)|i\s+am\s+(\d{1,3})\s+(?:years?\s+old)",
            re.IGNORECASE,
        ),
        "birth_year",
        lambda m: m.group(1) or m.group(2),
    ),
    # "Parlo X" / "Hablo X" / "I speak X"
    (
        re.compile(
            r"(?:parlo|hablo|i\s+speak)\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "spoken_languages",
        lambda m: m.group(1).strip().rstrip("."),
    ),
]

# Preference patterns
PREFERENCE_PATTERNS = [
    # "M'agrada X" / "Me gusta X" / "I like X"
    (
        re.compile(
            r"(?:m'agrada|m'encanta|me\s+gusta|me\s+encanta|i\s+(?:like|love|enjoy))\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "positive",
    ),
    # "Odio X" / "No m'agrada X" / "I hate X"
    (
        re.compile(
            r"(?:odio|no\s+m'agrada|no\s+me\s+gusta|i\s+(?:hate|dislike|don'?t\s+like))\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "negative",
    ),
    # "Prefereixo X" / "Prefiero X" / "I prefer X"
    (
        re.compile(
            r"(?:prefereixo|preferisco|prefiero|i\s+prefer)\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "positive",
    ),
]

# Correction patterns
CORRECTION_PATTERNS = [
    # "No, el meu nom és X" / "No, em dic X" / "No, me llamo X" / "No, my name is X"
    re.compile(
        r"no[,.]?\s+(?:el\s+meu\s+nom\s+[eé]s|em\s+dic|me\s+llamo|my\s+name\s+is|i'?m)\s+(.+?)(?:\.|,|$)",
        re.IGNORECASE,
    ),
    # "No, visc a X" / Generic correction
    re.compile(
        r"no[,.]?\s+(?:visc\s+a|vivo\s+en|i\s+live\s+in|soc|soy|i\s+am)\s+(.+?)(?:\.|,|$)",
        re.IGNORECASE,
    ),
]

# Allergy / health patterns
HEALTH_PATTERNS = [
    (
        re.compile(
            r"(?:tinc|tengo|i\s+have)\s+(?:al[·.]?l[eè]rgia|alergia|allergy|an?\s+allergy)\s+(?:a|al?|to)\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "allergies",
    ),
    (
        re.compile(
            r"(?:soc|soy|i'?m|i\s+am)\s+(?:al[·.]?l[eè]rgic|al[eé]rgic[oa]?|allergic)\s+(?:a|al?|to)\s+(.+?)(?:\.|,|$)",
            re.IGNORECASE,
        ),
        "allergies",
    ),
]


class Extractor:
    """
    Heuristic fact extractor — zero LLM.

    Detects:
    - First person + state verbs (identity facts)
    - Entities with proper nouns
    - Preferences
    - Corrections
    - Health/allergy mentions
    """

    def extract(self, text: str) -> List[ExtractedFact]:
        """
        Extract facts from text using heuristics.

        Args:
            text: User message text

        Returns:
            List of extracted facts (may be empty)
        """
        facts: List[ExtractedFact] = []
        clean = text.strip()
        if not clean:
            return facts

        # Check corrections first (higher priority)
        correction = self._check_corrections(clean)
        if correction:
            facts.append(correction)

        # Identity patterns
        for pattern, attribute, value_fn in IDENTITY_PATTERNS:
            match = pattern.search(clean)
            if match:
                value = value_fn(match)
                if value and len(value) > 1:
                    fact = ExtractedFact(
                        content=clean,
                        entity="user",
                        attribute=attribute,
                        value=value,
                        tags=["identity"],
                        importance=0.8,
                        source="heuristic",
                    )
                    # Avoid duplicate attributes in same extraction
                    if not any(f.attribute == attribute for f in facts):
                        facts.append(fact)

        # Health patterns (high importance)
        for pattern, attribute in HEALTH_PATTERNS:
            match = pattern.search(clean)
            if match:
                value = match.group(1).strip().rstrip(".")
                if value:
                    fact = ExtractedFact(
                        content=clean,
                        entity="user",
                        attribute=attribute,
                        value=value,
                        tags=["health", "critical"],
                        importance=0.9,
                        source="heuristic",
                    )
                    if not any(f.attribute == attribute and f.value == value for f in facts):
                        facts.append(fact)

        # Preference patterns
        for pattern, sentiment in PREFERENCE_PATTERNS:
            match = pattern.search(clean)
            if match:
                value = match.group(1).strip().rstrip(".")
                if value and len(value) > 1:
                    fact = ExtractedFact(
                        content=clean,
                        entity="user",
                        attribute=None,
                        value=value,
                        tags=["preference", sentiment],
                        importance=0.6,
                        source="heuristic",
                    )
                    facts.append(fact)

        # If no structured facts but text looks factual, create generic
        if not facts and self._looks_factual(clean):
            facts.append(
                ExtractedFact(
                    content=clean,
                    entity="user",
                    attribute=None,
                    value=None,
                    tags=["general"],
                    importance=0.5,
                    source="heuristic",
                )
            )

        return facts

    def _check_corrections(self, text: str) -> Optional[ExtractedFact]:
        """Detect correction patterns."""
        for pattern in CORRECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                value = match.group(1).strip().rstrip(".")
                if value:
                    # Try to detect what attribute is being corrected
                    attribute = self._guess_corrected_attribute(text, value)
                    return ExtractedFact(
                        content=text,
                        entity="user",
                        attribute=attribute,
                        value=value,
                        tags=["correction"],
                        importance=0.9,
                        source="heuristic",
                        is_correction=True,
                    )
        return None

    @staticmethod
    def _guess_corrected_attribute(text: str, value: str) -> Optional[str]:
        """Try to guess which attribute is being corrected."""
        lower = text.lower()
        if any(w in lower for w in ["nom", "llamo", "name", "dic"]):
            return "name"
        if any(w in lower for w in ["visc", "vivo", "live"]):
            return "location"
        if any(w in lower for w in ["soc", "soy", "i am"]):
            return "occupation"
        return None

    @staticmethod
    def _looks_factual(text: str) -> bool:
        """Check if text looks like it contains factual information."""
        lower = text.lower()
        factual_markers = [
            "tinc", "tengo", "i have",
            "soc", "soy", "i am",
            "faig", "hago", "i do",
            "uso", "utilizo", "i use",
            "estudio", "studio",
        ]
        return any(marker in lower for marker in factual_markers)


__all__ = ["Extractor", "ExtractedFact"]
