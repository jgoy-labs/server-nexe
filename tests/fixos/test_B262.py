"""
Test fix B262 (finding #850): flapping d'idioma invalida la caché de prefix.

La detecció d'idioma es feia PER TORN: un ack curt en una altra llengua
("thanks a lot" en conversa catalana) canviava la directiva CRITICAL — que va
AL PRINCIPI del system — i el prefix divergia des del token 0: re-prefill
complet gratuït (i a llama.cpp, _destroy + recàrrega del GGUF).

Fix: idioma sticky per sessió (patró thinking_enabled) resolt AL CALL-SITE
via _resolve_session_lang; només flipa amb una detecció REAL diferent en un
missatge >= _STICKY_LANG_MIN_SWITCH_CHARS (25). El fallback per text curt NO
és detecció i mai flipa. _build_system_prompt_with_time guanya `lang_hint`
(el contracte de test_b007 — canvi d'idioma = invalidació legítima — queda
intacte perquè la funció NO canvia de comportament sense hint).
"""
import datetime as _dt
from types import SimpleNamespace

import pytest

# C4.2: the sticky-language policy and the system-prompt assembly moved out of
# the plugin into `core/turn/prompt.py`, whole. `rc` keeps its name here so the
# assertions below stay a move, not a rewrite.
import core.lang_detect as _lang_detect  # #1143: the one place the reply language is decided
import core.turn.prompt as rc
from core.utils import compute_system_hash
from core.sessions import ChatSession

_FIXED_NOW = _dt.datetime(2026, 7, 30, 13, 2, 7).astimezone()


def _session(lang=None):
    return SimpleNamespace(lang=lang, lang_pending=None)


class TestResolveSessionLangPolicy:
    """Política de canvi amb detecció mockejada (determinista).

    Endurida per la review adversarial: fallback mai sembra, llindar sobre
    text natural, histèresi de 2 torns.
    """

    def test_first_real_detection_seeds_sticky(self, monkeypatch):
        monkeypatch.setattr(_lang_detect, "detect_user_lang_or_none", lambda m: "en")
        s = _session()
        assert rc._resolve_session_lang(s, "hello there, how are you today?") == "en"
        assert s.lang == "en"

    def test_no_detection_returns_fallback_without_seeding(self, monkeypatch):
        """Review #850: un guess (NEXE_LANG) mai es fixa — la primera detecció
        REAL és qui sembra; mentrestant el fallback és estable per env."""
        monkeypatch.setattr(_lang_detect, "detect_user_lang_or_none", lambda m: None)
        monkeypatch.setenv("NEXE_LANG", "ca")
        s = _session()
        assert rc._resolve_session_lang(s, "ok") == "ca"
        assert s.lang is None, "el fallback NO pot sembrar l'sticky"

    def test_degenerate_nexe_lang_still_returns_en(self, monkeypatch):
        """Review #850: NEXE_LANG degenerat no pot produir idioma buit."""
        monkeypatch.setattr(_lang_detect, "detect_user_lang_or_none", lambda m: None)
        monkeypatch.setenv("NEXE_LANG", "-es")
        assert rc._resolve_session_lang(_session(), "ok") == "en"

    def test_short_ack_never_flips(self, monkeypatch):
        """El cor del #850: "thanks a lot" (12 chars, detecció EN real) NO pot
        flipar una sessió catalana."""
        monkeypatch.setattr(_lang_detect, "detect_user_lang_or_none", lambda m: "en")
        s = _session(lang="ca")
        assert rc._resolve_session_lang(s, "thanks a lot") == "ca"
        assert s.lang == "ca"

    def test_url_padded_ack_never_flips(self, monkeypatch):
        """Review #850: el llindar es mesura sobre el TEXT NATURAL — un link
        llarg no converteix "thanks mate" en canvi d'idioma."""
        monkeypatch.setattr(_lang_detect, "detect_user_lang_or_none", lambda m: "en")
        s = _session(lang="ca")
        msg = "thanks mate https://github.com/jgoy-labs/server-nexe/issues/1"
        assert len(msg) >= rc._STICKY_LANG_MIN_SWITCH_CHARS  # el RAW enganya
        assert rc._resolve_session_lang(s, msg) == "ca"
        assert s.lang == "ca"

    def test_a_long_foreign_turn_flips_at_once(self, monkeypatch):
        """25/09 (decisió d'en Jordi): el canvi és al 1r missatge clar. La
        histèresi de 2 torns de #850 existia perquè la detecció no era segura;
        des que ho és (`_MIN_RELATIVE_DISTANCE`), un canvi genuí no ha de pagar
        un torn de retard. Contrapartida acceptada: una traça en anglès de ≥25
        caràcters enganxada en una conversa catalana també canvia l'idioma."""
        monkeypatch.setattr(_lang_detect, "detect_user_lang_or_none", lambda m: "en")
        s = _session(lang="ca")
        assert rc._resolve_session_lang(s, "can we please switch to english now?") == "en"
        assert s.lang == "en" and s.lang_pending is None

    def test_it_switches_back_just_as_fast(self, monkeypatch):
        detections = iter(["en", "ca"])
        monkeypatch.setattr(
            _lang_detect, "detect_user_lang_or_none", lambda m: next(detections)
        )
        s = _session(lang="ca")
        long = "aquesta és una frase prou llarga per superar el llindar del gate"
        assert rc._resolve_session_lang(s, long) == "en"
        assert rc._resolve_session_lang(s, long) == "ca"
        assert s.lang == "ca"

    def test_same_lang_long_message_keeps_sticky(self, monkeypatch):
        monkeypatch.setattr(_lang_detect, "detect_user_lang_or_none", lambda m: "ca")
        s = _session(lang="ca")
        assert rc._resolve_session_lang(s, "una pregunta llarga i ben catalana sobre el temps") == "ca"

    def test_threshold_is_named_constant(self):
        assert rc._STICKY_LANG_MIN_SWITCH_CHARS == 25


