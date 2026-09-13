"""One `authorize` for both chat doors, fail-closed (ADR-007, C4.1, #1044).

The two doors answered the SAME misconfiguration — a server with no valid API
key material — in opposite ways. Quoted, not paraphrased, from
`kickoff-una-sola-canonada-20260831.md` §2.3:

  «**Auth oposada** en el mateix escenari: A cau a `_check_dev_mode` i pot obrir
  (`auth_dependencies.py:288`); B fa **503 fail-closed** (`:213-222`).
  **Mana la de B.**»

A is `/v1/chat/completions`, B is `/ui/chat`. So the chat door is fail-closed at
both entries from here on: a turn whose principal is missing, or is the
`dev-mode-bypass` label `_check_dev_mode` hands out, does not run.

**Radius, deliberately minimal (#1044).** `_check_dev_mode`
(`core/security/auth_dependencies.py:150`) is NOT touched. It guards ~28 other
endpoints — the metrics, bootstrap, system, root, modules and four plugin
routers — and tipping it over globally is a different decision with a different
blast radius. What changes is the chat door: `require_api_key` now remembers the
principal it already computed (`request.state.principal`, which nothing wrote
before C4.1), the door copies it into the turn, and this step refuses the
bypass. `GET /admin/system/status` and its siblings keep opening in dev mode,
and `tests/core/turn/test_authorize_fail_closed.py` measures both halves.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from core.turn.context import TurnContext

logger = logging.getLogger(__name__)

#: What `_check_dev_mode` returns when it waves a request through
#: (`core/security/auth_dependencies.py:182`). A label, not a credential.
DEV_MODE_BYPASS = "dev-mode-bypass"

#: The same 503 body `authenticate_ui_request` has always answered with
#: (`auth_dependencies.py:325`), so the two doors also fail alike.
FAIL_CLOSED_DETAIL = "API key not configured (FAIL CLOSED)"


async def authorize_turn(ctx: TurnContext) -> None:
    """Refuse the turn unless the door authenticated a real principal.

    503, not 401: nothing is wrong with the request — the SERVER has no key
    material configured, which is a misconfiguration the operator has to fix.
    That is the answer `/ui/chat` has always given, and the one the 31/08
    decision quoted in the module docstring says wins.
    """
    principal = (ctx.principal or "").strip()
    if not principal:
        logger.error(
            "chat turn refused: no principal on the turn (FAIL CLOSED). "
            "The 31/08 decision: auth is opposed at the two doors for the same "
            "misconfiguration, and the fail-closed one wins (#1044)."
        )
        raise HTTPException(status_code=503, detail=FAIL_CLOSED_DETAIL)
    if principal == DEV_MODE_BYPASS:
        logger.error(
            "chat turn refused: NEXE_DEV_MODE bypassed authentication and the "
            "server has no valid API key (FAIL CLOSED). The 31/08 decision: "
            "«A cau a _check_dev_mode i pot obrir; B fa 503 fail-closed. Mana "
            "la de B.» The administration endpoints are unaffected (#1044)."
        )
        raise HTTPException(status_code=503, detail=FAIL_CLOSED_DETAIL)
