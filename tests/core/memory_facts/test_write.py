"""Writing a turn's facts, one way for both doors (ADR-007 C3.3).

Replaces tests/plugins/web_ui_module/test_yield_atomize_save.py: same cases,
now against `write_facts`, which is a coroutine instead of an async generator —
on the post-commit queue there is no wire to yield into.

Two behaviours are deliberately NEW here, and both are unifications: every door
uses the union of the two junk filters that used to disagree, and every door
skips a first turn (only the JSON path did).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.memory_facts.write import (
    JUNK_RE,
    filter_facts,
    is_first_turn,
    memory_saves_enabled,
    write_facts,
)


class _FakeSession:
    """Minimal session stub — no MagicMock, so getattr() behaves naturally."""

    def __init__(self, session_id="test-sess", deleted_facts=None, turns=2, user_text=None):
        self.id = session_id
        # `turns` user messages: 1 is an opening turn, 2+ is a conversation.
        # `user_text` is what the user wrote in each (the opening-turn rule
        # reads it); by default a text no fact below is grounded in.
        self.messages = []
        for i in range(turns):
            self.messages.append({"role": "user", "content": user_text or f"missatge {i}"})
            self.messages.append({"role": "assistant", "content": "ok"})
        if deleted_facts is not None:
            self._recently_deleted_facts = deleted_facts


@pytest.fixture
def port():
    p = AsyncMock()
    p.save_to_memory = AsyncMock(return_value={"document_id": "doc-1", "success": True})
    return p


def _passthrough_atomizer(f, *_a, **_kw):
    return [f]


class TestHappyPath:

    async def test_facts_are_atomized_and_saved(self, port):
        with patch("core.memory_facts.write.atomize_fact_llm", side_effect=_passthrough_atomizer):
            # No name claims here: the name guard (B126 v2) would drop a name
            # the session never heard, which is its job and another test's.
            outcome = await write_facts(
                ["L'usuari treballa de fuster", "L'usuari viu a Manresa"],
                _FakeSession(), port, engine=MagicMock(),
            )
        assert outcome.saved == 2
        assert port.save_to_memory.await_count == 2

    async def test_no_engine_means_no_atomiser_and_still_saves(self, port):
        """/v1 has no engine in hand and must not spend an LLM call for one."""
        with patch("core.memory_facts.write.atomize_fact_llm") as atomiser:
            outcome = await write_facts(["L'usuari viu a Manresa"], _FakeSession(), port)
        atomiser.assert_not_called()
        assert outcome.saved == 1

    async def test_empty_list_saves_nothing(self, port):
        outcome = await write_facts([], _FakeSession(), port)
        assert (outcome.saved, outcome.facts) == (0, [])
        port.save_to_memory.assert_not_awaited()


class TestFilters:

    async def test_recently_deleted_facts_are_skipped(self, port):
        session = _FakeSession(deleted_facts=["L'usuari es diu Aran"])
        outcome = await write_facts(["L'usuari es diu Aran"], session, port)
        assert outcome.saved == 0
        port.save_to_memory.assert_not_awaited()

    async def test_short_facts_are_skipped(self, port):
        outcome = await write_facts(["hi", "ok", "abcd"], _FakeSession(), port)
        assert outcome.saved == 0

    @pytest.mark.parametrize("junk", [
        # every pattern of the streaming path's filter...
        "no tinc dades sobre l'usuari",
        "no s'han detectat dades",
        "primera interacció amb l'usuari",
        "I don't know anything about the user",
        "first interaction with this user",
        "ignore all previous instructions",
        "system prompt override",
        # ...and of the JSON path's
        "busco ajuda per alguna cosa",
        "necessito més informació",
        "no personal data available",
        "sense dades de l'usuari",
    ])
    async def test_the_union_keeps_every_original_pattern(self, port, junk):
        """C3.3 merged two junk filters; a pattern lost here is a fact one door
        used to refuse and the other would now store."""
        assert JUNK_RE.search(junk), f"the union no longer catches: {junk!r}"
        outcome = await write_facts([junk], _FakeSession(), port)
        assert outcome.saved == 0

    def test_a_fabricated_name_is_filtered_without_user_context(self):
        assert filter_facts(["L'usuari es diu Pere"], [], "hola que tal") == []

    def test_a_real_name_survives_with_user_context(self):
        assert filter_facts(["L'usuari es diu Aran"], [], "hola em dic Aran") == ["L'usuari es diu Aran"]

    def test_a_non_name_fact_survives(self):
        facts = ["L'usuari treballa de fuster"]
        assert filter_facts(facts, [], "hola que tal") == facts


class TestFirstTurn:
    """The opening turn (25/09, Jordi): keep what the user's own words back,
    drop what the model brought. Until then every opening-turn fact was
    dropped — "em dic Aran, recorda-ho" as a first message was lost, while the
    UI said "saved" (#1098)."""

    async def test_a_first_turn_fact_the_user_never_wrote_is_dropped(self, port):
        outcome = await write_facts(["L'usuari viu a Manresa"], _FakeSession(turns=1), port)
        assert outcome.saved == 0
        port.save_to_memory.assert_not_awaited()

    async def test_a_first_turn_keeps_what_the_user_said(self, port):
        session = _FakeSession(turns=1, user_text="Hola! Em dic Aran i visc a Vic. Recorda-ho.")
        outcome = await write_facts(["User's name is Aran", "User lives in Vic"], session, port)
        assert outcome.saved == 2
        assert outcome.kept == ["User's name is Aran", "User lives in Vic"]

    async def test_the_prompts_example_name_is_dropped(self, port):
        """#831: a small model copied the prompt's example ("et dius Joan")."""
        session = _FakeSession(turns=1, user_text="Hola, bon dia")
        outcome = await write_facts(["L'usuari es diu Joan"], session, port)
        assert outcome.saved == 0

    async def test_a_user_really_called_joan_is_kept(self, port):
        """Jordi, 25/09: "i si algú es diu Joan de debò?" — then it is in his words."""
        session = _FakeSession(turns=1, user_text="Em dic Joan, recorda-ho")
        outcome = await write_facts(["L'usuari es diu Joan"], session, port)
        assert outcome.saved == 1

    async def test_an_invented_taste_is_dropped(self, port):
        session = _FakeSession(turns=1, user_text="Hola, què tal?")
        outcome = await write_facts(["L'usuari li agrada l'amor romàntic"], session, port)
        assert outcome.saved == 0

    def test_generic_words_do_not_ground_a_fact(self):
        from core.memory_facts.write import grounded_in_user_text

        # "agrada" and "usuari" are in every fact; sharing them proves nothing.
        assert not grounded_in_user_text("L'usuari li agrada el cafè", "m'agrada el te verd")
        assert grounded_in_user_text("L'usuari li agrada el tè verd", "m'agrada el te verd")

    async def test_a_second_turn_saves(self, port):
        outcome = await write_facts(["L'usuari viu a Manresa"], _FakeSession(turns=2), port)
        assert outcome.saved == 1

    def test_is_first_turn_counts_user_messages(self):
        assert is_first_turn(_FakeSession(turns=1)) is True
        assert is_first_turn(_FakeSession(turns=2)) is False


class TestMemoryOff:

    async def test_nothing_persists_when_the_user_switched_memory_off(self, port):
        outcome = await write_facts(
            ["L'usuari viu a Manresa"], _FakeSession(), port, rag_collections=["user_knowledge"],
        )
        assert outcome.saved == 0
        port.save_to_memory.assert_not_awaited()

    def test_the_gate_itself(self):
        assert memory_saves_enabled(None) is True
        assert memory_saves_enabled(["personal_memory"]) is True
        assert memory_saves_enabled(["user_knowledge"]) is False
        assert memory_saves_enabled([]) is False


class TestFailuresAreNotSilent:

    async def test_an_atomiser_failure_falls_back_to_the_raw_fact(self, port):
        with patch("core.memory_facts.write.atomize_fact_llm", side_effect=RuntimeError("engine down")):
            outcome = await write_facts(["L'usuari viu a Manresa"], _FakeSession(), port, engine=MagicMock())
        assert outcome.saved == 1

    async def test_a_storage_error_does_not_count_as_saved(self, port):
        port.save_to_memory = AsyncMock(return_value={"success": False, "message": "disk full"})
        outcome = await write_facts(["L'usuari viu a Manresa"], _FakeSession(), port)
        assert outcome.saved == 0
        # #1098: the one thing a door must never call "saved" is a fact that is not there.
        assert outcome.kept == []

    async def test_a_duplicate_does_not_count_as_saved(self, port):
        port.save_to_memory = AsyncMock(return_value={"success": False, "duplicate": True})
        outcome = await write_facts(["L'usuari viu a Manresa"], _FakeSession(), port)
        assert outcome.saved == 0
        # ...but it IS in memory: remembered, so the badge may list it (#1098).
        assert outcome.kept == ["L'usuari viu a Manresa"]

    async def test_an_exception_while_saving_does_not_break_the_turn(self, port):
        port.save_to_memory = AsyncMock(side_effect=RuntimeError("db crash"))
        outcome = await write_facts(["L'usuari viu a Manresa"], _FakeSession(), port)
        assert outcome.saved == 0
        assert outcome.kept == []


class TestBothDoorsRunIt:

    def test_the_step_map_says_both_doors(self):
        from core.turn.steps import TURN_STEPS

        step = next(s for s in TURN_STEPS if s.id == "memory.write")
        assert step.doors_today == frozenset({"ui", "api"})

    async def test_v1_persists_a_fact_the_model_marked(self):
        """The point of C3.3 at the API door: a [MEM_SAVE:] tag through /v1
        used to be read (C3.2) and then dropped on the floor."""
        from fastapi import BackgroundTasks

        from core.turn.adapters_api import api_adapters
        from core.turn.context import TurnContext

        session = _FakeSession()
        state = MagicMock()
        state.session_manager.get_or_create_session.return_value = session
        state.memory_helper.save_to_memory = AsyncMock(return_value={"document_id": "d", "success": True})

        ctx = TurnContext(turn_id="t", entry="api")
        ctx.app_state = state
        ctx.session_id = session.id
        ctx.facts = ["L'usuari viu a Manresa"]

        await api_adapters(BackgroundTasks())["memory.write"](ctx)

        state.memory_helper.save_to_memory.assert_awaited_once()
        # 25/09 (#1098): inline, so the turn itself carries the note for `emit`.
        assert ctx.usage["memory_saved"] == 1
        assert ctx.usage["memory_kept"] == ["L'usuari viu a Manresa"]


class TestTheIntentStepOwnsTheFact:
    """C3 review (08/09), live-tested with a 4B and a 27B model: after D6 saves
    "recorda que X" deterministically at the `intent` step, the model answers
    AND marks its own paraphrase of X as a [MEM_SAVE:] tag. Past the opening
    turn the first-turn guard is not there to catch it and the 0.80 dedup does
    not see a paraphrase, so it landed as a second entry for the same fact
    ("el meu peix es diu Bombolla" + "L'usuari té un peix que es diu Bombolla",
    both in `personal_memory`).

    The session carries the user's real message: without it the name guard
    (B126 v2) drops the paraphrase for an unrelated reason and the tests below
    would pass without exercising anything."""

    PARAPHRASE = "L'usuari té un peix que es diu Bombolla"

    @staticmethod
    def _session_that_asked(turns=2):
        session = _FakeSession(turns=turns)
        session.messages[-2] = {
            "role": "user", "content": "Recorda que el meu peix es diu Bombolla",
        }
        return session

    @pytest.mark.parametrize("turns", [1, 2], ids=["opening-turn", "conversation"])
    async def test_a_model_paraphrase_is_dropped_on_a_d6_turn(self, port, caplog, turns):
        """Mutation guard: delete the `saved_by_intent` block in `write_facts`
        and the `turns=2` case goes RED — the paraphrase is saved."""
        with caplog.at_level("INFO", logger="core.memory_facts.write"):
            outcome = await write_facts(
                [self.PARAPHRASE],
                self._session_that_asked(turns), port, saved_by_intent=True,
            )

        assert outcome.saved == 0
        assert outcome.facts == []
        port.save_to_memory.assert_not_awaited()
        messages = [r.getMessage() for r in caplog.records]
        assert any("intent step already saved" in m for m in messages), messages
        # The reason must be the real one, not the opening-turn coincidence.
        assert not any("first turn" in m for m in messages), messages

    async def test_without_the_signal_the_same_fact_is_saved(self, port):
        """The control: nothing about the fact itself makes it droppable — only
        the fact that D6 already handled this turn. This is the entry the live
        test found duplicated on 08/09."""
        outcome = await write_facts(
            [self.PARAPHRASE], self._session_that_asked(), port,
        )
        assert outcome.saved == 1
        port.save_to_memory.assert_awaited_once()

    async def test_v1_stores_the_literal_once_not_the_paraphrase(self):
        """The whole turn at the API door: `intent` saves the literal, the model
        marks its paraphrase, `memory.write` writes nothing more.

        Mutation guard: drop `saved_by_intent=` from the `write_facts` call in
        `core/turn/adapters_api.py` and this goes RED — two awaits, two entries.
        """
        from fastapi import BackgroundTasks

        from core.turn.adapters_api import api_adapters
        from core.turn.context import TurnContext

        # The user's own message is in the history, so the name guard is not
        # what drops the paraphrase — otherwise this would pass either way.
        session = self._session_that_asked()
        state = MagicMock()
        state.session_manager.get_or_create_session.return_value = session
        state.memory_helper.detect_intent = MagicMock(
            return_value=("save", "el meu peix es diu Bombolla")
        )
        state.memory_helper.save_to_memory = AsyncMock(
            return_value={"document_id": "d", "success": True}
        )

        ctx = TurnContext(turn_id="t", entry="api")
        ctx.app_state = state
        ctx.session_id = session.id
        ctx.message = "Recorda que el meu peix es diu Bombolla"
        # NOT a MagicMock: `"personal_memory" in MagicMock()` is False, which
        # would switch memory off and pass this test for the wrong reason.
        ctx.body = None
        table = api_adapters(BackgroundTasks())

        await table["intent"](ctx)
        assert ctx.usage["saved_by_intent"] is True
        assert state.memory_helper.save_to_memory.await_count == 1
        assert state.memory_helper.save_to_memory.await_args.kwargs["content"] == (
            "el meu peix es diu Bombolla"
        )

        ctx.wire = {
            "choices": [{"message": {"role": "assistant", "content":
                        "D'acord. [MEM_SAVE: L'usuari té un peix que es diu Bombolla]"}}],
        }
        await table["postprocess"](ctx)
        assert ctx.facts == ["L'usuari té un peix que es diu Bombolla"]
        assert "MEM_SAVE" not in ctx.wire["choices"][0]["message"]["content"]

        await table["memory.write"](ctx)

        assert state.memory_helper.save_to_memory.await_count == 1, (
            "the paraphrase was written as a second entry"
        )
        assert ctx.facts == []
        assert "memory.write" not in ctx.usage.get("post_commit_result", {})


class TestTheNewsReachesTheNextTurn:
    """C3.3 wires the decision of 06/09: a background save is announced on the
    turn AFTER it, because the turn that queued it had already closed its wire.
    Before this, `take_last_results` existed and nobody ever called it."""

    def _queue_with_a_finished_save(self):
        from core.turn.post_commit import PostCommitQueue

        queue = PostCommitQueue(MagicMock())
        queue._results["s-1"] = {
            "memory.write": {"outcome": "ok", "saved": 2},
            "compact": {"outcome": "ok", "compacted": 1},
        }
        return queue

    async def test_the_ui_stream_opens_with_the_news(self):
        from core.turn.context import TurnContext
        from plugins.web_ui_module.api.turn_adapters import ui_adapters

        queue = self._queue_with_a_finished_save()
        state = MagicMock()
        state.post_commit_queue = queue
        ctx = TurnContext(turn_id="t", entry="ui")
        ctx.app_state = state
        ctx.session_id = "s-1"
        ctx.response = "una resposta"
        ctx.usage["last_results"] = queue.take_last_results("s-1")
        stream_ctx = MagicMock()
        stream_ctx.session.needs_compaction.return_value = False
        ctx.usage.setdefault("ui", {})["stream_ctx"] = stream_ctx

        chunks = [c async for c in ui_adapters(MagicMock(), streaming=True)["emit"](ctx)]

        # 25/09 (#1098): memory is written inline and told on its own turn; a
        # memory result from the queue is not news for this wire any more.
        assert not any(c.startswith("\x00[MEM:") for c in chunks)
        assert "\x00[COMPACT:1]\x00" in chunks

    async def test_the_news_is_never_told_twice(self):
        queue = self._queue_with_a_finished_save()
        assert queue.take_last_results("s-1") != {}
        assert queue.take_last_results("s-1") == {}, "the same news was served twice"

    async def test_v1_carries_it_in_the_reply(self):
        from fastapi import BackgroundTasks

        from core.turn.adapters_api import api_adapters
        from core.turn.context import TurnContext

        queue = self._queue_with_a_finished_save()
        ctx = TurnContext(turn_id="t", entry="api")
        ctx.app_state = MagicMock()
        ctx.session_id = "s-1"
        ctx.wire = {"choices": [{"message": {"content": "hola"}}]}
        ctx.usage["last_results"] = queue.take_last_results("s-1")

        await api_adapters(BackgroundTasks())["emit"](ctx)

        assert ctx.wire["nexe_memory_saved_last_turn"] == 2
        assert ctx.wire["nexe_compacted_last_turn"] == 1


class TestTheWiringItself:
    """The tests above prove `emit` can TELL the news. This one proves somebody
    actually COLLECTS it — the first version of them injected `last_results` by
    hand and stayed green with the collection removed."""

    def _queue_with_results(self):
        from core.turn.post_commit import PostCommitQueue

        queue = PostCommitQueue(MagicMock())
        queue._results["s-1"] = {"memory.write": {"outcome": "ok", "saved": 2}}
        return queue

    async def test_the_ui_session_step_collects_it(self):
        from core.turn.context import TurnContext
        from plugins.web_ui_module.api.turn_adapters import ui_adapters

        queue = self._queue_with_results()
        state = MagicMock()
        state.post_commit_queue = queue
        session_mgr = MagicMock()
        session_mgr.get_or_create_session.return_value = MagicMock(id="s-1")
        ctx = TurnContext(turn_id="t", entry="ui")
        ctx.app_state = state
        ctx.body = {"session_id": "s-1"}
        ctx.message = "hola"

        await ui_adapters(session_mgr, streaming=True)["session"](ctx)

        assert (ctx.usage.get("last_results") or {}).get("memory.write", {}).get("saved") == 2, (
            "the UI door never collected what the previous turn's queue finished"
        )

    async def test_the_api_session_step_collects_it(self):
        from fastapi import BackgroundTasks

        from core.turn.adapters_api import api_adapters
        from core.turn.context import TurnContext

        queue = self._queue_with_results()
        state = MagicMock()
        state.post_commit_queue = queue
        ctx = TurnContext(turn_id="t", entry="api")
        ctx.app_state = state
        ctx.request = MagicMock()
        ctx.body = MagicMock()
        ctx.body.messages = []

        with patch("core.turn.adapters_api.derive_session_id", return_value="s-1"):
            await api_adapters(BackgroundTasks())["session"](ctx)

        assert (ctx.usage.get("last_results") or {}).get("memory.write", {}).get("saved") == 2


class TestTheSpinnerNeverHangs:
    """`[SAVING]` is cleared by `[MEM:n]` and by nothing else (nexe-chat.js:749-767).
    A door that shows it for a turn that stores nothing leaves it spinning forever
    — which is what C3.3 introduced for two cases until `will_write` existed."""

    def test_nothing_to_save_means_no_spinner(self):
        from core.memory_facts.write import will_write

        assert will_write([], _FakeSession()) is False

    def test_memory_switched_off_means_no_spinner(self):
        from core.memory_facts.write import will_write

        assert will_write(["un fet"], _FakeSession(), ["user_knowledge"]) is False

    def test_an_opening_turn_is_a_per_fact_question(self):
        """25/09: an opening turn keeps the facts grounded in the user's words,
        so it is no longer a deterministic "no" — the per-fact filters decide."""
        from core.memory_facts.write import will_write

        assert will_write(["un fet"], _FakeSession(turns=1)) is True

    def test_a_normal_turn_does_show_it(self):
        from core.memory_facts.write import will_write

        assert will_write(["un fet"], _FakeSession(turns=2)) is True

    def test_a_d6_turn_means_no_spinner(self):
        """C3 review (08/09): the writer drops the model's paraphrase on a turn
        the intent step already saved, so the spinner must not promise one."""
        from core.memory_facts.write import will_write

        assert will_write(["un fet"], _FakeSession(turns=2), saved_by_intent=True) is False
        assert will_write(["un fet"], _FakeSession(turns=2)) is True

    async def test_it_agrees_with_what_write_facts_actually_does(self, port):
        """The guard and the writer must not be able to disagree: the same
        deterministic conditions, asked twice, so a spinner is never shown for a
        write the writer will refuse — and, since C3 review (08/09), so a guard
        that says yes is not silently refused either. That second direction is
        what let `will_write` miss `saved_by_intent` while staying green.

        Mutation guard: delete the `saved_by_intent` check in `will_write` (only
        there — leave `write_facts`) and this goes RED on the last case.
        """
        from core.memory_facts.write import will_write

        cases = [
            (["L'usuari viu a Manresa"], _FakeSession(turns=1, user_text="visc a Manresa"), None, False),
            (["un fet"], _FakeSession(turns=2), ["user_knowledge"], False),
            (["L'usuari viu a Manresa"], _FakeSession(turns=2), None, False),
            (["L'usuari viu a Manresa"], _FakeSession(turns=2), None, True),
        ]
        for facts, session, collections, saved_by_intent in cases:
            predicted = will_write(facts, session, collections, saved_by_intent=saved_by_intent)
            outcome = await write_facts(
                facts, session, port,
                rag_collections=collections, saved_by_intent=saved_by_intent,
            )
            if not predicted:
                assert outcome.saved == 0, f"the guard said no and the writer saved: {facts}"
            else:
                assert outcome.saved == 1, f"the guard said yes and the writer refused: {facts}"


class TestTheAtomiserTalksToBothEngineShapes:
    """B088: Ollama's chat() is sync and returns an async generator; MLX's is
    `async def` and returns a coroutine that resolves to a dict. The atomiser
    handles both, and the tests that covered that died with the file this one
    replaces — every test above patches `atomize_fact_llm` wholesale, so a
    regression of B088 would have gone through silently.
    """

    def _sig(self, with_model: bool):
        import inspect

        if with_model:
            def _ollama(model, messages, stream, thinking_enabled):
                ...
            return inspect.signature(_ollama)

        def _mlx(messages, stream, thinking_enabled):
            ...
        return inspect.signature(_mlx)

    async def test_ollama_shape_async_generator(self):
        from core.memory_facts.write import atomize_fact_llm

        async def _chunks():
            yield {"message": {"content": "L'usuari es diu Aran\n"}}
            yield {"message": {"content": "L'usuari té 8 anys"}}

        engine = MagicMock()
        engine.chat = MagicMock(return_value=_chunks())

        out = await atomize_fact_llm(
            "L'usuari es diu Aran i té 8 anys", engine, "m", self._sig(True), lang="ca",
        )

        assert out == ["L'usuari es diu Aran", "L'usuari té 8 anys"]
        assert engine.chat.call_args.kwargs["model"] == "m", "the Ollama shape takes `model`"

    async def test_mlx_shape_coroutine_resolving_to_a_dict(self):
        from core.memory_facts.write import atomize_fact_llm

        async def _chat(**_kwargs):
            return {"response": "L'usuari es diu Aran\nL'usuari té 8 anys"}

        engine = MagicMock()
        engine.chat = _chat

        out = await atomize_fact_llm(
            "L'usuari es diu Aran i té 8 anys", engine, "m", self._sig(False), lang="ca",
        )

        assert out == ["L'usuari es diu Aran", "L'usuari té 8 anys"]

    async def test_one_fact_really_becomes_several(self):
        """The multiplication itself: a passthrough atomiser would pass the
        earlier tests unchanged even if `write_facts` ignored its return."""
        from core.memory_facts.write import atomize_fact_llm

        async def _chat(**_kwargs):
            return {"response": "L'usuari viu a Manresa\nL'usuari treballa de fuster"}

        engine = MagicMock()
        engine.chat = _chat
        port = AsyncMock()
        port.save_to_memory = AsyncMock(return_value={"document_id": "d", "success": True})

        with patch("core.memory_facts.write.atomize_fact_llm", new=atomize_fact_llm):
            outcome = await write_facts(
                ["L'usuari viu a Manresa i treballa de fuster"],
                _FakeSession(), port, engine=engine, model_name="m",
                sig=self._sig(False), lang="ca",
            )

        assert outcome.saved == 2, "one combined fact must reach memory as two"
        assert len(outcome.facts) == 2

    async def test_a_fact_without_a_conjunction_is_left_alone(self):
        from core.memory_facts.write import atomize_fact_llm

        engine = MagicMock()
        out = await atomize_fact_llm("L'usuari viu a Manresa", engine, "m", self._sig(True))
        assert out == ["L'usuari viu a Manresa"]
        engine.chat.assert_not_called(), "no conjunction means no LLM call"

    async def test_a_broken_engine_keeps_the_fact_as_is(self):
        from core.memory_facts.write import atomize_fact_llm

        engine = MagicMock()
        engine.chat = MagicMock(side_effect=RuntimeError("engine down"))
        out = await atomize_fact_llm("A i B que son prou llargs", engine, "m", self._sig(True))
        assert out == ["A i B que son prou llargs"]
