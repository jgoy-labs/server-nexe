"""D-G — the sanitizer log must not lie, and a failed load must not hide.

#871: never claim a rewrite (the module returns the original text).
#872: if the module cannot load, log WARNING (not debug) and pass the text.
"""

from __future__ import annotations

import logging

from plugins.security.sanitizer import apply_user_text_sanitizer
from plugins.security.sanitizer import module as sanitizer_mod


def test_source_never_claims_rewrite():
    src = open(sanitizer_mod.__file__, encoding="utf-8").read()
    assert "rewrote user input" not in src
    core_chat = open(
        __import__("core.endpoints.chat", fromlist=["chat"]).__file__,
        encoding="utf-8",
    ).read()
    assert "rewrote user input" not in core_chat


def test_unavailable_module_logs_warning_not_debug(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("sanitizer down")

    monkeypatch.setattr(sanitizer_mod, "get_sanitizer", _boom)
    with caplog.at_level(logging.DEBUG, logger=sanitizer_mod.__name__):
        out = apply_user_text_sanitizer("Hola, com estàs?")
    assert out == "Hola, com estàs?"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("unavailable" in r.getMessage() for r in warnings)
    debugs = [
        r for r in caplog.records
        if r.levelno == logging.DEBUG and "unavailable" in r.getMessage()
    ]
    assert not debugs


def test_sanitize_raise_logs_warning_keeps_text(monkeypatch, caplog):
    class _Broken:
        def sanitize(self, text):
            raise RuntimeError("scan failed")

    monkeypatch.setattr(sanitizer_mod, "get_sanitizer", lambda: _Broken())
    with caplog.at_level(logging.WARNING, logger=sanitizer_mod.__name__):
        out = apply_user_text_sanitizer("Hola")
    assert out == "Hola"
    assert any("sanitize raised" in r.getMessage() for r in caplog.records)


def test_flagged_log_does_not_say_rewrote(monkeypatch, caplog):
    """A non-blocking match is 'flagged', never 'rewrote'."""
    class _Flag:
        def sanitize(self, text):
            return sanitizer_mod.SanitizeResult(
                clean_text=text,
                is_safe=False,
                threats_detected=["jailbreak"],
                severity="low",
            )

    monkeypatch.setattr(sanitizer_mod, "get_sanitizer", lambda: _Flag())
    with caplog.at_level(logging.INFO, logger=sanitizer_mod.__name__):
        out = apply_user_text_sanitizer("hello jailbreak as a topic")
    assert out == "hello jailbreak as a topic"
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "rewrote" not in joined
    assert "flagged" in joined
