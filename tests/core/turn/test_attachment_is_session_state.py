"""C4.3 / D4 — the attached document belongs to the session, so both doors see it.

Until C4.3 the document was fetched deep inside `budget`, by one door only
(`_build_turn_context` reached into the session for it). That is what made an
attachment a property of /ui/chat rather than of the conversation: a client
talking to the same session over /v1 had no way to reach a document the user had
just uploaded.

`TURN_STEPS` says the `session` step writes `attachments`, and this is what
holds that claim up. I2 cannot: it checks that every `reads` is satisfied by an
earlier `writes`, and `validate` already declares `attachments` — so deleting
the declaration from `session` leaves I2 perfectly green while the document
silently stops arriving. The assertion has to be that the document IS there,
measured through a real turn at each door.
"""
from __future__ import annotations

import pytest

DOC = {
    "filename": "informe.txt",
    "content": "El pressupost del trimestre puja un 4%.",
    "chunks": ["El pressupost del trimestre puja un 4%."],
    "total_chunks": 1,
    "total_chars": 39,
    "current_chunk": 0,
}


def _attach(session_manager, session_id: str) -> None:
    session = session_manager.get_or_create_session(session_id)
    session.attach_document(
        DOC["filename"], DOC["content"], DOC["chunks"], total_chunks=DOC["total_chunks"],
    )
    session_manager._save_session_to_disk(session)


@pytest.mark.asyncio
async def test_the_web_door_reads_the_attached_document_into_the_turn(
    turn_lab, session_manager,
):
    _attach(session_manager, "doc-ui")

    ctx = await turn_lab.ui(streaming=False, session_id="doc-ui")

    doc = ctx.attachments.get("document")
    assert doc is not None, (
        "the `session` step declares it writes `attachments`; the web door "
        "left it empty, so the document never became turn state"
    )
    assert doc["filename"] == DOC["filename"]


@pytest.mark.asyncio
async def test_the_api_door_reads_the_same_document_from_the_same_session(
    turn_lab, session_manager,
):
    """This one is D4 itself: nothing uploaded through /v1, and /v1 still sees it."""
    _attach(session_manager, "doc-api")

    ctx = await turn_lab.api(session_id="doc-api")

    doc = ctx.attachments.get("document")
    assert doc is not None, (
        "a document attached to the session was invisible at /v1 — which is "
        "exactly the state D4 exists to end"
    )
    assert doc["filename"] == DOC["filename"]
    assert doc["chunks"] == DOC["chunks"]


@pytest.mark.asyncio
async def test_a_session_with_no_document_carries_none_at_both_doors(turn_lab):
    """The control: `attachments["document"]` is written either way, so a door
    that simply never sets the key would pass the two tests above by accident
    if they only checked truthiness of a missing key."""
    ui = await turn_lab.ui(streaming=False, session_id="empty-ui")
    api = await turn_lab.api(session_id="empty-api")

    assert "document" in ui.attachments, "the web door did not write the key at all"
    assert "document" in api.attachments, "the API door did not write the key at all"
    assert ui.attachments["document"] is None
    assert api.attachments["document"] is None
