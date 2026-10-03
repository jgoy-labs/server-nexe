"""The prose that frames retrieved context is ONE piece, and the user's message is not it.

This is the alarm for the context-presentation work, written against the target
and RED on purpose the day it lands. Each step of the plan makes more of it
green; when it is all green the piece is done.

What it asks, and why each one:

* **The user's last turn is byte-identical to what the user typed.** B030 layer
  2d already decided this for retrieved content
  (`core/endpoints/chat_sanitization.py:337-343`: *"injected prose spoke with
  the USER's authority... the real user message arrives clean as the last
  word"*), but `_doc_framing` escaped the reform and is still glued onto the
  message at `core/context_budget.py:278`.
* **The document's sentence sits AFTER the closing delimiter**, not inside the
  user's words. Its own text demands that position — it says "del bloc de
  context ANTERIOR".
* **The source legend sits BEFORE the opening delimiter.** It is the server's
  own trusted prose; `/v1` wraps it INSIDE the delimiters today
  (`core/endpoints/chat.py:468`), which marks the server's voice as untrusted
  data.
* **Both doors say the SAME thing.** Today they carry two different legends for
  the same job: a long one at the UI naming the three section labels (397 chars
  in Catalan) and a one-liner at `/v1` (64).

**Two layers, on purpose.** The document half is driven through `turn_lab` —
real adapter tables, real disk-backed SessionManager — because what matters is
what reaches the assembled prompt. The legend half calls the two injection
functions directly: `turn_lab` patches `build_rag_context` to retrieve nothing
inside every call (`conftest.py:232`), so a turn there can never carry RAG
text. Same reason the retrieval itself is not re-tested here: this file is
about PRESENTATION, and the two functions are exactly where the two doors
diverge.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.asyncio

#: Every assertion here was written against the TARGET and six of the eight
#: started red, marked `xfail(strict=True)`. Strict did its job: as each step
#: landed, the test failed FOR PASSING and forced the mark off. There are none
#: left — which is what "the piece is done" means, stated by the suite instead
#: of by a note somewhere saying it.

DOC_NAME = "informe.txt"
DOC_TEXT = "El pressupost puja un 4%."
RAG_TEXT = "[DOCUMENTACIO DEL SISTEMA]\nnexe corre localment."

OPEN_DELIM = "[CONTEXT "
CLOSE_DELIM = "[FI CONTEXT "

DOC_SENTENCE = "Respon basant-te en el DOCUMENT ADJUNTAT"


def _turns(ctx) -> list[dict]:
    return [m for m in (ctx.prompt or []) if isinstance(m, dict)]


def _last_user(ctx) -> str:
    """The user's own words, as the engine gets them. #1125 puts the time the
    message was sent in front of it at both doors — a line of its own, not a
    framing sentence — so it is taken off before comparing."""
    from core.chat_prompt import message_time_line

    users = [m for m in _turns(ctx) if m.get("role") == "user"]
    text = (users[-1].get("content") or "") if users else ""
    head = message_time_line(datetime.now(timezone.utc), ctx.lang or "ca").split(":", 1)[0]
    if text.startswith(head) and "]\n\n" in text:
        text = text.split("]\n\n", 1)[1]
    return text


def _context_turn(messages: list[dict]) -> str:
    """The user turn carrying the delimited block.

    `role != "system"` is not decoration: the static RAG security rule NAMES
    the delimiters (`chat_sanitization.py:275-316`), so the system message
    contains the literal `[CONTEXT ` and a naive scan finds it first.
    """
    for m in messages:
        if m.get("role") == "system":
            continue
        content = m.get("content") or ""
        if OPEN_DELIM in content:
            return content
    return ""


# ── the user's message stays the user's ──────────────────────────────────────

class TestTheUserMessageIsNeverTouched:

    async def test_ui_leaves_the_message_alone_when_a_document_is_attached(
        self, turn_lab, session_manager,
    ):
        """GREEN since the presentation piece landed. Mutation: glue the
        sentence back onto the message (`f"{framing}\\n\\n{message}"`) and this
        goes red again."""
        session = session_manager.get_or_create_session("framing-ui-doc")
        session.attach_document(DOC_NAME, DOC_TEXT, [DOC_TEXT], total_chunks=1)
        session_manager._save_session_to_disk(session)

        message = "Em pots resumir l'informe?"
        ctx = await turn_lab.ui(
            streaming=False, session_id="framing-ui-doc", message=message,
        )

        assert _last_user(ctx) == message, (
            "the web door prepends its framing sentence to the user's own message; "
            "B030 layer 2d already decided retrieved prose travels in its own turn"
        )

    async def test_api_leaves_the_message_alone_when_a_document_is_attached(
        self, turn_lab, session_manager,
    ):
        """GREEN today, and must STAY green once `/v1` gains the sentence: the
        whole point is that it arrives without editing the client's array."""
        session = session_manager.get_or_create_session("framing-api-doc")
        session.attach_document(DOC_NAME, DOC_TEXT, [DOC_TEXT], total_chunks=1)
        session_manager._save_session_to_disk(session)

        message = "What does the report say?"
        ctx = await turn_lab.api(session_id="framing-api-doc", message=message)

        assert _last_user(ctx) == message

    async def test_the_document_sentence_follows_the_closing_delimiter(
        self, turn_lab, session_manager,
    ):
        """GREEN since the presentation piece landed. It says "del bloc de
        context ANTERIOR" — the word encodes the position, so the sentence
        belongs after the block, not before the user's question."""
        session = session_manager.get_or_create_session("framing-ui-after")
        session.attach_document(DOC_NAME, DOC_TEXT, [DOC_TEXT], total_chunks=1)
        session_manager._save_session_to_disk(session)

        # Long and unambiguous on purpose: with a short message the language
        # detector (#850) cannot classify the turn, the turn falls back to the
        # server's language, and an assertion about Catalan wording becomes a
        # coin toss that depends on which tests ran before. Measured: "resum?"
        # passes alone and fails in the full suite.
        ctx = await turn_lab.ui(
            streaming=False, session_id="framing-ui-after",
            message="Em pots fer un resum de l'informe adjunt, si us plau?",
        )

        block = _context_turn(_turns(ctx))
        assert block, "no delimited context block in the prompt"
        assert "DOCUMENT ADJUNTAT" in block
        assert DOC_SENTENCE in block, "the framing sentence is not in the context turn"
        assert block.count(DOC_SENTENCE) == 1, "it must appear exactly once"
        assert block.index(DOC_SENTENCE) > block.index(CLOSE_DELIM), (
            "the sentence cites the block as 'anterior', so it must come after it"
        )

    async def test_ui_leaves_the_message_alone_when_an_image_is_attached(
        self, turn_lab,
    ):
        """#1081's sibling of the document case above: the image note used to
        be `_inject_image_block` gluing itself onto `messages[-1]`. Mutation:
        glue the note back onto the message and this goes red."""
        message = "Què hi ha en aquesta imatge?"
        ctx = await turn_lab.ui(
            streaming=False, session_id="framing-ui-image", message=message,
            body_extra={"image_b64": "aGVsbG8=", "image_type": "image/png"},
        )

        assert _last_user(ctx) == message

    async def test_the_image_note_travels_in_its_own_turn(self, turn_lab):
        """Same rule as the document's closing sentence, for the piece with no
        block to sit after: a note with nowhere to attach itself is not a
        licence to attach it to the user's message. Mutation: fold the note
        back into the last user turn and this goes red."""
        message = "Què hi ha en aquesta imatge?"
        ctx = await turn_lab.ui(
            streaming=False, session_id="framing-ui-image-2", message=message,
            body_extra={"image_b64": "aGVsbG8=", "image_type": "image/png"},
        )

        turns = _turns(ctx)
        note_turns = [
            m for m in turns
            if m.get("role") == "user" and "adjuntat una imatge" in (m.get("content") or "")
        ]
        assert note_turns, f"no separate turn carries the image note: {turns}"
        assert note_turns[0] is not turns[-1], "the note must not be the user's own last turn"


