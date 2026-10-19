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

from fastapi import HTTPException


class StreamCapExceeded(Exception):
    """A reply grew past `NEXE_MAX_STREAM_MB` (#1039): the turn ends partial.

    Same message as the /v1 forwarders' in-band error (`stream_cap_exceeded`),
    so a log line reads the same whichever door the runaway came through.
    """

    def __init__(self) -> None:
        super().__init__("stream_cap_exceeded")


class BadRequest(ValueError):
    """A request an engine refuses as bad, and every engine would (C4.8 N5):
    final. Raised on purpose, with a message nexe wrote for the user, which
    reaches the client as it is (`user_text`). Any other `ValueError` from
    inside an engine (a reshape, a JSON decode, a pydantic validation) is that
    engine failing, and the next one is asked (P2-7)."""

    fault = "bad_request"
    user_text = True


class ModelNotFound(ValueError):
    """The model named is not on this engine, said on purpose (the model
    switch's check, #1154's «it has no weights»): final for the engine the
    client asked for, the next engine's turn for a fallback. Its message is
    written for the user and reaches the client as it is."""

    fault = "not_found"
    user_text = True


class UserFacingHTTPException(HTTPException):
    """An HTTP answer whose detail nexe wrote for the user (a model that is not
    there, and the ones that are): when it ends the turn it reaches the client
    as it is (P2-7). An HTTPException that carries an engine's own text (the
    daemon's error body) is not one."""

    user_text = True


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
    exception's own words — they can carry internal paths or state.

    One exception: an error that carries its own `curated_text(lang)` (the API
    engine's — a refused key, a balance, a rate limit) says it. It is the
    error's own sentence, written to be shown, and the only way the user
    learns that the fix is in a `.env` and not in a retry."""
    err_msg = repr(exc) if not str(exc) else str(exc)
    code = lang[:2] if lang else "ca"
    own = getattr(exc, "curated_text", None)
    if callable(own):
        return own(code)
    if is_oom_error(err_msg):
        return oom_notice(err_msg, code)
    return _FAILED.get(code, _FAILED["en"])


_NOT_FOUND = {
    "ca": "Aquest motor no té el model demanat.",
    "es": "Este motor no tiene el modelo solicitado.",
    "en": "This engine does not have the requested model.",
}
_BAD_REQUEST = {
    "ca": "El motor no ha pogut acceptar aquesta petició.",
    "es": "El motor no ha podido aceptar esta petición.",
    "en": "The engine could not accept this request.",
}


#: Why no candidate is left to answer a turn, when engines are live (P2-1 re-review).
NO_OWN_MODEL = "no_own_model"
CANNOT_SEE = "cannot_see"
_NO_ENGINE_CAN_ANSWER = {
    NO_OWN_MODEL: {
        "ca": "Cap motor disponible no pot respondre: Ollama no té cap model propi configurat per fer de recanvi (NEXE_OLLAMA_MODEL).",
        "es": "Ningún motor disponible puede responder: Ollama no tiene ningún modelo propio configurado para hacer de reserva (NEXE_OLLAMA_MODEL).",
        "en": "No available engine can answer: Ollama has no model of its own configured to stand in (NEXE_OLLAMA_MODEL).",
    },
    CANNOT_SEE: {
        "ca": "Cap motor disponible no pot veure la imatge.",
        "es": "Ningún motor disponible puede ver la imagen.",
        "en": "No available engine can see the image.",
    },
}


def no_engine_can_answer(reasons: list, lang: "str | None") -> str:
    """What a turn is told when engines are live and none of them can answer it:
    why, written for the user, in the turn's language — one sentence per reason."""
    code = lang[:2] if lang else "ca"
    said = []
    for reason in reasons:
        table = _NO_ENGINE_CAN_ANSWER[reason]
        text = table.get(code, table["en"])
        if text not in said:
            said.append(text)
    return " ".join(said)


def final_error_text(exc: Exception, fault: str, lang: "str | None") -> str:
    """What the client is told when an engine's failure ends the turn (C4.8
    P2-7): never raw text — an engine's or an internal exception's own words
    carry internal URLs, paths, a pydantic dump. What nexe wrote for the user
    reaches the client as it is: an error's own `curated_text` (the API's
    refused key), or its message when it says so (`user_text`: `BadRequest`,
    `ModelNotFound`, `UserFacingHTTPException`). Anything else is told with the
    curated sentence of what it means."""
    code = lang[:2] if lang else "ca"
    own = getattr(exc, "curated_text", None)
    if callable(own):
        return own(code)
    if getattr(exc, "user_text", False) is True:
        return exc.detail if isinstance(exc, HTTPException) else str(exc)
    table = {"not_found": _NOT_FOUND, "bad_request": _BAD_REQUEST}.get(fault, _FAILED)
    return table.get(code, table["en"])
