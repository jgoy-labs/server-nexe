"""Memory commands in the core, one brain for every door (ADR-007 C3.1).

These replace tests/test_memory_intent_helpers.py's handler classes: same cases,
now against `intents.resolve`, which answers with data instead of a wire format.

The behaviour that CHANGED here is D6 (Jordi, 07/09/2026): "remember that ..."
saves the fact and lets the conversation continue. Before C3.1 it answered with a
fixed English line and the model never saw the message.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.memory_facts import intents
from core.memory_facts.intent_texts import TEXTS


@pytest.fixture(autouse=True)
def _english_answers(monkeypatch):
    """These assertions read the English table. Without pinning it, a sibling
    test that leaves NEXE_LANG set makes them fail for the wrong reason —
    which is exactly what happened the first time the whole suite ran."""
    monkeypatch.setenv("NEXE_LANG", "en")


def _session(messages=None):
    s = MagicMock()
    s.id = "sess-test-1"
    s.messages = messages if messages is not None else []
    s._pending_partial_delete = None
    s._pending_clear_all = False
    return s


def _port():
    p = MagicMock()
    p.save_to_memory = AsyncMock()
    p.preview_delete_from_memory = AsyncMock()
    p.delete_memory_entries = AsyncMock()
    p.list_memories = AsyncMock()
    p.clear_memory = AsyncMock()
    return p


async def _resolve(kind, content="", *, session=None, port=None, message=""):
    return await intents.resolve(kind, content, session or _session(), port or _port(), message)


# ═══════════════════════════════════════════════════════════════
# save — D6: persists, and the turn goes on
# ═══════════════════════════════════════════════════════════════

class TestSave:

    async def test_saves_the_fact_and_lets_the_turn_continue(self):
        port = _port()
        port.save_to_memory.return_value = {"success": True, "document_id": "doc-1"}

        outcome = await _resolve("save", "el meu gat es diu Mite", port=port, message="Recorda que el meu gat es diu Mite")

        port.save_to_memory.assert_awaited_once()
        assert port.save_to_memory.await_args.kwargs["content"] == "el meu gat es diu Mite"
        assert outcome.continue_turn is True, "D6: a save must not answer instead of the model"
        assert outcome.mem_saved == 1
        assert outcome.text == "", "the note rides as a sentinel/field, not as the turn's answer"

    async def test_duplicate_does_not_count_as_saved_but_still_continues(self):
        port = _port()
        port.save_to_memory.return_value = {"success": False, "duplicate": True}
        outcome = await _resolve("save", "ja ho sap", port=port)
        assert (outcome.mem_saved, outcome.continue_turn) == (0, True)

    async def test_failure_does_not_break_the_turn(self):
        port = _port()
        port.save_to_memory.return_value = {"success": False, "message": "Memory API not available"}
        outcome = await _resolve("save", "algun fet", port=port)
        assert (outcome.mem_saved, outcome.continue_turn) == (0, True)

    async def test_empty_content_saves_nothing(self):
        port = _port()
        outcome = await _resolve("save", "", port=port, message="")
        port.save_to_memory.assert_not_awaited()
        assert outcome.continue_turn is True

    async def test_strips_trailing_punctuation(self):
        port = _port()
        port.save_to_memory.return_value = {"success": True, "document_id": "d"}
        await _resolve("save", "em dic Pere?", port=port)
        assert port.save_to_memory.await_args.kwargs["content"] == "em dic Pere"

    async def test_a_save_owns_the_turns_fact_even_when_dedup_refuses_it(self):
        """`saved_by_intent` is "the port has seen this fact this turn", NOT
        `mem_saved > 0`. A dedup refusal means the fact is ALREADY in memory,
        so the paraphrase the model then marks about it must be dropped too —
        deriving the flag from `mem_saved` would let exactly that one through.

        Mutation guard: drop `saved_by_intent=True` from `_save` (or derive it
        from `mem_saved`) and the second case goes RED.
        """
        port = _port()
        port.save_to_memory.return_value = {"success": True, "document_id": "doc-1"}
        stored = await _resolve("save", "el meu gat es diu Mite", port=port)

        port.save_to_memory.return_value = {"success": False, "duplicate": True}
        refused = await _resolve("save", "el meu gat es diu Mite", port=port)

        assert stored.saved_by_intent is True
        assert refused.saved_by_intent is True, "a refused duplicate still owns the turn's fact"
        assert refused.mem_saved == 0, "…and it is still not counted as a new save"

    async def test_empty_content_does_not_own_a_fact(self):
        """Nothing reached the port, so nothing about this turn is already in
        memory: a tag the model marks here is a normal save, not a repetition.

        Mutation guard: set `saved_by_intent=True` on the empty-content return
        of `_save` (or default the field to True) and this goes RED.
        """
        port = _port()
        outcome = await _resolve("save", "", port=port, message="")
        port.save_to_memory.assert_not_awaited()
        assert outcome.saved_by_intent is False

    async def test_recall_does_not_own_a_fact(self):
        """A recall sets `memory_action` without saving anything — which is why
        the flag is its own field and not read off `memory_action`.

        Mutation guard: make the flag `bool(outcome.memory_action)` anywhere in
        the chain and this goes RED.
        """
        outcome = await _resolve("recall", "què saps de mi", message="què saps de mi")
        assert outcome.memory_action == "recall"
        assert outcome.saved_by_intent is False


# ═══════════════════════════════════════════════════════════════
# delete — still a command: it short-circuits
# ═══════════════════════════════════════════════════════════════

class TestTwoFactsInOneSave:
    """#1056: "recorda que visc a Vic i que treballo de fuster" was ONE card —
    forgetting where you live also forgot your job. Split before a known
    first-person verb only; anything else stays whole, as before."""

    @pytest.mark.parametrize("content, parts", [
        ("visc a Vic i que treballo de fuster", ["visc a Vic", "treballo de fuster"]),
        ("em dic Aran i tinc 8 anys", ["em dic Aran", "tinc 8 anys"]),
        ("vivo en Vic y trabajo de carpintero", ["vivo en Vic", "trabajo de carpintero"]),
        ("I live in Vic and I work as a carpenter", ["I live in Vic", "I work as a carpenter"]),
    ])
    def test_a_second_first_person_predicate_is_a_second_fact(self, content, parts):
        assert intents.split_first_person(content) == parts

    @pytest.mark.parametrize("content", [
        "m'agraden la vainilla i els macarrons",   # a list, one predicate
        "el gat i el gos es diuen Mite i Bru",     # "i" inside the subject
        "el meu peix es diu Bombolla",
    ])
    def test_a_list_or_a_single_fact_stays_whole(self, content):
        assert intents.split_first_person(content) == [content]

    async def test_each_fact_is_its_own_card_and_both_are_told(self):
        port = _port()
        port.save_to_memory.side_effect = [
            {"success": True, "document_id": "d1"},
            {"success": False, "duplicate": True},
        ]
        outcome = await _resolve("save", "visc a Vic i que treballo de fuster", port=port,
                                 message="Recorda que visc a Vic i que treballo de fuster")
        saved = [c.kwargs["content"] for c in port.save_to_memory.await_args_list]
        assert saved == ["visc a Vic", "treballo de fuster"]
        assert outcome.mem_saved == 1, "only the new one counts as stored"
        assert outcome.kept_facts == ["visc a Vic", "treballo de fuster"], "the duplicate is remembered too"
        assert outcome.saved_by_intent is True


class TestDelete:

    async def test_match_arms_confirmation_and_deletes_nothing(self):
        port = _port()
        port.preview_delete_from_memory.return_value = {
            "success": True, "candidates": [{"text": "el gat es diu Mite", "metadata": {"type": "note"}}],
        }
        session = _session([{"role": "user", "content": "Oblida que el gat es diu Mite"}])

        outcome = await _resolve("delete", "el gat es diu Mite", session=session, port=port)

        port.delete_memory_entries.assert_not_awaited()
        assert outcome.kind == "delete_pending"
        assert outcome.continue_turn is False
        assert session._pending_partial_delete["entries"][0]["text"] == "el gat es diu Mite"
        assert outcome.pending_delete_fact == "el gat es diu Mite"

    async def test_profile_candidate_warns(self):
        port = _port()
        port.preview_delete_from_memory.return_value = {
            "success": True, "candidates": [{"text": "em dic Jordi", "metadata": {"type": "fact"}}],
        }
        outcome = await _resolve("delete", "em dic Jordi", port=port)
        assert TEXTS["en"]["delete.profile_warning"].strip() in outcome.text

    async def test_nothing_found(self):
        port = _port()
        port.preview_delete_from_memory.return_value = {"success": True, "candidates": []}
        outcome = await _resolve("delete", "res de res", port=port)
        assert "Nothing found" in outcome.text
        assert outcome.kind == "delete"

    async def test_error_is_reported(self):
        port = _port()
        port.preview_delete_from_memory.return_value = {"success": False, "message": "store down"}
        outcome = await _resolve("delete", "algo", port=port)
        assert "store down" in outcome.text

    async def test_empty_content_asks_what_and_sanitizes_history(self):
        session = _session([{"role": "user", "content": "Oblida-ho"}])
        outcome = await _resolve("delete", "", session=session)
        assert outcome.text == TEXTS["en"]["delete.empty"]
        assert session.messages[-1]["content"].startswith("[Memory command: delete")

    async def test_sanitizes_the_last_user_message(self):
        port = _port()
        port.preview_delete_from_memory.return_value = {"success": True, "candidates": []}
        session = _session([{"role": "user", "content": "Oblida que tinc 8 anys"}])
        await _resolve("delete", "tinc 8 anys", session=session, port=port)
        assert "tinc 8 anys" in session.messages[-1]["content"]
        assert session.messages[-1]["content"].startswith("[Memory command: delete")


class TestDeleteConfirm:

    async def test_deletes_the_exact_pending_entries(self):
        port = _port()
        port.delete_memory_entries.return_value = {
            "success": True, "deleted": 1, "deleted_facts": [{"text": "el gat es diu Mite"}],
        }
        session = _session()
        session._pending_partial_delete = {"content": "gat", "entries": [{"text": "el gat es diu Mite", "metadata": {"type": "note"}}]}

        outcome = await _resolve("delete_confirm", session=session, port=port, message="si")

        port.delete_memory_entries.assert_awaited_once()
        assert outcome.mem_deleted == 1
        assert outcome.deleted_facts == ["el gat es diu Mite"]
        assert session._pending_partial_delete is None

    async def test_without_pending_is_a_noop(self):
        port = _port()
        outcome = await _resolve("delete_confirm", session=_session(), port=port, message="si")
        port.delete_memory_entries.assert_not_awaited()
        assert outcome.text == TEXTS["en"]["delete.nothing_pending"]

    async def test_profile_entry_needs_more_than_a_bare_yes(self):
        """B093: a generic 'yes' must not erase profile data."""
        port = _port()
        session = _session()
        session._pending_partial_delete = {"content": "nom", "entries": [{"text": "em dic Jordi", "metadata": {"type": "fact"}}]}

        outcome = await _resolve("delete_confirm", session=session, port=port, message="si")

        port.delete_memory_entries.assert_not_awaited()
        assert outcome.memory_action == "delete_blocked"

    async def test_profile_entry_with_an_explicit_reference_is_allowed(self):
        port = _port()
        port.delete_memory_entries.return_value = {"success": True, "deleted": 1, "deleted_facts": [{"text": "em dic Jordi"}]}
        session = _session()
        session._pending_partial_delete = {"content": "nom", "entries": [{"text": "em dic Jordi", "metadata": {"type": "fact"}}]}

        outcome = await _resolve("delete_confirm", session=session, port=port, message="si, esborra que em dic Jordi")

        port.delete_memory_entries.assert_awaited_once()
        assert outcome.mem_deleted == 1

    async def test_non_profile_entry_accepts_a_bare_yes(self):
        port = _port()
        port.delete_memory_entries.return_value = {"success": True, "deleted": 1, "deleted_facts": [{"text": "nota qualsevol"}]}
        session = _session()
        session._pending_partial_delete = {"content": "nota", "entries": [{"text": "nota qualsevol", "metadata": {"type": "note"}}]}
        outcome = await _resolve("delete_confirm", session=session, port=port, message="si")
        assert outcome.mem_deleted == 1

    async def test_stopwords_alone_are_not_a_reference(self):
        assert intents.references_entry("yes delete memory please", [{"text": "em dic Jordi"}]) is False
        assert intents.references_entry("esborra que em dic Jordi", [{"text": "em dic Jordi"}]) is True


class TestList:

    async def test_lists_the_facts(self):
        port = _port()
        port.list_memories.return_value = {
            "success": True, "total": 2,
            "facts": [{"text": "el gat es diu Mite"}, {"text": "visc a Barcelona"}],
        }
        outcome = await _resolve("list", port=port)
        assert "el gat es diu Mite" in outcome.text and "visc a Barcelona" in outcome.text
        assert "2 of 2" in outcome.text or "2 de 2" in outcome.text

    async def test_dates_are_shown_when_present(self):
        port = _port()
        port.list_memories.return_value = {
            "success": True, "total": 1, "facts": [{"text": "un fet", "created_at": "2026-09-08T02:00:00Z"}],
        }
        outcome = await _resolve("list", port=port)
        assert "(2026-09-08)" in outcome.text

    @pytest.mark.parametrize("result", [
        {"success": True, "total": 0, "facts": []},
        {"success": False, "facts": []},
    ])
    async def test_nothing_stored(self, result):
        port = _port()
        port.list_memories.return_value = result
        outcome = await _resolve("list", port=port)
        assert outcome.text == TEXTS["en"]["list.empty"]


class TestClearAll:

    async def test_clear_all_arms_the_confirmation_without_wiping(self):
        port = _port()
        session = _session()
        outcome = await _resolve("clear_all", session=session, port=port)
        port.clear_memory.assert_not_awaited()
        assert session._pending_clear_all is True
        assert outcome.memory_action == "clear_all_pending"

    async def test_confirm_wipes_and_clears_the_flag(self):
        port = _port()
        port.clear_memory.return_value = {"success": True}
        session = _session()
        session._pending_clear_all = True
        outcome = await _resolve("clear_all_confirm", session=session, port=port)
        port.clear_memory.assert_awaited_once_with(confirm=True)
        assert session._pending_clear_all is False
        assert outcome.mem_deleted == 1

    async def test_failure_is_reported(self):
        port = _port()
        port.clear_memory.return_value = {"success": False, "message": "nope"}
        outcome = await _resolve("clear_all_confirm", port=port)
        assert "nope" in outcome.text

    async def test_exception_is_reported(self):
        port = _port()
        port.clear_memory.side_effect = RuntimeError("store exploded")
        outcome = await _resolve("clear_all_confirm", port=port)
        assert "store exploded" in outcome.text


class TestPendingHijack:
    """Bug #18 P0 / B028: a pending confirmation owns the next message."""

    def test_pending_clear_all_turns_a_yes_into_a_confirmation(self):
        port = _port()
        port.detect_intent.return_value = ("chat", None)
        port.matches_clear_all_confirm.return_value = True
        session = _session()
        session._pending_clear_all = True
        detected, _ = intents.detect_with_pending(session, "si, esborra-ho tot", port)
        assert detected == "clear_all_confirm"

    def test_anything_else_clears_the_pending_flag(self):
        port = _port()
        port.detect_intent.return_value = ("chat", None)
        port.matches_clear_all_confirm.return_value = False
        session = _session()
        session._pending_clear_all = True
        detected, _ = intents.detect_with_pending(session, "millor no", port)
        assert detected == "chat" and session._pending_clear_all is False


