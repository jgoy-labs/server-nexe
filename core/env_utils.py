"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/env_utils.py
Description: Canonical environment-variable parsing helpers. A single shared
    truthy parser so every NEXE_* boolean flag accepts the same spellings
    (1/true/yes/on/y/t, case-insensitive) instead of each call site doing its
    own ``.lower() == "true"`` (MC-088). Kept a stdlib-only leaf so any layer
    can import it without coupling.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Optional

# Accepted truthy spellings for NEXE_* boolean env vars (case-insensitive,
# whitespace-stripped). Single source of truth — do not duplicate.
TRUTHY_VALUES = frozenset({"1", "true", "yes", "on", "y", "t"})


def parse_truthy(value: Optional[str]) -> bool:
    """Parse a string as a boolean flag.

    Accepts 1/true/yes/on/y/t (case-insensitive, whitespace-stripped) as True.
    ``None``, empty string, or anything else → False.
    """
    if value is None:
        return False
    return value.strip().lower() in TRUTHY_VALUES


# Valid TCP port range. Kept permissive (1-65535) so this shared validator never
# rejects a port that bound successfully before — it only rejects what could
# never work (0, >65535, non-numeric). SidecarConfig keeps its own stricter
# [1024-65535] policy for the Tauri-controlled sidecar.
_MIN_PORT = 1
_MAX_PORT = 65535


def parse_port(value: Optional[str], *, var_name: str = "port") -> Optional[int]:
    """Parse and validate a TCP port from an env-var string (MC-093).

    Returns ``None`` if ``value`` is None/empty so the caller falls back to its
    own default. Raises ``ValueError`` (naming the env var) when the value is not
    an integer or is outside [1, 65535], so a bad port fails fast at startup with
    a clear message instead of crashing cryptically later inside uvicorn.
    """
    if value is None or not value.strip():
        return None
    try:
        port = int(value.strip())
    except ValueError:
        raise ValueError(f"{var_name} must be an integer, got {value!r}") from None
    if port < _MIN_PORT or port > _MAX_PORT:
        raise ValueError(f"{var_name}={port} is out of the valid port range [{_MIN_PORT}-{_MAX_PORT}]")
    return port