class TestChatSessionPersistence:
    def test_lang_round_trips(self):
        s = ChatSession()
        s.lang = "en"
        restored = ChatSession.from_dict(s.to_dict())
        assert restored.lang == "en"

    def test_legacy_payload_without_lang_gives_none(self):
        s = ChatSession()
        payload = s.to_dict()
        payload.pop("lang", None)
        assert ChatSession.from_dict(payload).lang is None


class TestLangHintPlumbs:
    def test_hint_overrides_detection(self):
        """Amb lang_hint el system porta la directiva de l'idioma STICKY, no el
        del missatge — sense hint, el comportament (i el contracte b007) és
        exactament el d'abans."""
        system_ca, lang_ca = rc._build_system_prompt_with_time(
            "thanks a lot for everything", _now=_FIXED_NOW, lang_hint="ca"
        )
        assert lang_ca == "ca"
        assert "entire response in Catalan" in system_ca

    def test_flagship_hash_stable_across_ack_turns(self):
        """FLAGSHIP #850: mateixa sessió, torn català llarg + ack anglès curt →
        el system (i per tant identity_hash) NO canvia.

        Contra HEAD (detecció per torn, sense sticky): "thanks a lot!" flipava
        la directiva a English → hash diferent → RED.
        """
        lingua = pytest.importorskip("lingua", reason="cal lingua per la detecció real")
        assert lingua
        session = _session()
        msgs = [
            "explica'm com funciona la memòria de sessions, si us plau",
            "thanks a lot!",
        ]
        hashes = []
        for m in msgs:
            lang = rc._resolve_session_lang(session, m)
            system, _ = rc._build_system_prompt_with_time(m, _now=_FIXED_NOW, lang_hint=lang)
            hashes.append(compute_system_hash(system))
        assert hashes[0] == hashes[1], (
            "l'ack curt en una altra llengua ha invalidat el prefix (flapping #850)"
        )

    def test_companion_b007_genuine_switch_still_invalidates(self):
        """Review #850: contrapart pel flux sticky del contracte b007 — un canvi
        GENUÍ d'idioma SÍ canvia el hash (des del 25/09, al 1r torn clar)."""
        lingua = pytest.importorskip("lingua", reason="cal lingua per la detecció real")
        assert lingua
        session = _session()
        turns = [
            "explica'm com funciona la memòria de sessions, si us plau",
            "please switch to english for the rest of this conversation",
            "great, continue explaining the session memory in english now",
        ]
        hashes = []
        for m in turns:
            lang = rc._resolve_session_lang(session, m)
            system, _ = rc._build_system_prompt_with_time(m, _now=_FIXED_NOW, lang_hint=lang)
            hashes.append(compute_system_hash(system))
        # 25/09: el canvi és al 1r missatge clar — el 2n torn ja invalida.
        assert hashes[1] != hashes[0], (
            "el canvi genuí ha de ser una invalidació legítima (b007)"
        )
        assert hashes[2] == hashes[1], "un cop canviat, l'idioma es manté"
        assert session.lang == "en"
