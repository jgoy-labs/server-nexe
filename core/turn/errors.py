"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/errors.py
Description: What kind of failure an engine error is (C4.4, moved from routes_chat.py).

The CLASS is the core's; the words the user reads are each door's.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


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
