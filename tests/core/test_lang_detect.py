"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_lang_detect.py
Description: detect_user_lang() + directive helpers (lingua-backed). The engine
             must detect the user's message language (any of lingua's 75) —
             accurately on short, close-language text (ca/es) where langdetect
             failed — and reply in it, with safe fallbacks.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.lang_detect import (
    detect_user_lang,
    language_name_en,
    prepend_language_directive,
    append_language_reminder,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # The exact case that langdetect got wrong (detected 'fr'): now 'es'.
        ("¡Hola! ¿Puedes explicarme con detalle qué eres y qué puedes hacer?", "es"),
        ("Explícame cómo funcionan las redes neuronales artificiales.", "es"),
        ("Hola! Em pots explicar amb detall què ets i què pots fer per mi?", "ca"),
        ("Bon dia, com va tot avui? Tinc ganes de treballar.", "ca"),
        ("Hello, how are you doing today? I want to design a system.", "en"),
        # Global: beyond ca/es/en.
        ("Bonjour, comment ça va aujourd'hui mon ami?", "fr"),
        ("Ciao, come stai oggi? Ho voglia di lavorare.", "it"),
        ("Olá, tudo bem com você hoje?", "pt"),
        ("Hallo, wie geht es dir heute mein Freund?", "de"),
    ],
)
def test_detects_language(monkeypatch, message, expected):
    monkeypatch.delenv("NEXE_LANG", raising=False)
    assert detect_user_lang(message) == expected


def test_short_or_noise_falls_back(monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "ca")
    assert detect_user_lang("ok") == "ca"
    assert detect_user_lang("42") == "ca"
    assert detect_user_lang("") == "ca"
    assert detect_user_lang("   ") == "ca"


def test_code_block_stripped(monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "es")
    assert detect_user_lang("```python\ndef foo():\n    return 42\n```") == "es"


def test_explicit_fallback_wins_over_env(monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "en")
    assert detect_user_lang("xy", fallback="es") == "es"


def test_deterministic_across_calls(monkeypatch):
    monkeypatch.delenv("NEXE_LANG", raising=False)
    msg = "Hello, how are you doing today? I want to design a system."
    assert {detect_user_lang(msg) for _ in range(8)} == {"en"}


def test_language_name_en():
    assert language_name_en("es") == "Spanish"
    assert language_name_en("ca") == "Catalan"
    assert language_name_en("de") == "German"
    assert language_name_en("ja") == "Japanese"
    assert language_name_en("xx") == "XX"  # unknown → uppercased code


@pytest.mark.parametrize(
    ("lang", "name"),
    [("ca", "Catalan"), ("es", "Spanish"), ("en", "English"), ("de", "German")],
)
def test_prepend_language_directive(lang, name):
    out = prepend_language_directive("BASE PROMPT", lang)
    assert out.startswith("[CRITICAL INSTRUCTION]")
    assert name in out
    assert out.endswith("BASE PROMPT")


def test_append_language_reminder():
    out = append_language_reminder("PROMPT", "fr")
    assert out.startswith("PROMPT")
    assert out.rstrip().endswith("(Reply entirely in French.)")


# 25/09: with all 75 languages on and no floor, short Catalan lines were
# "detected" as Latin/French/Italian at ~0.06 confidence, and the first one
# seeded the session language. They must give NO signal (install language).
@pytest.mark.parametrize("message", [
    "Hola com vas?",
    "Qui ets?",
    "Com et dius?",
    "Bon dia, com estàs?",
    "Quant fa 17 per 23?",
    "I que saps del mon?",
    "Hola, com et dius i on vius?",
])
def test_a_short_ambiguous_line_is_no_signal(message):
    from core.lang_detect import detect_user_lang_or_none

    assert detect_user_lang_or_none(message) is None


@pytest.mark.parametrize(("message", "expected"), [
    ("¿Puedes explicarme cómo funciona la memoria?", "es"),
    ("Can we switch to English please?", "en"),
    ("Wie geht es dir heute?", "de"),
    ("Olá, tudo bem com você hoje?", "pt"),
    ("Bonjour, comment ça va aujourd'hui?", "fr"),
    ("Ciao, come stai oggi?", "it"),
    ("Ik wil graag weten hoe dit werkt", "nl"),
    ("Jak się masz dzisiaj?", "pl"),
])
def test_a_clear_sentence_still_detects_in_any_language(message, expected):
    from core.lang_detect import detect_user_lang_or_none

    assert detect_user_lang_or_none(message) == expected


# 25/09, live: "Et pregunto que com vas?" (Catalan without accents) → es, and
# it seeded the session in Spanish. On a ca install a close call goes home.
@pytest.mark.parametrize(("message", "expected"), [
    ("Et pregunto que com vas?", "ca"),
    ("Vull saber que fas i com funciones", "ca"),
    ("Puedes decirme que tal estas hoy amigo?", "es"),
    ("¿Puedes explicarme cómo funciona la memoria?", "es"),
    ("Can you tell me who you are please?", "en"),
    ("Bonjour, comment ça va aujourd'hui?", "fr"),
])
def test_a_close_call_goes_to_the_install_language(monkeypatch, message, expected):
    from core.lang_detect import detect_user_lang_or_none

    monkeypatch.setenv("NEXE_LANG", "ca")
    assert detect_user_lang_or_none(message) == expected
