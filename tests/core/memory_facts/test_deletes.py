"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/memory_facts/test_deletes.py
Description: The model's [MEM_DELETE:] tags arm ONE confirmation rule for
             every door (ADR-007 C4.5, B028). The four tests that guarded the
             web door's JSON copy (`_arm_mem_deletes_nonstreaming`, in
             tests/test_memory_intent_helpers.py until 26/09), plus the rule
             the three variants disagreed on, plus the dialog's confirmation.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import AsyncMock, MagicMock

from core.memory_facts import deletes, intents


#: These tests are about what arms and how; #1135 (whether the user asked)
#: has its own file, test_1135_mention_vs_use.py.
_ASKED = "oblida-ho"


def _session(pending=None):
    s = MagicMock()
    s.id = "sess-1"
    s.messages = []
    s._pending_partial_delete = pending
    return s


def _port(candidates=None, success=True):
    p = MagicMock()
    p.preview_delete_from_memory = AsyncMock(return_value={"success": success, "candidates": candidates or []})
    p.delete_from_memory = AsyncMock()
    p.delete_memory_entries = AsyncMock(return_value={
        "success": True, "deleted": 1,
        "deleted_facts": [{"text": "fact one", "id": "id-1", "score": 0.9}],
    })
    return p


def _candidate(text="fact one", cid="id-1", collection="personal_memory", score=0.9, mtype=None):
    return {"id": cid, "collection": collection, "text": text, "score": score,
            "metadata": {"type": mtype} if mtype else {}}


class TestArmPendingDeletes:

    async def test_arms_the_pending_and_answers_with_data_without_deleting(self):
        port = _port([_candidate()])
        session = _session()
        outcome = await deletes.arm_pending_deletes(session, ["fact one", "fact two"], port, user_message=_ASKED)
        port.delete_from_memory.assert_not_called()
        port.delete_memory_entries.assert_not_called()
        assert session._pending_partial_delete == {"content": "fact one", "entries": [_candidate()]}
        assert outcome is not None and outcome.kind == "delete_pending"
        assert outcome.memory_action == "delete_pending"
        assert outcome.text and "fact one" in outcome.text
        # The core is wire-agnostic: the sentinel is the web door's alphabet.
        assert "\x00" not in outcome.text and "PENDING_DELETE" not in outcome.text

    async def test_the_thing_to_confirm_is_the_entrys_text_not_the_models_phrase(self):
        """The dialog shows it and sends it back as the confirmed reference (B093)."""
        port = _port([_candidate(text="El gos de l'usuari es diu Tro")])
        outcome = await deletes.arm_pending_deletes(_session(), ["el gos"], port, user_message=_ASKED)
        assert outcome.pending_delete_fact == "El gos de l'usuari es diu Tro"

    async def test_no_match_arms_nothing_and_answers_nothing(self):
        port = _port([])
        session = _session()
        assert await deletes.arm_pending_deletes(session, ["unknown topic"], port, user_message=_ASKED) is None
        assert not session._pending_partial_delete

    async def test_a_failed_preview_arms_nothing(self):
        """TUR-PHANTOM-DEL: no dead confirm button, no armed flag."""
        port = _port([_candidate()], success=False)
        session = _session()
        assert await deletes.arm_pending_deletes(session, ["fact one"], port, user_message=_ASKED) is None
        assert not session._pending_partial_delete

    async def test_skips_short_facts(self):
        port = _port([_candidate()])
        assert await deletes.arm_pending_deletes(_session(), ["ab", "x", ""], port, user_message=_ASKED) is None
        port.preview_delete_from_memory.assert_not_called()

    async def test_a_raising_preview_is_survived(self):
        port = _port()
        port.preview_delete_from_memory = AsyncMock(side_effect=RuntimeError("crash"))
        assert await deletes.arm_pending_deletes(_session(), ["some fact"], port, user_message=_ASKED) is None

    async def test_nothing_to_arm_asks_nothing(self):
        port = _port([_candidate()])
        assert await deletes.arm_pending_deletes(_session(), [], port, user_message=_ASKED) is None
        port.preview_delete_from_memory.assert_not_called()

    async def test_a_pending_confirmation_is_not_overwritten(self):
        """The rule the JSON copy broke: the typed "sí" of the next turn must
        answer the question the user actually saw."""
        pending = {"content": "first", "entries": [_candidate(text="first", cid="id-0")]}
        session = _session(pending=dict(pending))
        port = _port([_candidate()])
        assert await deletes.arm_pending_deletes(session, ["fact one"], port, user_message=_ASKED) is None
        port.preview_delete_from_memory.assert_not_called()
        assert session._pending_partial_delete == pending

    async def test_the_turns_collections_narrow_the_search(self):
        """The rule the streaming copy broke: a tag never reaches a collection
        the user switched off — same as a typed "oblida" (`intents._delete`)."""
        port = _port([_candidate()])
        await deletes.arm_pending_deletes(_session(), ["fact one"], port, ["personal_memory"], user_message=_ASKED)
        port.preview_delete_from_memory.assert_awaited_once_with("fact one", collections=["personal_memory"])

    async def test_the_first_tag_that_matches_wins(self):
        port = _port()
        port.preview_delete_from_memory = AsyncMock(side_effect=[
            {"success": True, "candidates": []},
            {"success": True, "candidates": [_candidate(text="fact two", cid="id-2")]},
        ])
        session = _session()
        outcome = await deletes.arm_pending_deletes(session, ["nothing here", "fact two"], port, user_message=_ASKED)
        assert session._pending_partial_delete["content"] == "fact two"
        assert outcome.pending_delete_fact == "fact two"

    async def test_best_match_only(self):
        """B028/RT-04: what the user confirms is exactly what dies."""
        port = _port([_candidate(cid="id-1"), _candidate(text="fact one bis", cid="id-2")])
        session = _session()
        await deletes.arm_pending_deletes(session, ["fact one"], port, user_message=_ASKED)
        assert session._pending_partial_delete["entries"] == [_candidate(cid="id-1")]