class TestLanguageAndFlag:

    def test_commands_answer_in_the_server_language(self, monkeypatch):
        """The texts used to be English hardcoded (save/list) and Catalan
        hardcoded (clear_all). Now one table answers in the server's language."""
        monkeypatch.setenv("NEXE_LANG", "ca")
        assert intents._t("list.empty") == TEXTS["ca"]["list.empty"]
        monkeypatch.setenv("NEXE_LANG", "es")
        assert intents._t("list.empty") == TEXTS["es"]["list.empty"]

    def test_every_language_defines_every_key(self):
        keys = set(TEXTS["en"])
        for lang, table in TEXTS.items():
            assert set(table) == keys, f"{lang} does not define the same keys as en"

    def test_the_flag_turns_the_whole_thing_off(self, monkeypatch):
        monkeypatch.setenv("NEXE_MEMORY_INTENT", "false")
        assert intents.intent_enabled() is False
        monkeypatch.setenv("NEXE_MEMORY_INTENT", "true")
        assert intents.intent_enabled() is True

    def test_default_is_on(self, monkeypatch):
        monkeypatch.delenv("NEXE_MEMORY_INTENT", raising=False)
        assert intents.intent_enabled() is True


class TestCoreCarriesNoWireFormat:

    async def test_no_answer_the_core_produces_carries_a_sentinel(self):
        """The UI's alphabet belongs to the UI. Behaviour, not grep: every
        command's text is checked, so a sentinel sneaking back in fails here."""
        port = _port()
        port.preview_delete_from_memory.return_value = {"success": True, "candidates": [{"text": "un fet"}]}
        port.delete_memory_entries.return_value = {"success": True, "deleted": 1, "deleted_facts": [{"text": "un fet"}]}
        port.list_memories.return_value = {"success": True, "total": 1, "facts": [{"text": "un fet"}]}
        port.clear_memory.return_value = {"success": True}
        port.save_to_memory.return_value = {"success": True, "document_id": "d"}

        for kind in ("save", "delete", "list", "clear_all", "clear_all_confirm", "delete_confirm", "recall"):
            session = _session([{"role": "user", "content": "text"}])
            session._pending_partial_delete = {"content": "x", "entries": [{"text": "un fet", "metadata": {}}]}
            outcome = await intents.resolve(kind, "un fet", session, port, "un fet")
            assert "\x00" not in outcome.text, f"{kind} answered with a UI sentinel"
            assert "MODEL:nexe-system" not in outcome.text

    def test_no_english_answer_is_hardcoded_outside_the_table(self):
        import pathlib

        import core.memory_facts as pkg

        src = (pathlib.Path(pkg.__file__).parent / "intents.py").read_text()
        assert "Saved to memory" not in src
        assert "I'll remember this" not in src


class TestBothDoorsRunIt:
    """D7: the same step, at both doors — not an `if entry == "ui"`."""

    def test_the_api_table_has_a_real_intent_step(self):
        from core.turn.adapters_api import api_adapters

        table = api_adapters(MagicMock())
        assert "folded" not in table["intent"].__name__, "the /v1 intent step is still a placeholder"

    def test_the_ui_table_has_a_real_intent_step(self):
        from plugins.web_ui_module.api.turn_adapters import ui_adapters

        table = ui_adapters(MagicMock(), streaming=True)
        assert "folded" not in table["intent"].__name__

    def test_the_step_map_says_both_doors(self):
        from core.turn.steps import TURN_STEPS

        step = next(s for s in TURN_STEPS if s.id == "intent")
        assert step.doors_today == frozenset({"ui", "api"})
