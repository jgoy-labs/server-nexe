"""#1135, second case — a model that MENTIONS a memory tag is not using it.

Live 03/10 17:18 (MLX, Qwen3.5-9B): asked «com funciona la teva memòria?», the
model explained its instructions with an example made from the user's real
name — `[MEM_DELETE: L'usuari es diu Jordi]` (log sha 787d5693) — and the
dialog offered to delete it. The tag's content is a real fact, so no rule on
the content (test_1135_example_tags.py) can tell it from a request. Two
signals can, decided by Jordi («les dues»):

* a tag inside code (`…` or a fenced block) is a quotation: not run, and the
  span goes with it (the web showed «El format és: ``.»);
* a model's delete tag arms only when the USER asked to forget — this turn, or
  a bare "sí" right after a message that did.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.memory_facts import deletes
from core.memory_facts.extract import extract_memory_tags
from core.sessions import ChatSession

LIVE_REPLY = (
    "3. **Escric el tag:** El format és: `[MEM_SAVE: L'usuari es diu Jordi]`.\n"
    "4. **Gestiono l'oblit:** si dius «oblida que em dic Jordi», et pregunto i després escric "
    "`[MEM_DELETE: L'usuari es diu Jordi]`.\n"
    "```\n[MEM_SAVE: L'usuari té 30 anys]\n```\n"
    "Vols que guardi alguna cosa concreta ara mateix?"
)


# ── 1. Inside code: a quotation ─────────────────────────────────────────────

def test_the_live_reply_runs_no_tag_and_leaves_no_empty_backticks():
    clean, facts, dels = extract_memory_tags(LIVE_REPLY, user_input="com funciona la teva memòria?")
    assert facts == [] and dels == []
    assert "``" not in clean and "MEM_" not in clean
    assert "Vols que guardi alguna cosa concreta" in clean


def test_a_real_tag_outside_code_in_the_same_reply_still_runs():
    clean, facts, dels = extract_memory_tags(LIVE_REPLY + " Ho recordaré. [MEM_SAVE: L'usuari viu a Girona]")
    assert facts == ["L'usuari viu a Girona"]


@pytest.mark.parametrize("quoted", [
    "`[MEM_DELETE: el gos es diu Tro]`",
    "```\n[MEM_DELETE: el gos es diu Tro]\n```",
    "`[OBLIT: el gos es diu Tro]`",
    "`[MEMORIA: L'usuari té un gos]`",
])
def test_every_tag_form_in_code_is_a_quotation(quoted):
    clean, facts, dels = extract_memory_tags(f"Així: {quoted}.")
    assert facts == [] and dels == []
    assert "`" not in clean


@pytest.mark.parametrize("text", [
    "El format és:\n~~~\n[MEM_SAVE: L'usuari es diu Jordi]\n~~~\nI ja està.",
    "El format és:\n```\n[MEM_SAVE: L'usuari es diu Jordi]",                 # never closed
    "El format és: ``[MEM_SAVE: L'usuari es diu Jordi]``.",
    "El format és:\n```text\n[MEM_SAVE: L'usuari es diu Jordi]\n```\nI ja està.",
])
def test_other_code_forms_are_quotations_too_and_leave_nothing_behind(text):
    """Review 04/10: `~~~`, an unclosed fence, ``double`` backticks; and a
    ```text block left an empty block behind."""
    clean, saves, _ = extract_memory_tags(text)
    assert saves == []
    assert "`" not in clean and "~~~" not in clean, clean


def test_code_without_a_tag_is_left_alone():
    text = "Fes servir `pip install` i després:\n```\nnexe go\n```"
    clean, _, _ = extract_memory_tags(text)
    assert clean == text


# ── 2. Arms only when the user asked ────────────────────────────────────────

ENTRY = {"id": "id-1", "collection": "personal_memory", "text": "L'usuari es diu Jordi", "score": 0.9}


def _port():
    port = MagicMock()
    port.preview_delete_from_memory = AsyncMock(return_value={"success": True, "candidates": [ENTRY]})
    return port


def _session(*user_messages) -> ChatSession:
    session = ChatSession(session_id="s1")
    for text in user_messages:
        session.messages.append({"role": "user", "content": text})
    return session


async def test_the_live_question_arms_nothing():
    port = _port()
    session = _session("com funciona la teva memòria?")
    armed = await deletes.arm_pending_deletes(
        session, ["L'usuari es diu Jordi"], port, user_message="com funciona la teva memòria?")
    assert armed is None
    port.preview_delete_from_memory.assert_not_called()
    assert not getattr(session, "_pending_partial_delete", None)


@pytest.mark.parametrize("message", [
    "oblida que em dic Jordi", "esborra el meu nom", "treu-ho de la memòria",
    "el Bombolla ja no hi és", "olvida mi nombre", "ya no tengo perro",
    "please forget my name", "I don't have a dog anymore", "remove that", "no longer at Helefante",
    # Review 04/10: an accent inside the stem, and stems that were missing.
    "Bórralo de tu memoria, por favor", "Olvídate de que me llamo Pere", "Elimínalo de la memoria",
    "suprimeix això de la memòria", "suprime eso", "no ho recordis més", "no lo recuerdes",
    "wipe that", "scratch that from your memory",
])
async def test_a_message_that_asks_to_forget_arms(message):
    armed = await deletes.arm_pending_deletes(_session(message), ["L'usuari es diu Jordi"], _port(), user_message=message)
    assert armed is not None and armed.kind == "delete_pending"


async def test_a_bare_si_after_a_request_to_forget_arms():
    session = _session("oblida que em dic Jordi", "sí")
    armed = await deletes.arm_pending_deletes(session, ["L'usuari es diu Jordi"], _port(), user_message="sí")
    assert armed is not None


@pytest.mark.parametrize("yes", ["Sí!", "sí, si us plau", "Sí, gràcies", "ok", "vale", "d'acord", "yes please"])
async def test_a_short_yes_after_a_request_to_forget_arms(yes):
    # Review 04/10: only a bare «sí» counted; every other yes armed nothing.
    session = _session("oblida que em dic Jordi", yes)
    armed = await deletes.arm_pending_deletes(session, ["L'usuari es diu Jordi"], _port(), user_message=yes)
    assert armed is not None


async def test_a_long_yes_is_a_new_message_not_a_confirmation():
    yes = "sí, i a més vull explicar-te una cosa del meu gos"
    session = _session("oblida que em dic Jordi", yes)
    armed = await deletes.arm_pending_deletes(session, ["L'usuari es diu Jordi"], _port(), user_message=yes)
    assert armed is None


async def test_a_bare_si_after_anything_else_arms_nothing():
    # «Vols que guardi alguna cosa?» — «sí»: the live reply ended with that question.
    session = _session("com funciona la teva memòria?", "sí")
    armed = await deletes.arm_pending_deletes(session, ["L'usuari es diu Jordi"], _port(), user_message="sí")
    assert armed is None


async def test_a_bare_si_finds_the_previous_message_even_if_this_one_is_not_stored_yet():
    session = _session("oblida que em dic Jordi")
    armed = await deletes.arm_pending_deletes(session, ["L'usuari es diu Jordi"], _port(), user_message="sí")
    assert armed is not None


async def test_this_turns_message_is_recognised_by_equality_not_containment():
    # «sí» is IN «oblida-ho, sí»: a containment test would drop the request as
    # if it were this turn's own message, and refuse a confirmation that is one.
    session = _session("oblida-ho, sí")
    armed = await deletes.arm_pending_deletes(session, ["L'usuari es diu Jordi"], _port(), user_message="sí")
    assert armed is not None
