"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/runtime_state.py
Description: Thread-safe singleton for runtime engine/model overrides set by
the UI (web_ui_module routes_auth/routes_chat) and consumed by motor plugins
(mlx_module, llama_cpp_module) and chat orchestration.

part 2:
  Replaces the previous pattern of mutating ``os.environ["NEXE_*"]`` from
  request handlers. The env writes were thread-unsafe (concurrent requests
  could race), opaque (no logging), and a security smell flagged by the
  semgrep ``no-environ-writes-in-handlers`` rule. This singleton keeps the
  overrides in memory only — readers consult ``get_*()`` which falls back
  to the environment variable, so standalone runs (no UI) keep their
  existing semantics.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Optional


_VALID_KEYS: frozenset[str] = frozenset({
    "NEXE_MODEL_ENGINE",
    "NEXE_DEFAULT_MODEL",
    "NEXE_MLX_MODEL",
    "NEXE_LLAMA_CPP_MODEL",
})


@dataclass
class _RuntimeOverrides:
    """Backing store. Use module-level get_/set_ helpers instead."""

    _values: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)


_state = _RuntimeOverrides()


def set_override(key: str, value: Optional[str]) -> None:
    """Set or clear a runtime override.

    Args:
      key: One of NEXE_MODEL_ENGINE / NEXE_DEFAULT_MODEL / NEXE_MLX_MODEL /
        NEXE_LLAMA_CPP_MODEL. Other keys raise ValueError so typos are caught
        at the call site instead of silently writing to a useless slot.
      value: ``None`` or empty string clears the override (readers fall back
        to the corresponding env var). Any other string is stored verbatim.
    """
    if key not in _VALID_KEYS:
        raise ValueError(
            f"runtime_state: unknown override key {key!r}; "
            f"valid keys are {sorted(_VALID_KEYS)}"
        )
    with _state._lock:
        if value:
            _state._values[key] = value
        else:
            _state._values.pop(key, None)


def get_override(key: str) -> Optional[str]:
    """Return the current override or None when not set.

    Does NOT consult the environment — use ``get_with_env_fallback`` for the
    full lookup chain.
    """
    if key not in _VALID_KEYS:
        raise ValueError(
            f"runtime_state: unknown override key {key!r}; "
            f"valid keys are {sorted(_VALID_KEYS)}"
        )
    with _state._lock:
        return _state._values.get(key)


def get_with_env_fallback(key: str, default: str = "") -> str:
    """Override → environment variable → default.

    Most readers want this — they pick up live UI selections when present and
    fall back to startup-time env vars otherwise.
    """
    override = get_override(key)
    if override is not None:
        return override
    return os.environ.get(key, default)


def reset() -> None:
    """Clear all overrides. Intended for tests."""
    with _state._lock:
        _state._values.clear()