class TestConfirmPendingDelete:

    async def test_deletes_the_pending_entry_by_id_and_clears_it(self):
        session = _session(pending={"content": "fact", "entries": [_candidate()]})
        port = _port()
        outcome = await deletes.confirm_pending_delete(session, port, "fact one")
        port.delete_memory_entries.assert_awaited_once_with([_candidate()])
        port.delete_from_memory.assert_not_called()
        assert outcome.mem_deleted == 1 and outcome.deleted_facts == ["fact one"]
        assert session._pending_partial_delete is None

    async def test_nothing_pending_deletes_nothing(self):
        port = _port()
        outcome = await deletes.confirm_pending_delete(_session(), port, "fact one")
        port.delete_memory_entries.assert_not_called()
        assert outcome.mem_deleted == 0 and outcome.memory_action == "delete"

    async def test_a_profile_entry_needs_the_reference_b093(self):
        profile_type = next(iter(intents.PROFILE_LIKE_TYPES))
        entry = _candidate(text="the user is called Aran", mtype=profile_type)
        port = _port()

        blocked = await deletes.confirm_pending_delete(
            _session(pending={"content": "x", "entries": [entry]}), port, "",
        )
        assert blocked.memory_action == "delete_blocked" and blocked.mem_deleted == 0
        port.delete_memory_entries.assert_not_called()

        # The dialog sends the entry's own text: that names it.
        session = _session(pending={"content": "x", "entries": [entry]})
        confirmed = await deletes.confirm_pending_delete(session, port, "the user is called Aran")
        port.delete_memory_entries.assert_awaited_once_with([entry])
        assert confirmed.mem_deleted == 1

    async def test_the_shown_entry_names_itself_even_with_short_words(self):
        """Live 26/09: "el meu gos es diu Tro." is profile-like and has no word
        `references_entry` counts (all under 4 letters) — the dialog's click on
        that very entry was refused. The entry's own text, sent back, is the
        explicit reference B093 asks for; case and a trailing period do not
        matter. A bare "sí" or another text still does not name it."""
        profile_type = next(iter(intents.PROFILE_LIKE_TYPES))
        entry = _candidate(text="el meu gos es diu Tro.", mtype=profile_type)
        port = _port()
        port.delete_memory_entries = AsyncMock(return_value={
            "success": True, "deleted": 1, "deleted_facts": [{"text": entry["text"], "id": "id-1", "score": 0.9}],
        })

        for bare in ("", "sí", "el gat es diu Mite"):
            refused = await deletes.confirm_pending_delete(
                _session(pending={"content": "el gos", "entries": [entry]}), port, bare,
            )
            assert refused.memory_action == "delete_blocked", bare
        port.delete_memory_entries.assert_not_called()

        for shown in ("el meu gos es diu Tro.", "El meu gos es diu Tro", "  el meu gos es diu tro  "):
            port.delete_memory_entries.reset_mock()
            session = _session(pending={"content": "el gos", "entries": [entry]})
            confirmed = await deletes.confirm_pending_delete(session, port, shown)
            port.delete_memory_entries.assert_awaited_once_with([entry])
            assert confirmed.mem_deleted == 1 and session._pending_partial_delete is None, shown
