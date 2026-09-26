"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lang_detect.py
Description: Language detection for user messages, so the engine replies in the
             language of the message instead of being anchored to the install
             language (NEXE_LANG). Uses lingua (offline, models bundled in the
             wheel, accurate on short text and close languages like ca/es/pt/fr/it).
             Supports the 75 languages lingua ships. Falls back to NEXE_LANG when
             the message is too short/ambiguous, code, or detection is unsure.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lingua import LanguageDetector

logger = logging.getLogger(__name__)

# Below this many characters (after stripping code/URLs) detection is unreliable
# on short, close-language text → fall back instead of guessing.
_MIN_DETECT_CHARS = 10

_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")

# ISO 639-1 → English language name, used to build the reply directive. Small
# models follow an instruction that names the language explicitly ("respond in
# German") far better than "match the user's language". Unknown codes fall back
# to the uppercased code so the directive is still meaningful.
_LANG_NAMES_EN = {
    "ca": "Catalan", "es": "Spanish", "en": "English", "fr": "French",
    "de": "German", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "gl": "Galician", "eu": "Basque", "ru": "Russian", "uk": "Ukrainian",
    "pl": "Polish", "cs": "Czech", "sk": "Slovak", "ro": "Romanian",
    "el": "Greek", "tr": "Turkish", "ar": "Arabic", "he": "Hebrew",
    "fa": "Persian", "hi": "Hindi", "bn": "Bengali", "ur": "Urdu",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese",
    "th": "Thai", "id": "Indonesian", "ms": "Malay", "tl": "Tagalog",
    "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish",
    "is": "Icelandic", "hu": "Hungarian", "et": "Estonian", "lv": "Latvian",
    "lt": "Lithuanian", "sl": "Slovene", "hr": "Croatian", "sr": "Serbian",
    "bg": "Bulgarian", "mk": "Macedonian", "sq": "Albanian", "ga": "Irish",
    "cy": "Welsh", "af": "Afrikaans", "sw": "Swahili",
}

# lingua must be SURE, not just pick the top of 75 near-equal guesses. With
# every language on, a short Catalan greeting scores like noise — measured
# 25/09: "Hola com vas?" → Latin 0.06 · Portuguese 0.05 · Spanish 0.05, and
# that Latin seeded the session: the scaffolding went English and the reply
# directive said "respond in LA". The langdetect this replaced (29/05) had a
# 0.55 confidence floor; the switch to lingua dropped it. 0.1 is the measured
# point: every short ambiguous Catalan line gives no signal (install language
# wins), while clear sentences in es/en/de/pt/fr/it/nl/pl still detect. 0.2
# already loses a plain Italian "Ciao, come stai oggi?".
_MIN_RELATIVE_DISTANCE = 0.1

# Catalan without accents reads like Spanish to lingua, and the first such
# line decided a whole conversation (seen live 25/09: "Et pregunto que com
# vas?" → es, and the session answered in Spanish). When the detection
# differs from the INSTALL language and the install language still scores at
# least this share of the winner's confidence, it is a close call and the
# install language wins. A ratio, not a difference: on short text every
# score is low. Measured on a ca install — Catalan misread as Spanish: ca at
# 0.57-0.70 of es; real Spanish, Italian, English, German…: ca at ≤0.21 of
# the winner (even "hola que tal estas", 0.21, stays Spanish).
_HOME_LANG_RATIO = 0.5

_DETECTOR: LanguageDetector | None = None
try:
    from lingua import LanguageDetectorBuilder

    # All languages → truly global support (the 75 lingua covers), but only
    # calls lingua is sure of (see _MIN_RELATIVE_DISTANCE).
    _DETECTOR = (
        LanguageDetectorBuilder.from_all_languages()
        .with_minimum_relative_distance(_MIN_RELATIVE_DISTANCE)
        .build()
    )
except ImportError:  # pragma: no cover - optional dependency
    pass


def _fallback_lang(fallback: Optional[str]) -> str:
    """Resolve the fallback language: explicit arg → NEXE_LANG → 'en'."""
    base = fallback or os.getenv("NEXE_LANG") or "en"
    return base.split("-")[0].lower()[:2] or "en"