# ── one piece means one text, at both doors ──────────────────────────────────

def _ui_injection(rag_context: str, lang: str) -> list[dict]:
    from core.context_budget import _inject_context_into_messages

    messages, _pct, _injected = _inject_context_into_messages(
        [], "què és nexe?", "", rag_context,
        {"doc_truncated_pct": 0, "doc_kept_chars": 0}, 5000, 0, lang,
    )
    return messages


def _api_injection(rag_context: str, lang: str) -> list[dict]:
    from core.endpoints.chat import _inject_rag_context_into_messages

    messages = [{"role": "user", "content": "què és nexe?"}]
    # `has_rag=True` is what the `budget` adapter passes (`bool(ctx.recall_text)`):
    # the door knows which half of the block is retrieval and which is the
    # attached document, and the presenter is told the shape, not the content.
    _inject_rag_context_into_messages(messages, rag_context, lang, has_rag=True)
    return messages


def _legend_of(block: str) -> str:
    return block.split(OPEN_DELIM)[0].strip()


class TestProseSitsOutsideTheDelimiters:

    @pytest.mark.parametrize("door", ["ui", "api"])
    async def test_the_source_legend_precedes_the_opening_delimiter(self, door):
        """`/v1` used to wrap the legend INSIDE the nonce'd pair, telling the
        model the server's own instructions were untrusted data. Mutation: put
        it back inside `wrap_untrusted_context` and the api case goes red."""
        inject = _ui_injection if door == "ui" else _api_injection
        block = _context_turn(inject(RAG_TEXT, "ca"))

        assert block, f"the {door} door produced no delimited context block"
        assert _legend_of(block), (
            f"the {door} door keeps its source legend inside the delimiters — "
            "trusted server prose marked as retrieved data"
        )


