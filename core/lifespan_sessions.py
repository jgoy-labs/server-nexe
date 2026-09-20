"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_sessions.py
Description: SessionManager startup + hourly cleanup. Owns the instance so
             /v1 can persist threads without the UI plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)


async def _startup_session_manager(server_state) -> None:
    """Create the process-wide SessionManager after encryption, before plugins."""
    from core.sessions import attach_session_manager
    attach_session_manager(server_state)


def _expose_session_manager(app, server_state) -> None:
    """Put the process-wide SessionManager where the API routes look for it.

    `attach_session_manager` hangs the instance on `server_state`; the /v1 code
    (`mirror_v1_conversation`, `persist_v1_turn`, the collision guard in
    `derive_session_id`) reads `request.app.state.session_manager` — the same
    place `chat_completions` reads `config` and `modules` from. Until
    2026-09-06 nothing copied it across: the mirror found None, returned
    (best-effort, by design) and no /v1 conversation ever reached disk on a real
    server — while the tests, which set `app.state.session_manager` by hand,
    stayed green. One registry, one brain: the instance on `app.state` IS the
    one on `server_state`, never a second manager.
    """
    mgr = getattr(server_state, "session_manager", None)
    if mgr is None:
        logger.warning(
            "SessionManager not attached on server_state — /v1 threads will not "
            "be persisted (app.state.session_manager left unset)"
        )
        return
    app.state.session_manager = mgr


async def _startup_engine_gate(server_state) -> None:
    """Create the process-wide EngineGate (ADR-007 §7, C2.1) after the session
    manager — same slot, no reason to be earlier or later."""
    from core.turn.gate import attach_engine_gate
    attach_engine_gate(server_state)


def _expose_engine_gate(app, server_state) -> None:
    """Mirror the gate onto `app.state`, same reason as `_expose_session_manager`
    above: the turn adapters read `ctx.app_state.engine_gate`, not `server_state`."""
    gate = getattr(server_state, "engine_gate", None)
    if gate is None:
        logger.warning("EngineGate not attached on server_state — generation will run unguarded")
        return
    app.state.engine_gate = gate


async def _startup_post_commit_queue(server_state) -> None:
    """Create the process-wide PostCommitQueue (ADR-007 §6, C2.2) after the
    engine gate — it needs the SAME gate instance the doors' `generate` uses,
    so a background job and a user turn are never scheduling against two
    different doors into Metal. Starts its worker task immediately: nothing
    is queued yet, but the queue must be draining before the first request
    that queues something can arrive."""
    from core.turn.gate import attach_engine_gate
    from core.turn.post_commit import attach_post_commit_queue
    queue = attach_post_commit_queue(server_state, gate=attach_engine_gate(server_state))
    queue.start()
    server_state._post_commit_task = queue._task


def _expose_post_commit_queue(app, server_state) -> None:
    """Mirror the queue onto `app.state`, same reason as `_expose_engine_gate`
    above: `queue_for(ctx.app_state)` is what the UI door reads."""
    queue = getattr(server_state, "post_commit_queue", None)
    if queue is None:
        logger.warning("PostCommitQueue not attached on server_state — memory.write/compact run inline")
        return
    app.state.post_commit_queue = queue


async def _startup_memory_helper(server_state) -> None:
    """Create the process-wide MemoryHelper (ADR-007 §4, C3.0) — the memory
    brain lives in the core now, so /v1 can reach it without the UI plugin."""
    from core.memory_facts import attach_memory_helper
    attach_memory_helper(server_state)


def _expose_memory_helper(app, server_state) -> None:
    """Mirror the helper onto `app.state`, same reason as `_expose_engine_gate`
    above: `helper_for(ctx.app_state)` is what the doors read."""
    helper = getattr(server_state, "memory_helper", None)
    if helper is None:
        logger.warning("MemoryHelper not attached on server_state — memory operations will fail")
        return
    app.state.memory_helper = helper


async def _startup_context_presenter(server_state) -> None:
    """Create the process-wide ContextPresenter — how retrieved context frames
    itself, one piece for both doors instead of one per door."""
    from core.context_presentation import attach_context_presenter
    attach_context_presenter(server_state)


def _expose_context_presenter(app, server_state) -> None:
    """Mirror the presenter onto `app.state`, same reason as its neighbours:
    `frame_for(ctx.app_state, ...)` is what the `budget` step reads."""
    presenter = getattr(server_state, "context_presenter", None)
    if presenter is None:
        logger.warning("ContextPresenter not attached on server_state — turns will use the default framing")
        return
    app.state.context_presenter = presenter


async def _startup_file_handler(server_state) -> None:
    """Create the process-wide FileHandler (C4.3-b) — the web UI module used to
    build its own; now the core owns it, so /v1 can attach documents too."""
    from core.files import attach_file_handler
    attach_file_handler(server_state)


def _expose_file_handler(app, server_state) -> None:
    """Mirror the handler onto `app.state`, same reason as `_expose_memory_helper`
    above: `/v1/attachments` reads `request.app.state.file_handler`."""
    handler = getattr(server_state, "file_handler", None)
    if handler is None:
        logger.warning("FileHandler not attached on server_state — /v1/attachments will be unavailable")
        return
    app.state.file_handler = handler


async def _startup_session_cleanup(app, server_state) -> None:
    """Start the session cleanup background task (N-5 / N04)."""
    try:
        from core.sessions import start_session_cleanup_task
        session_mgr = getattr(server_state, "session_manager", None)
        if session_mgr is not None:
            server_state._session_cleanup_task = start_session_cleanup_task(session_mgr)
            logger.info("Session cleanup task started (runs every hour)")
        else:
            logger.warning("SessionManager not attached — session cleanup task skipped")
    except Exception as e:
        logger.warning("Could not start session cleanup task: %s", e)
