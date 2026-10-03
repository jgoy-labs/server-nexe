"""
────────────────────────────────────
Server Nexe
Location: tests/test_1022_one_emergency_system_prompt.py
Description: #1022 — the last-resort system prompt existed twice and the two
             copies had drifted.

                 core/endpoints/chat.py:168
                   "You are Nexe, an AI assistant. Respond clearly and helpfully."
                 plugins/web_ui_module/api/routes_chat.py:1742
                   "You are Nexe, a local AI assistant. Respond clearly and helpfully."

             One word apart, and the word matters: it is an instruction the
             model reads. Depending on which door a user came through, the
             model was or was not told it runs on this machine.

             The two are NESTED, not parallel — `core`'s is what
             `_get_system_prompt` returns when server.toml configures no
             prompt at all, and the UI's is what it falls back to when
             `_get_system_prompt` cannot be reached at all. That makes a single
             constant the right shape: it is the same last resort, one level
             apart.

             Decision, argued in the result: **"a local AI assistant" wins.**
             Every engine server-nexe can serve (MLX, llama.cpp, Ollama) runs
             on the machine, so of the two wordings it is the true one, and it
             is the one that stops a model offering to look something up on the
             web. `/v1` describing itself as non-local was the drift, not a
             deliberate difference between the doors.

             Home: `core/chat_prompt.py` — the module that already exists for
             system-prompt assembly shared by both doors (F-D blocks 1-2) and
             that both files already import from. A new file for one constant
             would have added an import nobody else needs.
────────────────────────────────────
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.chat_prompt import EMERGENCY_SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]
V1_DOOR = ROOT / "core" / "endpoints" / "chat.py"
UI_DOOR = ROOT / "plugins" / "web_ui_module" / "api" / "routes_chat.py"
# 2026-10-04: routes_chat.py was split; the door is now these files too — its
# alphabet, its engine call, and the steps that call them.
UI_API = ROOT / "plugins" / "web_ui_module" / "api"
UI_WIRE, UI_ENGINE_CALL, UI_STEPS = (UI_API / f for f in ("wire.py", "engine_call.py", "turn_adapters.py"))
# C4.2: the UI door's fallback moved into the core with the rest of the prompt
# assembly (`_build_system_prompt_with_time`), so the scan follows it — a copy
# reappearing in its new home is the same drift this file exists to catch.
PROMPT_HOME = ROOT / "core" / "turn" / "prompt.py"


def _string_constants(path: Path) -> list[str]:
    """Every string literal in a module, from its AST.

    Parsed, not grepped: this has to see a literal however it is spelled,
    concatenated or indented, and must not trip over the word appearing in a
    comment.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


class TestOneLiteral:

    def test_the_wording_is_the_local_one(self):
        """The decision itself, pinned. Dropping "local" is allowed — but it
        has to be someone's choice, not a drift."""
        assert EMERGENCY_SYSTEM_PROMPT == (
            "You are Nexe, a local AI assistant. Respond clearly and helpfully."
        )

    @pytest.mark.parametrize(
        "door", [V1_DOOR, UI_DOOR, UI_WIRE, UI_ENGINE_CALL, UI_STEPS, PROMPT_HOME],
        ids=["v1", "ui", "ui-wire", "ui-engine-call", "ui-steps", "prompt"],
    )
    def test_neither_door_carries_its_own_copy(self, door: Path):
        """A second literal is how the two drifted in the first place."""
        offenders = [s for s in _string_constants(door) if s.startswith("You are Nexe")]
        assert offenders == [], (
            f"{door.name} has its own copy of the emergency prompt again: "
            f"{offenders}. Import EMERGENCY_SYSTEM_PROMPT from core.chat_prompt."
        )

    def test_the_constant_is_exported(self):
        """Both doors import it by name; `__all__` is the module's contract."""
        import core.chat_prompt as chat_prompt
        assert "EMERGENCY_SYSTEM_PROMPT" in chat_prompt.__all__


class TestBothDoorsReturnIt:
    """Not "they contain the same text" — the same object, reached by running
    the real fallback on each side."""

    def test_the_v1_door_falls_back_to_the_constant(self):
        from core.turn.prompt import _get_system_prompt
        state = SimpleNamespace(config={"personality": {"prompt": {}}})
        assert _get_system_prompt(state, "en") is EMERGENCY_SYSTEM_PROMPT

    def test_the_v1_door_still_prefers_a_configured_prompt(self):
        """Mutation control: returning the constant unconditionally would pass
        the test above and throw away everyone's server.toml."""
        from core.turn.prompt import _get_system_prompt
        state = SimpleNamespace(
            config={"personality": {"prompt": {"en_full": "Ets el Nexe configurat"}}}
        )
        assert _get_system_prompt(state, "en") == "Ets el Nexe configurat"

    def test_the_ui_door_falls_back_to_the_same_constant(self):
        """The UI's fallback is the outer one: it fires when the core's
        resolver cannot be reached at all."""
        from core.turn import prompt as prompt_mod

        with patch("core.lifespan.get_server_state",
                   side_effect=RuntimeError("no server state")):
            prompt, lang = prompt_mod._build_system_prompt_with_time("hola", lang_hint="en")

        assert EMERGENCY_SYSTEM_PROMPT in prompt, (
            "the UI fell back to something that is not the shared constant"
        )
        assert lang == "en"

    def test_the_two_doors_agree_on_the_base(self):
        """The finding in one assertion: whatever each door falls back to, it
        is the same text."""
        from core.turn.prompt import _get_system_prompt
        from core.turn import prompt as prompt_mod

        v1_base = _get_system_prompt(SimpleNamespace(config={}), "en")
        with patch("core.lifespan.get_server_state", side_effect=RuntimeError("down")):
            ui_prompt, _ = prompt_mod._build_system_prompt_with_time("hola", lang_hint="en")

        assert v1_base in ui_prompt
        assert v1_base is EMERGENCY_SYSTEM_PROMPT

    def test_the_ui_door_uses_the_core_resolver_when_it_can(self):
        """The nesting, pinned: the UI's own literal is the LAST resort, not
        the normal path — it must not shadow a configured prompt."""
        from core.turn import prompt as prompt_mod

        state = MagicMock()
        state.config = {"personality": {"prompt": {"en_full": "Configurat des del TOML"}}}
        with patch("core.lifespan.get_server_state", return_value=state):
            prompt, _ = prompt_mod._build_system_prompt_with_time("hola", lang_hint="en")

        assert "Configurat des del TOML" in prompt
        assert EMERGENCY_SYSTEM_PROMPT not in prompt
