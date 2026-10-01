"""Golden master for the #965 Phase-1 split: the context-budget group leaves routes_chat.py.

Written against the UNSPLIT module and green before every move. The split is
supposed to be a move: same code, different file. These tests hold the parts
that a move can break silently — the wiring nothing else asserts.

Assertions here are not to be edited while the split runs. A move that needs
one of them changed is not a move: it changed behaviour.

The three functions moving out (`compute_context_budget`, `_inject_context_into_messages`,
`_assemble_engine_messages`) are module-level functions, not closures of
`register_chat_routes` — which is why they can leave without touching the two
frozen closures (`_handle_chat_engine` CCN 38, `_chat_inner` CCN 28) that stay behind.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import APIRouter

from core import context_budget
from plugins.web_ui_module.api import routes_chat

# The names that must keep resolving from `routes_chat` after the move, because
# production code and tests reach for them there:
#   compute_context_budget        -> tests/plugins/web_ui_module/test_context_budget_history.py:16
#   _inject_context_into_messages -> tests/core/endpoints/test_b030_untrusted_context.py:172
#   _assemble_engine_messages     -> called by _handle_chat_engine inside register_chat_routes
MOVING_NAMES = (
    "compute_context_budget",
    "_inject_context_into_messages",
    "_assemble_engine_messages",
)

# C4.2: the same "exactly one definition" guard, for the eleven symbols the
# prompt assembly moved out of the plugin into `core/turn/{prompt,recall,
# assemble}.py`. A separate tuple because the two contracts are different:
# `MOVING_NAMES` above must also RESOLVE from `routes_chat` (production and
# tests reach for them there), and most of these must not — only the three the
# FD-S6 `continue` path still calls do.
#
# Audit finding (09/09): the reason given for keeping the moved symbols' names
# was "so `TestOneDefinitionPerName` stays the gate", and that was true of
# `_assemble_engine_messages` alone — the other ten were outside the scan. No
# fork exists today (each is defined exactly once, measured), so this is a
# guard for the NEXT move: C4.3 touches these files again.
C42_MOVED_NAMES = (
    "_collections_prompt_overrides",   # core/turn/prompt.py
    "_resolve_session_lang",           # core/turn/prompt.py
    "_finalize_system_prompt",         # core/turn/prompt.py
    "_get_system_prompt",              # core/turn/prompt.py (was core/endpoints/chat.py)
    "_build_system_prompt_with_time",  # core/turn/prompt.py
    "turn_system_prompt",              # core/turn/prompt.py (the shared step)
    "_build_rag_context",              # core/turn/recall.py
    "_build_turn_context",             # core/turn/assemble.py
    "_build_document_context",         # core/turn/assemble.py
)

#: Every name whose definition must be unique across `core/` and `plugins/`.
ONE_DEFINITION_ONLY = MOVING_NAMES + C42_MOVED_NAMES

WEB_UI_ROOT = Path(routes_chat.__file__).parent.parent  # plugins/web_ui_module/

# F-D block 4 moved compute_context_budget and _inject_context_into_messages out
# of the plugin and into core/context_budget.py, so "exactly once" can no longer
# be checked inside the plugin alone — there it would now be zero, and a scan
# that cannot see the new home cannot see a fork either. Both product packages
# are scanned instead, which is strictly stronger than the original check.
# Derived from the modules themselves, never by counting parents: this file's
# sibling broke that way when it moved one level up.
CORE_ROOT = Path(context_budget.__file__).parent  # core/
SCAN_ROOTS = (CORE_ROOT, WEB_UI_ROOT.parent)  # core/, plugins/


class TestTheRouteSurface:
    """`POST /chat` with operation_id `webui_chat` is the contract with the web UI
    AND with the CLI — both post to /ui/chat (tests/test_cli_ui_shared_pipeline.py).
    A decorator lost in a move takes the whole chat off the air, and no unit test
    of a moved function would notice."""

    def _register(self) -> APIRouter:
        router = APIRouter()
        routes_chat.register_chat_routes(
            router,
            session_mgr=MagicMock(),
            require_ui_auth=AsyncMock(return_value=None),
        )
        return router

    def test_the_chat_route_is_registered_with_its_operation_id(self) -> None:
        router = self._register()
        actual = {
            (method, route.path, route.operation_id)
            for route in router.routes
            for method in route.methods
            if method != "HEAD"
        }
        assert ("POST", "/chat", "webui_chat") in actual, (
            f"POST /chat (webui_chat) must stay registered; router exposes {actual}"
        )

    def test_exactly_one_route_is_registered(self) -> None:
        """The factory registers one endpoint. Two would mean a decorator was
        duplicated in a move; zero, that one was lost — and asserting only that
        /chat is present would catch neither."""
        router = self._register()
        paths = [getattr(r, "path", None) for r in router.routes]
        assert paths == ["/chat"], f"expected exactly POST /chat, got {paths}"


class TestTheMovingNamesStayReachable:
    """After the move `routes_chat` re-exports them (the pattern already used for
    `compact_session`, routes_chat.py:67-70). Reaching them by the old name must
    keep working."""

    def test_every_moving_name_resolves_from_routes_chat(self) -> None:
        for name in MOVING_NAMES:
            assert hasattr(routes_chat, name), (
                f"{name} no longer resolves from routes_chat — the re-export is missing"
            )
            assert callable(getattr(routes_chat, name))

    def test_the_re_exported_names_are_the_moved_module_s_own(self) -> None:
        """Identity, not just presence: a stale copy left behind in routes_chat
        would pass a hasattr check while quietly diverging from the real one."""
        from core import context_budget

        assert routes_chat.compute_context_budget is context_budget.compute_context_budget
        assert routes_chat._inject_context_into_messages is context_budget._inject_context_into_messages

    def test_the_assembler_still_calls_both(self) -> None:
        """Source-level check (the calls sit inside a long function, so there is
        no seam to observe them at) — it catches a call deleted in a move, not a
        call rerouted to a copy. The identity test above covers that."""
        import inspect

        src = inspect.getsource(routes_chat._assemble_engine_messages)
        assert "compute_context_budget(" in src
        assert "_inject_context_into_messages(" in src


class TestOneDefinitionPerName:
    """A move leaves exactly one definition. Two `def compute_context_budget` in the
    package means the copy was added and the original never deleted — the classic
    way a split silently forks behaviour."""

    def test_each_moving_name_is_defined_exactly_once_in_the_package(self) -> None:
        for name in ONE_DEFINITION_ONLY:
            hits = []
            for root in SCAN_ROOTS:
                for path in sorted(root.rglob("*.py")):
                    if "__pycache__" in str(path):
                        continue
                    for lineno, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), start=1
                    ):
                        stripped = line.lstrip()
                        if stripped.startswith(f"def {name}(") or stripped.startswith(
                            f"async def {name}("
                        ):
                            hits.append(f"{path.relative_to(root.parent)}:{lineno}")
            assert len(hits) == 1, (
                f"{name} must be defined exactly once across core/ and plugins/; found {hits}"
            )


class TestTheBudgetArithmeticIsUnchanged:
    """Pinned outputs of the pure function. The move must not touch a single
    number; Phase 5 changes where `max_context_chars` COMES FROM, never how the
    budget is computed from it."""

    def test_history_floor_wins_when_history_is_short(self) -> None:
        b = routes_chat.compute_context_budget(
            max_context_chars=24000,
            system_chars=1000,
            history_chars=2000,
            message_chars=100,
            document_chars=0,
        )
        assert b == {
            "history_reserve": 7200,
            "history_effective": 7200,
            "available_chars": 15200,
            "doc_truncated_pct": 0,
            "doc_kept_chars": 0,
        }

    def test_real_history_wins_when_it_exceeds_the_floor(self) -> None:
        b = routes_chat.compute_context_budget(
            max_context_chars=24000,
            system_chars=1000,
            history_chars=12000,
            message_chars=100,
            document_chars=0,
        )
        assert b["history_effective"] == 12000, "the floor is a minimum, never a ceiling"
        assert b["history_reserve"] == 7200
        assert b["available_chars"] == 10400

    def test_document_too_big_is_truncated_and_reports_the_percentage(self) -> None:
        b = routes_chat.compute_context_budget(
            max_context_chars=24000,
            system_chars=1000,
            history_chars=2000,
            message_chars=100,
            document_chars=20000,
        )
        assert b["doc_kept_chars"] == 15200
        assert b["doc_truncated_pct"] == 24

    def test_document_that_fits_is_kept_whole(self) -> None:
        b = routes_chat.compute_context_budget(
            max_context_chars=24000,
            system_chars=1000,
            history_chars=2000,
            message_chars=100,
            document_chars=5000,
        )
        assert b["doc_kept_chars"] == 5000
        assert b["doc_truncated_pct"] == 0

    def test_available_chars_may_go_negative_and_is_not_clamped(self) -> None:
        """Documented behaviour of the current function; the injection site is what
        guards on `available_chars > 0`, not the arithmetic."""
        b = routes_chat.compute_context_budget(
            max_context_chars=1000,
            system_chars=500,
            history_chars=2000,
            message_chars=100,
            document_chars=0,
        )
        assert b["available_chars"] == -2100
        assert b["doc_kept_chars"] == 0

    def test_history_ratio_is_clamped_to_the_documented_range(self) -> None:
        high = routes_chat.compute_context_budget(
            max_context_chars=10000,
            system_chars=0,
            history_chars=0,
            message_chars=0,
            document_chars=0,
            history_ratio=2.0,
        )
        assert high["history_reserve"] == 9000, "ratio clamps at 0.9"

        low = routes_chat.compute_context_budget(
            max_context_chars=10000,
            system_chars=0,
            history_chars=0,
            message_chars=0,
            document_chars=0,
            history_ratio=-1.0,
        )
        assert low["history_reserve"] == 0, "ratio clamps at 0.0"


class TestTheEngineReachesTheBudget:
    """The wiring the other tests cannot see: drop `engine` from the call site
    and the budget silently falls back to the default window on every turn,
    with every test in this suite still green."""

    def test_the_call_site_passes_the_engine(self) -> None:
        # C4.6: the only call site left is the turn's `budget` adapter (the
        # Continue path that also called it is a turn now). Read as a syntax
        # tree: its arguments nest parentheses a regex would stop inside.
        import ast
        import inspect
        import textwrap

        from plugins.web_ui_module.api import turn_adapters

        tree = ast.parse(textwrap.dedent(inspect.getsource(turn_adapters.ui_adapters)))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "_assemble_engine_messages"
        ]
        assert len(calls) == 1, "the budget step must call _assemble_engine_messages, once"
        passed = [ast.unparse(a) for a in calls[0].args] + [ast.unparse(k.value) for k in calls[0].keywords]
        assert "ctx.engine" in passed, (
            "#965: the live engine must reach _assemble_engine_messages, or the "
            "budget quietly reverts to the default window"
        )