def _strip_noise(text: str) -> str:
    """Remove code blocks, inline code and URLs (no natural-language signal)."""
    text = _CODE_BLOCK_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    return text.strip()


def fallback_lang(explicit: Optional[str] = None) -> str:
    """Public fallback resolution (explicit → NEXE_LANG → 'en'), normalised.

    Exposed so callers (#850 sticky policy) never re-implement the
    normalisation — an inline copy once dropped the trailing 'en' guard and
    seeded an empty language from a degenerate NEXE_LANG.
    """
    return _fallback_lang(explicit)


def natural_text_len(message: str) -> int:
    """Length of the natural-language content (code blocks/inline/URLs out).

    This is the text lingua actually judged — switch gates (#850) must
    measure THIS, not the raw string ("thanks mate https://…" is 34 raw
    chars but only 11 of language).
    """
    return len(_strip_noise(message or ""))


def detect_user_lang_or_none(message: str) -> Optional[str]:
    """Pure detection: ISO 639-1 code only when lingua makes a REAL call.

    ``None`` means "no signal": detector unavailable, empty/short/code-only
    text, or lingua judged it ambiguous. Callers deciding whether to SWITCH a
    sticky session language must never treat a fallback as a detection (#850).
    """
    if _DETECTOR is None or not message:
        return None

    cleaned = _strip_noise(message)
    if len(cleaned) < _MIN_DETECT_CHARS:
        return None

    # detect_language_of returns the best candidate, or None when the top two
    # are closer than _MIN_RELATIVE_DISTANCE — exactly the no-signal we want.
    detected = _DETECTOR.detect_language_of(cleaned)
    if detected is None:
        return None

    code = detected.iso_code_639_1.name.lower()
    home = _fallback_lang(None)
    if code != home and _home_is_close(cleaned, detected, home):
        return home
    return code


def _home_is_close(text: str, detected, home: str) -> bool:
    """True when the install language scores at least _HOME_LANG_RATIO of the
    detected one's confidence — too close a call to take it away from home."""
    try:
        from lingua import IsoCode639_1, Language

        home_lang = Language.from_iso_code_639_1(IsoCode639_1.from_str(home))
    except Exception:  # an install language lingua does not know: no preference
        return False
    top = _DETECTOR.compute_language_confidence(text, detected)
    return top > 0 and _DETECTOR.compute_language_confidence(text, home_lang) >= _HOME_LANG_RATIO * top


def detect_user_lang(message: str, fallback: Optional[str] = None) -> str:
    """Detect the language of a user message (ISO 639-1, any of lingua's langs).

    Falls back to ``fallback`` (else ``NEXE_LANG``, else ``"en"``) when lingua is
    unavailable, the message is too short/ambiguous/code, or confidence is low.
    """
    detected = detect_user_lang_or_none(message)
    return detected if detected is not None else _fallback_lang(fallback)


def language_name_en(lang: str) -> str:
    """English name of an ISO 639-1 code, for the reply directive."""
    return _LANG_NAMES_EN.get(lang.lower()[:2], lang.upper())


def prepend_language_directive(prompt: str, lang: str) -> str:
    """Prepend an imperative reply-language directive (English + explicit name).

    English instruction with the language named explicitly is the most reliable
    way to make small models (4B/9B) reply in the right language. Shared by the
    web UI and the OpenAI-compatible API.
    """
    name = language_name_en(lang)
    directive = (
        f"[CRITICAL INSTRUCTION] You MUST write your entire response in {name}. "
        "Do not use any other language, regardless of the system language."
    )
    return f"{directive}\n\n{prompt}"


def append_language_reminder(prompt: str, lang: str) -> str:
    """Append a short reply-language reminder at the very end of the prompt.

    Small models are recency-biased: the instruction closest to generation
    weighs most. Reinforcing the directive at the end markedly improves
    compliance over prepend alone.
    """
    return f"{prompt}\n\n(Reply entirely in {language_name_en(lang)}.)"
