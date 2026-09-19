"""C4.2 — one prompt, one recall, one language resolution, both chat doors.

The three questions this sub-fase closes, each measured on the REAL adapter
tables (`ui_adapters`, `api_adapters`) rather than on the functions that were
moved — C4.2 moves eleven symbols, and a test that pinned where they live
would have to be rewritten by the next sub-fase while proving nothing about
behaviour:

* **the collection notes reach both doors** — #851's truth-telling notes were
  a `/ui/chat` behaviour. `/v1` has always had the same `rag_collections`
  field and retrieval has always honoured it, so an API turn with the
  documentation collection switched off got no documents and a system prompt
  that still promised them. This is the visible change of C4.2;
* **the sticky language advances once per turn** — the hysteresis is a state
  machine on the session (#850): a second resolution inside the same turn
  would confirm its own candidate and flip the reply language mid-turn,
  invalidating the prefix cache the policy exists to protect;
* **recall is identical at both doors** — given the same retrieval, the two
  doors must end the step with the same text and the same items.

No conditional mocks: `build_rag_context` is patched with one function that
answers the same thing whatever it is called with, so no path is hidden
behind an argument the fake happens not to match.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks

from core.memory_access import DOCS_COLLECTION, MEMORY_COLLECTION
from core.turn.context import TurnContext
from core.turn.prompt import _COLLECTIONS_OFF_NOTES
from tests.core.turn.conftest import door_patches

pytestmark = pytest.mark.asyncio

#: Everything except the documentation collection: the toggle a user flips
#: when they want the model to answer from the conversation alone.
ONLY_MEMORY = [MEMORY_COLLECTION]

#: What retrieval "found", the same for every caller and every argument.
FOUND_TEXT = "el peix es diu Bombolla"
FOUND_ITEMS = [(MEMORY_COLLECTION, 0.91)]


async def _found(*_args, **_kwargs):
    return FOUND_TEXT, list(FOUND_ITEMS)


async def _system_prompt_at(door: str, lab, *, rag_collections) -> str:
    """The `system_prompt` step of one door, run for real."""
    if door == "ui":
        from plugins.web_ui_module.api.turn_adapters import ui_adapters

        session = lab.session_manager.get_or_create_session(f"cols-{door}")
        ctx = TurnContext(
            turn_id="t", entry="ui", message="hola", lang="ca",
            body={"message": "hola", "rag_collections": rag_collections},
            app_state=lab.app_state, session=session,
        )
        table = ui_adapters(lab.session_manager, streaming=False)
    else:
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message
        from core.turn.adapters_api import api_adapters

        body = ChatCompletionRequest(
            messages=[Message(role="user", content="hola")],
            rag_collections=rag_collections, use_rag=True,
        )
        ctx = TurnContext(
            turn_id="t", entry="api", message="hola", lang="ca",
            body=body, app_state=lab.app_state,
        )
        table = api_adapters(BackgroundTasks())
    with door_patches(lab.server_state, lab.memory_helper):
        await table["system_prompt"](ctx)
    return ctx.system_prompt


@pytest.mark.parametrize("door", ["ui", "api"])
async def test_collection_off_note_reaches_both_doors(door, turn_lab) -> None:
    """A turn that switched the documentation collection OFF says so in the
    system prompt — at `/ui/chat`, which has done it since #851, and at
    `/v1/chat/completions`, which is where C4.2 takes it.

    Found live before #851 and still true at the API door until here: docs
    disabled, RAG correctly empty, and the model answering documentation
    questions from what the static prompt claimed it had.
    """
    prompt = await _system_prompt_at(door, turn_lab, rag_collections=ONLY_MEMORY)
    assert _COLLECTIONS_OFF_NOTES[DOCS_COLLECTION]["ca"] in prompt, (
        f"the {door} door does not tell the model the documentation collection "
        f"is off: {prompt[-400:]!r}"
    )


@pytest.mark.parametrize("door", ["ui", "api"])
async def test_no_note_when_every_collection_is_on(door, turn_lab) -> None:
    """The twin the test above needs: the notes are per-request truth, not a
    constant. `rag_collections=None` (old clients, API users) is everything
    enabled, and a prompt that carried the notes anyway would pass the first
    assertion while lying in the opposite direction."""
    prompt = await _system_prompt_at(door, turn_lab, rag_collections=None)
    for note in _COLLECTIONS_OFF_NOTES[DOCS_COLLECTION].values():
        assert note not in prompt, f"the {door} door claims a collection is off"


async def test_the_two_doors_finalise_the_prompt_the_same_way(turn_lab) -> None:
    """Same language, same toggles: the tail both doors append is the same.

    Only the tail: `/v1` may be handed a system message by its client and
    `/ui/chat` never is, so the BASE legitimately differs. What C4.2 makes one
    is everything after it — the collection notes and the unconditional RAG
    security rule.
    """
    ui_prompt = await _system_prompt_at("ui", turn_lab, rag_collections=ONLY_MEMORY)
    api_prompt = await _system_prompt_at("api", turn_lab, rag_collections=ONLY_MEMORY)
    note = _COLLECTIONS_OFF_NOTES[DOCS_COLLECTION]["ca"]
    assert ui_prompt.split(note, 1)[1] == api_prompt.split(note, 1)[1]


async def test_sticky_lang_is_resolved_once_per_turn(turn_lab) -> None:
    """#850's hysteresis advances exactly one step per turn.

    Two consecutive detections of a new language are needed to flip; the first
    only arms a candidate. So a turn that resolved the language twice would
    confirm its own candidate and flip mid-turn — the prefix cache invalidation
    the policy exists to prevent, paid on a single off-language message.

    Measured through a real turn, with the real detector: the resolution is a
    step of the turn now (`session`), and a second resolution anywhere in it
    would show up here as a language that flipped in one turn instead of two.
    """
    pytest.importorskip("lingua", reason="cal lingua per la detecció real")
    sid = "sticky-one-per-turn"
    await turn_lab.ui(
        streaming=False, session_id=sid,
        message="explica'm com funciona la memòria de sessions, si us plau",
    )
    session = turn_lab.session_manager.get_or_create_session(sid)
    assert session.lang == "ca", "the first real detection seeds the sticky language"

    ctx = await turn_lab.ui(
        streaming=False, session_id=sid,
        message="please explain the whole session memory system in detail",
    )
    assert session.lang == "ca", (
        "one English turn flipped the reply language — the hysteresis advanced "
        "twice in the same turn"
    )
    assert session.lang_pending == "en", "the candidate was not armed"
    assert ctx.lang == "ca", "the turn answered in the language it flipped away from"


async def test_recall_is_identical_for_both_doors(turn_lab) -> None:
    """Given the same retrieval, the two doors end the `recall` step with the
    same text and the same items.

    The text is compared RAW on purpose: sizing it to the serving engine's
    window is `budget`'s job at both doors since C4.2 — `recall` runs before
    `engine`, so at this point in the turn nobody knows what the window is.
    """
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message
    from core.turn.adapters_api import api_adapters
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    message = "què recordes de mi?"
    ui_ctx = TurnContext(
        turn_id="t", entry="ui", message=message, lang="ca",
        body={"message": message}, app_state=turn_lab.app_state,
        session=turn_lab.session_manager.get_or_create_session("recall-ui"),
    )
    api_ctx = TurnContext(
        turn_id="t", entry="api", message=message, lang="ca",
        body=ChatCompletionRequest(
            messages=[Message(role="user", content=message)], use_rag=True,
        ),
        app_state=turn_lab.app_state,
    )
    with patch("core.endpoints.chat_rag.build_rag_context", new=_found):
        await ui_adapters(turn_lab.session_manager, streaming=False)["recall"](ui_ctx)
        await api_adapters(BackgroundTasks())["recall"](api_ctx)

    assert ui_ctx.recall_text == api_ctx.recall_text == FOUND_TEXT
    assert list(ui_ctx.recall) == list(api_ctx.recall) == FOUND_ITEMS


async def test_both_doors_narrow_the_same_way_for_an_attached_document(turn_lab) -> None:
    """C4.3: the attached-document rule is the TURN's, not one door's.

    It used to hang off `ctx.session.has_attached_document()` inside the web
    door's adapter, so `/v1` did not obey it — a turn on a session with a
    document open searched the documents collection again at one door and not
    at the other. That is precisely what I1 says cannot happen: the door is a
    label on the step, not a switch inside it. Both doors now ask
    `collections_for_turn` with the document the `session` step wrote.

    This one is a CLIENT-VISIBLE change at `/v1`, which is why it is asserted
    and not assumed.
    """
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message
    from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION
    from core.turn.adapters_api import api_adapters
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    document = {"filename": "informe.pdf", "content": "hola", "chunks": ["hola"]}
    message = "què diu el document?"
    asked: dict[str, list] = {}

    async def _capture(*args, **kwargs):
        asked[args[0] if args else "?"] = kwargs.get("collections")
        return FOUND_TEXT, list(FOUND_ITEMS)

    session = turn_lab.session_manager.get_or_create_session("recall-both")
    session.attached_document = document
    ui_ctx = TurnContext(
        turn_id="t", entry="ui", message=message, lang="ca",
        body={"message": message}, app_state=turn_lab.app_state, session=session,
    )
    api_ctx = TurnContext(
        turn_id="t", entry="api", message=message, lang="ca",
        body=ChatCompletionRequest(
            messages=[Message(role="user", content=message)], use_rag=True,
        ),
        app_state=turn_lab.app_state,
    )
    # What the `session` step writes at both doors, stood in for here.
    ui_ctx.attachments["document"] = document
    api_ctx.attachments["document"] = document

    with patch("core.endpoints.chat_rag.build_rag_context", new=_capture):
        await ui_adapters(turn_lab.session_manager, streaming=False)["recall"](ui_ctx)
        await api_adapters(BackgroundTasks())["recall"](api_ctx)

    got = asked[message]
    assert KNOWLEDGE_COLLECTION not in got, f"the document's own collection was searched: {got}"
    assert MEMORY_COLLECTION in got and DOCS_COLLECTION in got, got


async def test_the_api_door_without_a_document_is_left_alone(turn_lab) -> None:
    """The narrowing only fires when there IS a document: an ordinary `/v1`
    turn keeps passing the client's toggle through untouched (`None` = search
    everything discovered), which is what it did before C4.3."""
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message
    from core.turn.adapters_api import api_adapters

    seen = {}

    async def _capture(*args, **kwargs):
        seen.update(kwargs)
        return FOUND_TEXT, list(FOUND_ITEMS)

    api_ctx = TurnContext(
        turn_id="t", entry="api", message="hola", lang="ca",
        body=ChatCompletionRequest(
            messages=[Message(role="user", content="hola")], use_rag=True,
        ),
        app_state=turn_lab.app_state,
    )
    with patch("core.endpoints.chat_rag.build_rag_context", new=_capture):
        await api_adapters(BackgroundTasks())["recall"](api_ctx)

    assert seen.get("collections") is None, (
        f"a turn with no document had its collections narrowed: {seen.get('collections')}"
    )


async def test_the_ui_door_drops_only_the_documents_collection(turn_lab) -> None:
    """The one thing that door still decides for itself, asserted so the
    convergence above cannot quietly delete it — but narrowed to what it was
    always meant to be.

    A session with an attached document already has ITS OWN knowledge for the
    turn, so the uploaded-documents collection is not searched. Until #1064
    this skipped the step whole, and one retrieval covers three collections:
    personal memory was going silent too, on every turn a document was open.
    The door now drops one collection instead of all of them.
    """
    from core.memory_access import DOCS_COLLECTION, KNOWLEDGE_COLLECTION, MEMORY_COLLECTION
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    session = turn_lab.session_manager.get_or_create_session("recall-doc")
    session.attached_document = {"filename": "x.txt", "content": "hola", "chunks": ["hola"]}
    ctx = TurnContext(
        turn_id="t", entry="ui", message="què diu el document?", lang="ca",
        body={"message": "què diu el document?"}, app_state=turn_lab.app_state,
        session=session,
    )
    # C4.3: the document reaches `recall` through the context, written by the
    # `session` step — exercising one step alone means standing in for it.
    ctx.attachments["document"] = session.attached_document
    seen = {}

    async def _capture(*args, **kwargs):
        seen.update(kwargs)
        return FOUND_TEXT, list(FOUND_ITEMS)

    with patch("core.endpoints.chat_rag.build_rag_context", new=_capture):
        await ui_adapters(turn_lab.session_manager, streaming=False)["recall"](ctx)

    asked = seen.get("collections")
    assert asked is not None, "the step was skipped whole again (#1064)"
    assert KNOWLEDGE_COLLECTION not in asked, (
        f"the attached document's own collection was searched anyway: {asked}"
    )
    assert MEMORY_COLLECTION in asked, (
        "personal memory went silent because a document was attached (#1064) — "
        f"asked for {asked}"
    )
    assert DOCS_COLLECTION in asked, asked


async def test_an_empty_toggle_stays_empty_with_a_document_attached(turn_lab) -> None:
    """A client that switched every source OFF must keep searching nothing.

    `build_rag_context` treats `[]` as "the user disabled every source" and
    `None` as "no toggle, search everything" — turning the first into the
    second would answer from personal memory against an explicit opt-out.
    Dropping a collection from an already-empty list must stay empty.
    """
    from plugins.web_ui_module.api.turn_adapters import ui_adapters

    session = turn_lab.session_manager.get_or_create_session("recall-doc-empty")
    session.attached_document = {"filename": "x.txt", "content": "hola", "chunks": ["hola"]}
    ctx = TurnContext(
        turn_id="t", entry="ui", message="què diu?", lang="ca",
        body={"message": "què diu?", "rag_collections": []},
        app_state=turn_lab.app_state, session=session,
    )
    # C4.3: `recall` reads the document from the context, where the `session`
    # step puts it (`steps.py`: session writes `attachments`, recall reads it).
    # Exercising one step alone means standing in for the one before it.
    ctx.attachments["document"] = session.attached_document
    seen = {}

    async def _capture(*args, **kwargs):
        seen.update(kwargs)
        return FOUND_TEXT, list(FOUND_ITEMS)

    with patch("core.endpoints.chat_rag.build_rag_context", new=_capture):
        await ui_adapters(turn_lab.session_manager, streaming=False)["recall"](ctx)

    assert seen.get("collections") == [], (
        f"an explicit empty toggle was widened: {seen.get('collections')}"
    )
