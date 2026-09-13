"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/attach.py
Description: Bind the process-wide MemoryHelper onto ServerState.

Same idempotent-attach shape as core.sessions.attach.attach_session_manager,
core.turn.gate.attach_engine_gate and core.turn.post_commit.attach_post_commit_queue.
Called from the core lifespan, so /v1 reaches memory without the UI plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging

from core.memory_facts.helper import MemoryHelper

logger = logging.getLogger(__name__)


def attach_memory_helper(server_state) -> MemoryHelper:
    """Return the process-wide MemoryHelper, creating it once on server_state."""
    existing = getattr(server_state, "memory_helper", None)
    if existing is not None:
        return existing
    helper = MemoryHelper()
    server_state.memory_helper = helper
    logger.info("MemoryHelper attached to server_state")
    return helper


def helper_for(app_state) -> MemoryHelper:
    """The MemoryHelper on `app_state`, or a loud failure.

    Unlike `gate_for`, there is no permissive fallback: a helper conjured on
    the spot would answer every call while reading nobody's memory, and the
    caller would never know. The lifespan attaches one before any request can
    reach a door; a test that drives these paths attaches its own.
    """
    helper = getattr(app_state, "memory_helper", None)
    if helper is not None:
        return helper
    raise RuntimeError(
        "MemoryHelper missing on app_state — attach_memory_helper() must run "
        "in the lifespan (or in the test fixture) before any memory operation."
    )
