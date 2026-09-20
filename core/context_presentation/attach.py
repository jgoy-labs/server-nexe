"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/context_presentation/attach.py
Description: Bind the process-wide ContextPresenter onto ServerState.

Same idempotent-attach shape as core.sessions.attach.attach_session_manager,
core.memory_facts.attach.attach_memory_helper, core.files.attach.attach_file_handler,
core.turn.gate.attach_engine_gate and core.turn.post_commit.attach_post_commit_queue.

**Idempotence is the extension point.** `attach_*` returns what is already
there, so whoever puts a presenter on the state first wins. Today that is the
lifespan; the day a plugin brings one, this is where it lands without a line
changing here.

⚠️ **And here is the trap for that day.** `_expose_context_presenter` mirrors
the object onto `app.state` during startup, BEFORE module discovery runs
(`core/lifespan.py`). A plugin that assigns `server_state.context_presenter`
inside `initialize()` will NOT be seen by turns, which read `app_state`. When
that day comes it needs a setter that writes both, not a second attach — the
same "one registry, one brain" lesson `core/lifespan_sessions.py:27-35`
already paid for once, when /v1 conversations silently never reached disk.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging

from core.context_presentation.default import DefaultContextPresenter
from core.context_presentation.port import ContextFraming, ContextShape

logger = logging.getLogger(__name__)

#: The fallback, built once: stateless, so sharing it is free.
_DEFAULT = DefaultContextPresenter()


def attach_context_presenter(server_state):
    """Return the process-wide ContextPresenter, creating it once on server_state."""
    existing = getattr(server_state, "context_presenter", None)
    if existing is not None:
        return existing
    presenter = DefaultContextPresenter()
    server_state.context_presenter = presenter
    logger.info("ContextPresenter attached to server_state")
    return presenter


def frame_for(app_state, shape: ContextShape) -> ContextFraming:
    """This turn's framing prose, never an exception and never a surprise.

    Permissive like `gate_for` and unlike `helper_for`: a turn without framing
    is a turn with a plainer prompt, and losing the prompt's wording is not
    worth losing the answer. There is no silent-data-loss failure mode here
    (the one `helper_for` refuses to allow) — the retrieved content itself
    still reaches the model either way.

    🔴 **The return value is validated, not the presenter.** `runtime_checkable`
    checks that the ATTRIBUTES exist and nothing else, so a `MagicMock` — which
    `tests/core/test_fd_block4_budget_shared.py:150` really does pass as
    `app_state` — satisfies `ContextPresenter` and answers `.frame()` with
    another Mock. Formatted into the prompt, that is a literal
    `<MagicMock id=...>` shipped to the model. Checking what comes back against
    a concrete class is what a Protocol check cannot do for us.
    """
    presenter = getattr(app_state, "context_presenter", None)
    if presenter is None:
        return _DEFAULT.frame(shape)
    try:
        framing = presenter.frame(shape)
    except Exception as exc:  # a presenter never costs the turn
        logger.warning("ContextPresenter failed, using the default framing: %s", exc)
        return _DEFAULT.frame(shape)
    if not isinstance(framing, ContextFraming):
        logger.warning(
            "ContextPresenter returned %s, not ContextFraming — using the default",
            type(framing).__name__,
        )
        return _DEFAULT.frame(shape)
    return framing
