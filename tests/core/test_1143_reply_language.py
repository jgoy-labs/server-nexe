"""#1143 — the reply language of a conversation (Jordi, 03/10: «les dues regles»).

Live 03/10 (Ollama, qwen3.5:9b, install language ca): «quees aqursta imatge?»
was detected as Afrikaans and, being the first detection of a new conversation,
set it in Afrikaans; «En Català perdona.» was detected as Catalan but, 18
characters under the 25 of the switch threshold, changed nothing. Two rules:

* a short message cannot set a language other than the install one;
* a language asked for by name («en català», «in English») wins at once.

The decision is one function (core.lang_detect.decide_reply_lang) for both
doors; the parity tests in test_f854_sticky_lang_openai.py keep them equal.
"""
import pytest

import core.endpoints.chat as ce
import core.lang_detect as ld
import core.turn.prompt as rc
from core.sessions import ChatSession

LIVE = ["quees aqursta imatge?", "En Català perdona.", "Post paralar amb català?", "perque paralves mab alemana?"]


@pytest.fixture(autouse=True)
def _catalan_install(monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "ca")


def test_the_premise_lingua_still_misreads_short_catalan():
    # If lingua ever reads these right, the first rule is no longer what saves
    # them — this says so instead of passing for the wrong reason.
    assert ld.detect_user_lang_or_none("quees aqursta imatge?") not in (None, "ca")
    assert ld.detect_user_lang_or_none("què és aquesta imatge?") not in (None, "ca")


def test_the_live_conversation_is_answered_in_catalan_at_both_doors():
    session = ChatSession(session_id="s1143")
    web = [rc._resolve_session_lang(session, m) for m in LIVE]
    api = [ce._resolve_request_lang("api-1143", m) for m in LIVE]
    assert web == api == ["ca", "ca", "ca", "ca"]


# ── Rule 1: a short message cannot set a foreign language ───────────────────

def test_a_short_foreign_detection_does_not_seed(monkeypatch):
    monkeypatch.setattr(ld, "detect_user_lang_or_none", lambda m: "yo")
    assert ld.decide_reply_lang(None, "què és aquesta imatge?") == ("ca", None)


def test_a_clear_foreign_sentence_still_seeds(monkeypatch):
    monkeypatch.setattr(ld, "detect_user_lang_or_none", lambda m: "en")
    assert ld.decide_reply_lang(None, "hello there, how are you doing today?") == ("en", "en")


def test_a_short_message_in_the_install_language_seeds(monkeypatch):
    monkeypatch.setattr(ld, "detect_user_lang_or_none", lambda m: "ca")
    assert ld.decide_reply_lang(None, "bon dia!") == ("ca", "ca")


# ── Rule 2: a language asked for by name wins at once ───────────────────────

@pytest.mark.parametrize("text, lang", [
    ("En Català perdona.", "ca"), ("Post paralar amb català?", "ca"), ("parla en català", "ca"),
    ("in English please", "en"), ("can you answer in Spanish?", "es"), ("respon-me en anglès", "en"),
    ("en castellano por favor", "es"), ("¿puedes hablar en catalán?", "ca"), ("en français s'il te plaît", "fr"),
    # Review 04/10: ways to ask that the first rule missed.
    ("switch to English", "en"), ("canvia a castellà", "es"), ("Cambia a español", "es"),
    ("parla català", "ca"), ("English please", "en"), ("Speak Spanish please", "es"),
    ("explica-ho en català, si us plau", "ca"), ("pots contestar amb l'anglès?", "en"),
])
def test_a_named_language_is_a_request(text, lang):
    assert ld.requested_lang(text) == lang


@pytest.mark.parametrize("text", [
    "m'agrada l'anglès", "el català és bonic", "tradueix-ho en anglès", "translate this into Spanish",
    "hola", "quees aqursta imatge?",
    # Review 04/10: ordinary sentences that switched the whole conversation.
    "vivo en Italia desde 2010", "estuve en Italia el verano pasado", "com es diu gat en anglès?",
    "¿cómo se dice gato en inglés?", "how do you say thanks in French?", "El llibre està escrit en francès",
    "en anglès és diferent", "the word in English is cat", "amb català no m'aclareixo",
    "con el inglés tengo problemas", "talla-ho en angles de 45 graus", "please explain the English grammar",
    "tradueix-ho al castellà, si us plau", "com es diu gat en anglès, si us plau?",
    "how do you say thanks in French, please?",
    "explica'm coses d'Itàlia, si us plau", "la meva filla parla molt bé l'anglès",
])
def test_mentioning_a_language_is_not_a_request(text):
    assert ld.requested_lang(text) is None


def test_a_named_request_switches_a_conversation_already_in_another_language():
    # The live turn 2: sticky Afrikaans, 18 characters.
    assert ld.decide_reply_lang("af", "En Català perdona.") == ("ca", "ca")


def test_without_a_name_a_short_message_still_does_not_switch(monkeypatch):
    monkeypatch.setattr(ld, "detect_user_lang_or_none", lambda m: "en")
    assert ld.decide_reply_lang("ca", "thanks a lot") == ("ca", None)
