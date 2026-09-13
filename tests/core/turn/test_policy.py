"""The product decisions of a turn, in the core (ADR-007 C3.5).

D3 — whether a turn that cleaned down to nothing but [MEM_SAVE:] tags earns a
second LLM call — lived inside the web UI plugin, so /v1 answered such a turn
with a 200 and an empty body while /ui/chat answered with a confirmation.
"""

from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks

from core.endpoints.chat import chat_completions  # noqa: F401 — breaks a circular import
from core.turn import policy
from core.turn.adapters_api import api_adapters
from core.turn.context import TurnContext


class TestTheFlag:

    def test_default_is_on(self, monkeypatch):
        monkeypatch.delenv(policy.ENV_REPROMPT_IF_ONLY_MEMSAVE, raising=False)
        assert policy.reprompt_enabled() is True

    def test_it_can_be_switched_off(self, monkeypatch):
        for off in ("0", "false", "no", "off", "OFF"):
            monkeypatch.setenv(policy.ENV_REPROMPT_IF_ONLY_MEMSAVE, off)
            assert policy.reprompt_enabled() is False, off

    def test_it_is_read_fresh_every_time(self, monkeypatch):
        """A runtime toggle must take effect on the next turn, not on restart."""
        monkeypatch.setenv(policy.ENV_REPROMPT_IF_ONLY_MEMSAVE, "false")
        assert policy.reprompt_enabled() is False
        monkeypatch.setenv(policy.ENV_REPROMPT_IF_ONLY_MEMSAVE, "true")
        assert policy.reprompt_enabled() is True


class TestTheConfirmation:

    def test_it_names_the_facts(self):
        assert policy.mem_save_fallback_text(["el gat es diu Mite"]) == "Memòria desada: el gat es diu Mite"

    def test_it_joins_several(self):
        out = policy.mem_save_fallback_text(["un fet", "un altre"])
        assert "un fet" in out and "un altre" in out

    def test_nothing_to_confirm_means_no_text(self):
        assert policy.mem_save_fallback_text([]) == ""
        assert policy.mem_save_fallback_text(["", "   "]) == ""


class TestBothDoorsShareIt:

    def test_the_override_covers_the_three_languages(self):
        assert set(policy.REPROMPT_OVERRIDE) == {"ca", "es", "en"}
        for text in policy.REPROMPT_OVERRIDE.values():
            assert "MEM_SAVE" in text

    async def test_v1_no_longer_answers_a_memsave_only_turn_with_an_empty_body(self):
        """#856 at the other door: the tag was stripped and nothing was left."""
        ctx = TurnContext(turn_id="t", entry="api")
        ctx.message = "recorda que visc a Manresa"
        ctx.wire = {
            "choices": [{"message": {"role": "assistant", "content": "[MEM_SAVE: L'usuari viu a Manresa]"}}],
        }

        await api_adapters(BackgroundTasks())["postprocess"](ctx)

        content = ctx.wire["choices"][0]["message"]["content"]
        assert content, "a MEM_SAVE-only turn still returns an empty body at /v1"
        assert "L'usuari viu a Manresa" in content
        assert "MEM_SAVE" not in content

    async def test_the_missing_half_of_d3_is_declared_not_hidden(self):
        """/v1 does not re-enter `generate` for a real reply yet — the trace
        says so instead of the product quietly differing between doors."""
        ctx = TurnContext(turn_id="t", entry="api")
        ctx.message = "recorda que visc a Manresa"
        ctx.wire = {"choices": [{"message": {"content": "[MEM_SAVE: L'usuari viu a Manresa]"}}]}

        await api_adapters(BackgroundTasks())["postprocess"](ctx)

        assert ctx.usage.get("degraded", {}).get("reprompt")

    def test_the_policy_left_the_plugin(self):
        import plugins.web_ui_module.api.routes_chat as rc

        assert not hasattr(rc, "_reprompt_enabled")
        assert not hasattr(rc, "_mem_save_fallback_text")
        assert not hasattr(rc, "_REPROMPT_OVERRIDE")