class TestBothDoorsSayTheSameThing:

    @pytest.mark.parametrize("lang", ["ca", "es", "en"])
    async def test_the_two_doors_carry_the_same_legend(self, lang):
        """There used to be two: a long legend naming the three labels at the
        UI and a one-liner at `/v1`. Same retrieval, same language, two
        framings. Mutation: give either door its own text back and this goes
        red in all three languages."""
        ui_block = _context_turn(_ui_injection(RAG_TEXT, lang))
        api_block = _context_turn(_api_injection(RAG_TEXT, lang))
        assert ui_block and api_block, "both doors must produce a context block"

        assert _legend_of(ui_block) == _legend_of(api_block), (
            "the same retrieval is framed with two different texts depending on "
            "which door the turn came through"
        )


# ── the piece is actually detachable, and this is the proof ──────────────────

class TestAPresenterCanBeReplaced:
    """Without this, "pluggable" is a claim nobody checked.

    A port whose implementation is resolved but never consulted looks exactly
    like one that works: every prompt still comes out right, because the
    default is doing the job. The mutation "stop passing `app_state` down the
    chain" is invisible to every other test in the repo.
    """

    async def test_a_substituted_presenter_reaches_the_real_prompt(
        self, turn_lab, session_manager,
    ):
        """Mutation: drop `app_state=ctx.app_state` from the `budget` adapter
        (`turn_adapters.py`) or `app_state` from `_inject_context_into_messages`
        and this goes red — the default's wording comes back instead."""
        from core.context_presentation import ContextFraming

        class _Shouty:
            def frame(self, shape):
                return ContextFraming(
                    legend="", closing="LLEGEIX EL DOCUMENT I PROU.",
                )

        session = session_manager.get_or_create_session("framing-swap")
        session.attach_document(DOC_NAME, DOC_TEXT, [DOC_TEXT], total_chunks=1)
        session_manager._save_session_to_disk(session)
        turn_lab.app_state.context_presenter = _Shouty()
        try:
            ctx = await turn_lab.ui(
                streaming=False, session_id="framing-swap",
                message="Em pots fer un resum de l'informe adjunt, si us plau?",
            )
        finally:
            del turn_lab.app_state.context_presenter

        block = _context_turn(_turns(ctx))
        assert "LLEGEIX EL DOCUMENT I PROU." in block, (
            "the substituted presenter never reached the prompt — the port is "
            "resolved but not consulted"
        )
        assert DOC_SENTENCE not in block, "the default's wording came through too"
        assert DOC_TEXT in block, "the document itself must still be there"
