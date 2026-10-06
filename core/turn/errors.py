"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/errors.py
Description: What kind of failure an engine error is (C4.4, moved from routes_chat.py).

The CLASS is the core's. So are the curated words for an engine that failed
(C4.8-b: a JSON door and /v1 tell the user the same thing the chat's notice
does); how a door dresses them is its own.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


class StreamCapExceeded(Exception):
    """A reply grew past `NEXE_MAX_STREAM_MB` (#1039): the turn ends partial.

    Same message as the /v1 forwarders' in-band error (`stream_cap_exceeded`),
    so a log line reads the same whichever door the runaway came through.
    """

    def __init__(self) -> None:
        super().__init__("stream_cap_exceeded")


def is_oom_error(err_msg: str) -> bool:
    """True when an engine's error text describes an out-of-memory failure.

    Shared by the web door's `_stream_error_notice` (which message to show) and
    `_classify_engine_error` (#1040, C2.4: which ADR-007 §8 class to record —
    Fatal, since closing other applications or switching engines is a step
    the user must take, not something a retry on the next engine fixes).
    """
    return any(k in err_msg for k in (
        "Insufficient Memory", "OutOfMemory",
        "Memòria insuficient", "Memoria insuficiente",
        "Not enough memory",
    ))


def classify_engine_error(exc: Exception) -> str:
    """ADR-007 §8 class for an exception caught mid-stream (#1040, C2.4).

    Used only to annotate `ctx.error` for the trace — C2 does not yet act on
    the class (that starts with C2.5's deadline/budget work). OOM is Fatal
    (the user must free memory or switch engines); anything else caught here
    is the current engine failing at this moment, i.e. Retryable in the
    sense that a fresh turn against a different engine could still succeed —
    though this turn itself, with tokens already on the wire, cannot be.
    """
    err_msg = repr(exc) if not str(exc) else str(exc)
    return "Fatal" if is_oom_error(err_msg) else "Retryable"


_OOM_MLX = {
    "ca": "Memòria insuficient per carregar el model amb MLX. Canvia el motor a Ollama (fa servir molta menys memòria) o tanca altres aplicacions i torna-ho a provar.",
    "es": "Memoria insuficiente para cargar el modelo con MLX. Cambia el motor a Ollama (usa mucha menos memoria) o cierra otras aplicaciones e inténtalo de nuevo.",
    "en": "Not enough memory to load the model with MLX. Switch the engine to Ollama (it uses far less memory) or close other applications and try again.",
}
_OOM_GENERIC = {
    "ca": "Memòria insuficient. Tanca altres aplicacions per alliberar memòria i torna-ho a provar.",
    "es": "Memoria insuficiente. Cierra otras aplicaciones para liberar memoria e inténtalo de nuevo.",
    "en": "Not enough memory. Close other applications to free up memory and try again.",
}
_FAILED = {
    "ca": "S'ha produït un error en generar la resposta. Torna-ho a provar.",
    "es": "Se ha producido un error al generar la respuesta. Inténtalo de nuevo.",
    "en": "An error occurred while generating the response. Please try again.",
}


def oom_notice(err_msg: "str | None", lang: str) -> str:
    """Curated out-of-memory text, by originating engine.

    The MLX pre-load guard already raises a message telling the user to switch
    engines, but a generic "close other applications" used to replace every
    OOM — and since the UI always streams, that advice never reached anyone.
    It is gated on the failure actually coming from MLX: this also catches OOM
    raised by other engines, and telling a user who is already on Ollama to
    switch to Ollama is nonsense.

    MC-133 still holds: the text is curated per language and never echoes the
    raw exception, which can carry internal paths or state.
    """
    table = _OOM_MLX if "MLX" in (err_msg or "") else _OOM_GENERIC
    return table.get(lang, table["en"])


def curated_error_text(exc: Exception, lang: "str | None") -> str:
    """What the user is told about an engine that failed (MC-133): the OOM text
    when it was out of memory, a localized generic one otherwise. Never the
    exception's own words — they can carry internal paths or state."""
    err_msg = repr(exc) if not str(exc) else str(exc)
    code = lang[:2] if lang else "ca"
    if is_oom_error(err_msg):
        return oom_notice(err_msg, code)
    return _FAILED.get(code, _FAILED["en"])
