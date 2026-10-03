"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_chat.py
Description: POST /chat endpoint: the route that walks TURN_STEPS.
             Extracted from routes.py during tech debt refactoring. The
             door's alphabet is wire.py and its engine call engine_call.py
             (split out on 2026-10-04); the steps are turn_adapters.py.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from typing import Dict, Any
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends, Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from core.dependencies import limiter
# The adapters (`turn_adapters.py`) reach these three through this module, at
# call time (`_rc()`); tests read `_assemble_engine_messages` here.
from core.turn.cancel import start_disconnect_monitor as _start_disconnect_monitor  # noqa: F401
from core.turn.assemble import _assemble_engine_messages, _build_turn_context  # noqa: F401
from core.turn.context import TurnContext
from core.turn.lease import release_turn_lease, releasing
from core.turn.post_commit import queue_for
from core.turn.run import run_turn, stream_turn
from plugins.web_ui_module.api.turn_adapters import ui_adapters

from core.context_budget import (  # noqa: F401 — re-exported for tests and callers
    compute_context_budget,
    _inject_context_into_messages,
)


def register_chat_routes(router: APIRouter, *, session_mgr, require_ui_auth):
    """Registers endpoint: POST /chat"""

    # P0-3's lock around body.model singleton mutations now lives with the
    # switch it guards (core.endpoints.chat_engines.model_switch), because what
    # it protects — LlamaCppChatNode._pool / MLXChatNode._model — is
    # process-global while this function runs once per router. Its reasoning is
    # unchanged and is written there: server-nexe is architecturally mono-user
    # (workers=1, class-level singletons), so the race is a breadcrumb for a
    # future multi-user design rather than something seen in the field.

    # -- POST /chat --
    #    The route only: it builds the TurnContext and walks TURN_STEPS
    #    (intent detection, RAG, compaction and the engines are steps).

    @router.post("/chat", operation_id="webui_chat")
    @limiter.limit("20/minute")
    async def chat(request: FastAPIRequest, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Chat endpoint with streaming and memory intent detection.

        Concurrency is the engine gate's job now (ADR-007 §7, C2.1,
        core/turn/gate.py) — held by `generate_stream`/`generate_json` for as
        long as their body is being driven, not by this route for as long as
        it takes to get a `StreamingResponse` OBJECT back (that used to be the
        whole of the old `Semaphore(2)` here: it released before a single
        token was generated).
        """
        return await _chat_inner(request, body, _auth)

    async def _chat_inner(request: FastAPIRequest, body: Dict[str, Any], _auth):
        """Inner chat logic: validates the session id and walks the turn."""
        session_id = body.get("session_id")
        # RT-10: clean 400 for malformed/traversal session ids (see routes_files).
        if session_id is not None and not session_mgr.is_valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        stream = body.get("stream", False)

        # ADR-007 (C1.3): from here on this door no longer decides the order of
        # the turn. It builds a TurnContext and lets the engine walk TURN_STEPS;
        # every step is an adapter in `turn_adapters.py` wrapping the functions
        # this body used to call. Two tables, one per wire format, because four
        # steps really differ between them. C4.6: FD-S6's Continue is a turn
        # too — `resume` tells the steps; it no longer has a path of its own.
        ctx = TurnContext(
            turn_id=uuid4().hex,
            entry="ui",
            # C4.1 (#1044): WHO `require_ui_auth` authenticated, recorded on the
            # request by `auth_dependencies._remember_principal`. This door was
            # already fail-closed, so the turn's `authorize` step never fires
            # here — it is filled so there is ONE step, not a step and an
            # exception for the door that happened to be right.
            principal=getattr(getattr(request, "state", None), "principal", None),
            streaming=bool(stream),
            resume=body.get("continue") is True,
            body=body,
            request=request,
            app_state=request.app.state,
        )
        return await _walk_turn(ctx, bool(stream))

    async def _walk_turn(ctx: TurnContext, stream: bool):
        """The turn, walked through `TURN_STEPS` in this door's wire shape.

        #1105: a turn that fails after `session` gives the lease back — before
        this, only `emit`, the disconnect path and a short-circuit did, and the
        next message of the conversation got the 409 for the lease's whole TTL.
        In streaming the failure can come after the response is committed
        (`generate` runs inside the body), hence the wrapper on the body too.
        """
        adapters = ui_adapters(session_mgr, streaming=stream)
        # C2.2: memory.write/compact go to the post-commit queue when a real
        # one is attached (production always has one — the lifespan attaches
        # it next to the engine gate); None here makes them run inline,
        # exactly as before C2.2 — the fallback pre-C2.2 test harnesses need.
        post_commit = queue_for(ctx.app_state)
        try:
            if stream:
                body_iterator = await stream_turn(ctx, adapters, post_commit=post_commit)
            else:
                await run_turn(ctx, adapters, post_commit=post_commit)
        except BaseException:
            release_turn_lease(session_mgr, ctx)
            raise
        if stream:
            return StreamingResponse(
                releasing(body_iterator, session_mgr, ctx),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff",
                    # The session this turn was stored in: a client that lost
                    # its id (or never learned the one the server minted for
                    # it) has a way back instead of starting a new conversation.
                    "X-Session-Id": ctx.session.id,
                    # C2.0: one id to grep for in `turn.trace` log lines.
                    "X-Nexe-Turn-Id": ctx.turn_id,
                },
            )
        return ctx.wire
