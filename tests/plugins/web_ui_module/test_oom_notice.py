"""The streaming OOM notice must keep the MLX guard's actionable advice.

Finding 841 (NEXE-MLX-GUARD-DEADEND) shipped a message telling the user to
switch engine, but the streaming error handler replaced every OOM with a
generic "close other applications" — and the UI always streams, so the advice
never reached a single user. These tests pin both halves: MLX failures keep the
advice, non-MLX failures must NOT be told to switch to Ollama.
"""

import pytest

from plugins.web_ui_module.api.routes_chat import _oom_notice

# The exact strings the MLX pre-load guard raises (plugins/mlx_module/core/chat.py).
_GUARD_MSG = {
    "ca": "Memòria insuficient per carregar el model amb MLX. Canvia el motor a Ollama (fa servir molta menys memòria) o tanca altres aplicacions i torna-ho a provar.",
    "es": "Memoria insuficiente para cargar el modelo con MLX. Cambia el motor a Ollama (usa mucha menos memoria) o cierra otras aplicaciones e inténtalo de nuevo.",
    "en": "Not enough memory to load the model with MLX. Switch the engine to Ollama (it uses far less memory) or close other applications and try again.",
}


@pytest.mark.parametrize("lang", ["ca", "es", "en"])
def test_mlx_guard_failure_keeps_the_switch_engine_advice(lang):
    notice = _oom_notice(_GUARD_MSG[lang], lang)
    assert "Ollama" in notice, f"the actionable half was dropped for {lang}: {notice}"


@pytest.mark.parametrize("lang", ["ca", "es", "en"])
def test_non_mlx_oom_is_not_told_to_switch_to_ollama(lang):
    """An OOM from any other engine must not advise switching to Ollama.

    A user already running Ollama being told to switch to Ollama is the failure
    this guard-on-"MLX" exists to prevent.
    """
    notice = _oom_notice("llama_cpp: OutOfMemory while allocating KV cache", lang)
    assert "Ollama" not in notice, f"nonsensical advice for {lang}: {notice}"
    assert notice, "a non-MLX OOM must still produce a notice"


def test_unknown_language_falls_back_to_english():
    assert _oom_notice(_GUARD_MSG["en"], "de") == _GUARD_MSG["en"]
    assert "Not enough memory" in _oom_notice("OutOfMemory", "de")


def test_empty_error_text_is_treated_as_non_mlx():
    """Defensive: repr(e) can be empty-ish; must not crash and must not advise."""
    assert "Ollama" not in _oom_notice("", "ca")
    assert "Ollama" not in _oom_notice(None, "ca")
