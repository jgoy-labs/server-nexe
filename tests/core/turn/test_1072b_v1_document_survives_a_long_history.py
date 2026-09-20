"""An attached document is not what /v1 gives up first (C4.4, the budget half).

Since #1078 the document reaches this door's prompt, and it travels the RAG
path: `budget` folds it in front of `ctx.recall_text` and `_trim_rag_context`
sizes the pair against what the turn has left. That sizing counted the
client's history WHOLE, and when it did not fit it dropped the retrieved block
— document included — with a warning that never said a document was in it.

What makes it a bug and not a trade-off is the ORDER. `_fit_v1_messages_to_window`
(#976) runs right after and drops whole turns, oldest first, until the prompt
fits. So the door gave up the document to make room for history that the very
next step then threw away. Measured: with an 8k-token window, a 4k-char
document and ~30k chars of client history, the document vanished entirely.

The fix does not touch the client's `messages` array — an OpenAI-compatible
API has no business editing it, which is why the framing sentence the web door
appends is still deliberately absent here. It only stops the budget from
counting history that is about to be trimmed anyway: when a document is
attached, the history that enters the arithmetic is capped at what will still
be there once the document has its place.
"""
from __future__ import annotations

from core.context_budget import compute_context_budget, resolve_max_context_chars
from core.endpoints.chat import _trim_rag_context

WINDOW = 8192
DOC = "D" * 4000
RECALL = "R" * 500


def _messages(history_chars: int) -> list:
    """A /v1 payload: system, a long history, and the question being asked."""
    return [
        {"role": "system", "content": "S" * 1500},
        {"role": "user", "content": "H" * history_chars},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "what does the document say?"},
    ]


def test_a_long_history_no_longer_costs_the_whole_document():
    """Mutation: drop the `document_chars` cap in `_trim_rag_context` and this
    goes red — the context comes back empty, which is the old behaviour.
    """
    kept = _trim_rag_context(
        DOC + RECALL, _messages(30_000), WINDOW, document_chars=len(DOC),
    )

    assert kept, "the whole retrieved block was dropped, document and all"
    assert kept.startswith("D"), kept[:50]
    assert kept.count("D") >= 4000 * 0.9, (
        f"only {kept.count('D')} of the document's 4000 chars survived"
    )


def test_without_a_document_nothing_changes():
    """The control: a turn with no document keeps the old arithmetic exactly.

    This is what says the fix is a cap on a specific case and not a quiet
    loosening of the budget for everyone — with the same oversized history and
    no document, retrieval is still dropped.
    """
    assert _trim_rag_context(RECALL, _messages(30_000), WINDOW, document_chars=0) == ""


def test_a_history_that_fits_is_left_alone():
    """The cap only bites when the history would push the document out; a
    normal turn must compute the same budget it always did.
    """
    msgs = _messages(2_000)
    kept = _trim_rag_context(DOC + RECALL, msgs, WINDOW, document_chars=len(DOC))

    unchanged = _trim_rag_context(DOC + RECALL, msgs, WINDOW, document_chars=0)
    assert kept == unchanged == DOC + RECALL


def test_the_document_still_yields_to_a_window_it_cannot_fit_in():
    """The cap is not a licence to overflow: a document bigger than the whole
    turn still gets trimmed, it just is not silently dropped in favour of
    history. `fit_prompt_to_window` is the backstop either way.
    """
    huge = "D" * 100_000
    kept = _trim_rag_context(huge, _messages(2_000), WINDOW, document_chars=len(huge))

    max_chars = resolve_max_context_chars(window_tokens=WINDOW)
    assert 0 < len(kept) < len(huge)
    assert len(kept) <= max_chars


def test_the_order_that_made_this_a_bug_and_not_a_trade_off():
    """Documents the measurement the docstring cites, executably: with the old
    arithmetic the budget went negative on history alone, while #976's fit step
    was about to drop those same turns. If `compute_context_budget` ever starts
    reserving for the document by itself, this is the test that says so.
    """
    max_chars = resolve_max_context_chars(window_tokens=WINDOW)
    old = compute_context_budget(
        max_chars, system_chars=1500, history_chars=30_000, message_chars=80,
        document_chars=len(DOC), history_ratio=0.0, response_buffer=500,
    )
    assert old["available_chars"] < 0, (
        "the premise of this fix is gone: history alone no longer exhausts the budget"
    )
    assert old["doc_kept_chars"] == 0, "the document used to be dropped whole"


# ── the framing prose is paid for, not added on top ──────────────────────────

def test_the_framing_prose_comes_out_of_the_same_budget():
    """C4.4: `/v1` adopted the web door's long source legend (397 chars in
    Catalan against the 64 of the one-liner it had). Prose the server adds is
    prompt the turn ships, so it is subtracted from what the payload may use —
    otherwise "unified framing" would quietly mean "a bigger prompt", and the
    engines this runs on do not truncate, they raise.

    Asserted here and not through `test_fd_block4_budget_shared.py`: measured,
    none of that test's rows comes within 283 chars of its `WRAPPER_SLACK`, so
    adding 397 to the prompt would not have moved it. A promise nothing can
    break is not a gate.

    Mutation: drop `- scaffold_chars` in `_trim_rag_context` and this goes red.
    """
    # A history long enough that the trim actually BITES: with room to spare
    # the payload is returned whole either way, and a test on that case would
    # pass with the subtraction deleted. Measured: 18k of history leaves ~2.9k
    # for a 4.5k block, so the cut is real and its size is the assertion.
    msgs = _messages(18_000)
    without = _trim_rag_context(DOC + RECALL, msgs, WINDOW)
    with_prose = _trim_rag_context(DOC + RECALL, msgs, WINDOW, scaffold_chars=500)

    assert 0 < len(without) < len(DOC + RECALL), (
        "this case must be one where the budget actually trims, or it proves nothing"
    )
    assert len(with_prose) == len(without) - 500, (
        "the framing prose was not charged to the turn's budget: the payload "
        "kept the same room while the prompt grew by the length of the prose"
    )


def test_a_turn_with_no_prose_is_charged_nothing():
    """The control: `scaffold_chars=0` must compute byte-for-byte what it did
    before this parameter existed."""
    msgs = _messages(18_000)
    assert (
        _trim_rag_context(DOC + RECALL, msgs, WINDOW)
        == _trim_rag_context(DOC + RECALL, msgs, WINDOW, scaffold_chars=0)
    )
