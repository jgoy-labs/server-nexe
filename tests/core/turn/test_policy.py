"""The product decisions of a turn, in the core (ADR-007 C3.5).

D3 — whether a turn that cleaned down to nothing but [MEM_SAVE:] tags earns a
second LLM call — lived inside the web UI plugin, so /v1 answered such a turn
with a 200 and an empty body while /ui/chat answered with a confirmation.
C4.5 (26/09): the second call itself is the core's (`reprompt_chunks`), /v1
spends it too, and the stand-in when it yields nothing is a neutral phrase.
"""

from unittest.mock import AsyncMock, MagicMock, patch

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


class TestTheStandIn:
    """C4.5 (decision 1, 26/09): when the second reply does not come, the user
    reads a neutral phrase in the turn's language — never a "saved" built from
    the model's tags before the server decided (the lie #1098 took off the badge)."""

    def test_it_speaks_the_turns_language(self):
        assert policy.empty_reply_text("ca") == "D'acord."
        assert policy.empty_reply_text("es") == "De acuerdo."
        assert policy.empty_reply_text("en") == "Okay."

    def test_an_unknown_language_falls_back_to_english(self):
        assert policy.empty_reply_text("fr") == "Okay."
        assert policy.empty_reply_text("ca-ES") == "D'acord."

    def test_it_never_claims_a_save(self):
        for lang in ("ca", "es", "en", None, "de"):
            text = policy.empty_reply_text(lang).lower()
            assert "desad" not in text and "guardad" not in text and "saved" not in text

    def test_the_old_confirmation_is_gone(self):
        assert not hasattr(policy, "mem_save_fallback_text")


class TestBothDoorsShareIt:

    def test_the_override_covers_the_three_languages(self):
        assert set(policy.REPROMPT_OVERRIDE) == {"ca", "es", "en"}
        for text in policy.REPROMPT_OVERRIDE.values():
            assert "MEM_SAVE" in text

    async def test_v1_no_longer_answers_a_memsave_only_turn_with_an_empty_body(self):
        """#856 at the other door: the tag was stripped and nothing was left.

        A bare turn (no request, no engine to reach): the second call fails, so
        what comes back is the neutral stand-in — never an empty body, never the
        tag, and (C4.5) never a "saved" the server has not confirmed."""
        ctx = TurnContext(turn_id="t", entry="api", lang="ca")
        ctx.message = "recorda que visc a Manresa"
        ctx.wire = {
            "choices": [{"message": {"role": "assistant", "content": "[MEM_SAVE: L'usuari viu a Manresa]"}}],
        }

        await api_adapters(BackgroundTasks())["postprocess"](ctx)

        content = ctx.wire["choices"][0]["message"]["content"]
        assert content == policy.empty_reply_text("ca"), content
        assert "MEM_SAVE" not in content
        assert "reprompt" not in ctx.usage.get("degraded", {})

    async def test_v1_spends_the_second_generation_and_counts_it_once(self):
        """D3, whole (C4.5): a MEM_SAVE-only turn re-enters the cascade for a
        real reply — the trace no longer declares a missing half, it counts one
        `reprompt` call against the model that served, and the model is asked
        under the override in the turn's language."""
        ctx = TurnContext(turn_id="t", entry="api", lang="ca", engine="ollama")
        ctx.message = "recorda que visc a Manresa"
        ctx.prompt = [{"role": "system", "content": "sys"}, {"role": "user", "content": ctx.message}]
        ctx.wire = {"choices": [{"message": {"content": "[MEM_SAVE: L'usuari viu a Manresa]"}}], "model": "llama3"}
        second = {"choices": [{"message": {"content": "Perfecte, ho recordaré."}}], "model": "llama3"}
        cascade = AsyncMock(return_value=(second, "ollama", None, "preferred_unavailable", "llama3"))

        with patch("core.endpoints.chat._dispatch_through_cascade", new=cascade):
            await api_adapters(BackgroundTasks())["postprocess"](ctx)

        assert ctx.wire["choices"][0]["message"]["content"] == "Perfecte, ho recordaré."
        assert "reprompt" not in ctx.usage.get("degraded", {})
        calls = ctx.usage["llm"]["calls"]
        assert [c["step"] for c in calls] == ["reprompt"]
        assert calls[0]["engine"] == "ollama" and calls[0]["model"] == "llama3"
        asked = cascade.await_args.args[2]
        assert asked[0]["role"] == "system" and asked[0]["content"].endswith(policy.REPROMPT_OVERRIDE["ca"])
        assert asked[1:] == ctx.prompt[1:]

    async def test_v1_reprompt_is_the_only_second_call_and_off_means_none(self, monkeypatch):
        monkeypatch.setenv(policy.ENV_REPROMPT_IF_ONLY_MEMSAVE, "false")
        ctx = TurnContext(turn_id="t", entry="api", lang="en", engine="ollama")
        ctx.message = "remember I live in Manresa"
        ctx.wire = {"choices": [{"message": {"content": "[MEM_SAVE: The user lives in Manresa]"}}]}
        cascade = AsyncMock()

        with patch("core.endpoints.chat._dispatch_through_cascade", new=cascade):
            await api_adapters(BackgroundTasks())["postprocess"](ctx)

        cascade.assert_not_awaited()
        assert ctx.wire["choices"][0]["message"]["content"] == policy.empty_reply_text("en")
        assert "llm" not in ctx.usage

    def test_the_policy_left_the_plugin(self):
        import plugins.web_ui_module.api.routes_chat as rc

        assert not hasattr(rc, "_reprompt_enabled")
        assert not hasattr(rc, "_mem_save_fallback_text")
        assert not hasattr(rc, "_REPROMPT_OVERRIDE")
        # C4.5: the second call and the delete rule left too — no door keeps a copy.
        for gone in ("_yield_reprompt", "_reprompt_nonstreaming", "_postprocess_nonstreaming",
                     "NonStreamRepromptContext", "_arm_mem_deletes_nonstreaming",
                     "_yield_mem_delete_prompts", "_yield_reprompt_when_only_mem_saves"):
            assert not hasattr(rc, gone), gone
