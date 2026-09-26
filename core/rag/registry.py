"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/rag/registry.py
Description: Where a retrieval source says it exists (ADR-008, E1b).

Until now the turn had three sources and no way to add a fourth: the lookup
was a literal dict in `collections.py` and a generic fallback built on the
spot, so the orchestrator was still the only thing that knew the names. This
is the missing half of the pattern — a place a source registers itself, and
one function the turn asks.

Two tiers, on purpose:

1. What is REGISTERED here (dynamic: a plugin's collection, and later the
   document module of E3).
2. The three the product ships with, which stay in `collections.py`.

They are NOT merged into one dict, and that is a safety decision, not an
oversight: a reset of this registry (every test needs one — see below) must
not be able to take `personal_memory` down with it. The built-ins are not
registrable state; they are the floor.

Registering a name that a system source already answers is REFUSED. The
alternative — last writer wins — would let any plugin quietly answer for
`personal_memory` and read the user's memory through a door meant for its own
collection. A port that can be hijacked is worse than no port.

Global mutable state needs a reset in tests or one test's source leaks into
the next (a test that passes alone and fails in a suite, or worse, the
reverse). `clear_registered_sources()` exists for exactly that, and the
autouse fixture in `tests/core/rag/conftest.py` calls it.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
from typing import Dict

from core.rag.source import RAGSource

logger = logging.getLogger(__name__)

#: name -> source. Written by `register_source`, read by `source_for`.
_REGISTERED: Dict[str, RAGSource] = {}


def register_source(source: RAGSource) -> None:
    """Make `source` answer for its own name from the next turn on.

    Raises `ValueError` if the name is already registered, or if it is one of
    the collections the product ships with (see the module docstring: a
    registered source must not be able to shadow `personal_memory`).
    """
    # Deferred so this module does not import the built-ins at import time:
    # `collections.py` reads thresholds from the environment when IT is
    # imported, and the registry must not be what forces that to happen.
    from core.rag.collections import is_system_collection

    name = source.name()
    if not isinstance(name, str) or not name:
        raise ValueError("a source must have a non-empty name")
    if is_system_collection(name):
        raise ValueError(
            f"{name!r} is a system collection: a registered source must not shadow "
            "one the product ships with"
        )
    if name in _REGISTERED:
        raise ValueError(f"a source named {name!r} is already registered")
    _REGISTERED[name] = source
    logger.info("RAG: source %r registered", name)


def unregister_source(name: str) -> bool:
    """Remove a registered source. True if there was one."""
    return _REGISTERED.pop(name, None) is not None


def registered_source(name: str) -> "RAGSource | None":
    """The registered source for `name`, or None. Read by `source_for`."""
    return _REGISTERED.get(name)


def registered_names() -> list[str]:
    """Every registered source's name.

    The orchestrator unions these with the collections it discovers live, so
    a registered source is searchable and selectable by `rag_collections`
    without having to exist as a Qdrant collection first — which is what E3's
    document module will need.
    """
    return sorted(_REGISTERED)


def clear_registered_sources() -> None:
    """Forget every registered source. For tests; see the module docstring."""
    _REGISTERED.clear()
