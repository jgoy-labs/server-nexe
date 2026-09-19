"""#1078 — a document attached to the session must reach the /v1 prompt too.

`session` (adapters_api.py) has read the attached document into
`ctx.attachments` since C4.3, and `recall` has narrowed the RAG collections
for it since C4.3-a — but nothing at this door ever turned the document into
text and put it in front of the model: `_assemble_v1_messages` had no
parameter for it, and `_build_document_context` (the one place that builds
that text) was only ever called from the UI door's `budget` adapter, which
its own docstring said outright ("The API door (/v1) does not call this
function at all yet").

Driven through `turn_lab.api()` — the real adapter table, a real disk-backed
SessionManager, the same harness `test_i1_one_sequence.py` uses — because a
unit test of `budget` alone with a hand-built `ctx.attachments` would not have
caught this: the bug was that NOTHING downstream read it, not that `session`
failed to write it.
"""
from __future__ import annotations


def _prompt_text(ctx) -> str:
    return "\n".join(m.get("content", "") for m in ctx.prompt)


class TestDocumentReachesV1Prompt:
    async def test_attached_document_text_reaches_the_v1_prompt(self, turn_lab, session_manager):
        session_id = "doc-1078-v1"
        session = session_manager.get_or_create_session(session_id)
        session.attach_document("secret.txt", "the password is PINYA-COLADA-42")

        ctx = await turn_lab.api(session_id=session_id, message="what is the password?")

        assert "PINYA-COLADA-42" in _prompt_text(ctx), (
            "the attached document's content never reached the assembled "
            "/v1 messages — ctx.prompt was built without it"
        )

    async def test_no_attached_document_leaves_the_v1_prompt_unchanged(self, turn_lab, session_manager):
        """Control: a session with nothing attached must not gain a document
        section — `_build_document_context` should never run for it."""
        session_id = "doc-1078-v1-none"
        session_manager.get_or_create_session(session_id)

        ctx = await turn_lab.api(session_id=session_id, message="hola")

        assert "PINYA-COLADA" not in _prompt_text(ctx)

    async def test_attached_document_reaches_both_doors_the_same_way(self, turn_lab, session_manager):
        """The point of #1078 was parity: the UI door already did this
        (C4.3). Both doors must end up with the document in the prompt they
        actually send, not just agree on which RAG collections to skip."""
        session_id = "doc-1078-parity"
        session = session_manager.get_or_create_session(session_id)
        session.attach_document("secret.txt", "the password is PINYA-COLADA-42")

        api_ctx = await turn_lab.api(session_id=session_id, message="what is the password?")
        ui_ctx = await turn_lab.ui(streaming=False, session_id=session_id, message="what is the password?")

        assert "PINYA-COLADA-42" in _prompt_text(api_ctx)
        assert "PINYA-COLADA-42" in "\n".join(m.get("content", "") for m in ui_ctx.prompt)


class TestAMalformedDocumentDoesNotEndTheTurn:
    """A document the turn cannot use costs the document, not the turn.

    Audit 19/09: `_build_document_context` read `filename` by subscript while
    reading every other field with `.get`, so a session holding a document
    without one raised KeyError from inside `budget`. Once C4.3-b gave `/v1` a
    `budget` that calls this function, that became an uncaught 500 at a door
    that had answered the same request the day before. The shape is session
    state and may come from an older build, so it is not guaranteed.
    """

    def test_a_document_without_filename_is_skipped_not_raised(self):
        from core.turn.assemble import _build_document_context

        text, shown, total = _build_document_context(
            {"chunks": ["the password is PINYA-COLADA-42"]},
            context_window=8192, lang="ca",
        )
        assert text == ""
        assert (shown, total) == (0, 0)

    def test_an_empty_filename_counts_as_missing(self):
        from core.turn.assemble import _build_document_context

        text, _, _ = _build_document_context(
            {"filename": "", "chunks": ["x"]}, context_window=8192, lang="ca",
        )
        assert text == ""

    def test_a_well_formed_document_still_builds(self):
        """The control: without it, returning "" unconditionally would pass."""
        from core.turn.assemble import _build_document_context

        text, shown, total = _build_document_context(
            {"filename": "secret.txt", "chunks": ["the password is PINYA-COLADA-42"]},
            context_window=8192, lang="ca",
        )
        assert "PINYA-COLADA-42" in text
        assert "secret.txt" in text
        assert (shown, total) == (1, 1)
