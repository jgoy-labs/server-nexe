"""The document header agrees with the sentence that names it (#1063).

`core/context_budget.py::_doc_framing` already answers "Answer based on the
ATTACHED DOCUMENT..." in the turn's language. The header the framing sentence
refers to, built by `core/turn/assemble.py::_build_document_context`, used to
be Catalan no matter what: with the default `NEXE_LANG=en`, a model would read
that sentence and then find a block titled "DOCUMENT ADJUNTAT" right after it.
`core/endpoints/chat_rag.py` treats this correspondence as deliberate — "labels
per language — must match system prompt references" — and this was the one
label that broke it.

Two things, mirroring the pair `tests/core/endpoints/test_b030_untrusted_context.py`
already asks of `_doc_framing`:

* **the header follows `lang`, not `NEXE_LANG`** — measured with `NEXE_LANG`
  set to something the test then contradicts through the `lang` argument, so a
  test that forgot to thread `lang` through would still show Catalan and go
  red;
* **the common case (no lang, single chunk) is untouched** — convergence is
  not a swap.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.turn.assemble import _build_document_context

ONE_CHUNK_DOC = {
    "filename": "informe.txt",
    "chunks": ["contingut sencer"],
    "total_chunks": 1,
}

PARTIAL_DOC = {
    "filename": "informe.txt",
    "chunks": ["primera part"],
    "total_chunks": 4,
    "total_chars": 12000,
}


def test_header_follows_lang_not_nexe_lang(monkeypatch):
    """Mutation: drop the `lang` forwarding at the one production call site
    (`turn_adapters.py`'s `budget` adapter) and this goes red — the header
    reverts to Catalan while `NEXE_LANG` here says otherwise, which is exactly
    the divergence #1063 was about.
    """
    monkeypatch.setenv("NEXE_LANG", "ca")  # if this leaked in, the test below would fail

    ctx, _shown, _total = _build_document_context(ONE_CHUNK_DOC, lang="en")

    assert "ATTACHED DOCUMENT (informe.txt):" in ctx, ctx
    assert "DOCUMENT ADJUNTAT" not in ctx, ctx


@pytest.mark.parametrize("lang,header", [
    ("ca", "DOCUMENT ADJUNTAT (informe.txt):"),
    ("es", "DOCUMENTO ADJUNTO (informe.txt):"),
    ("en", "ATTACHED DOCUMENT (informe.txt):"),
    (None, "ATTACHED DOCUMENT (informe.txt):"),  # no turn lang in scope -> en, never NEXE_LANG
    ("fr", "ATTACHED DOCUMENT (informe.txt):"),  # unsupported -> en, same fallback as its neighbours
])
def test_header_in_each_supported_language(lang, header):
    ctx, _shown, _total = _build_document_context(ONE_CHUNK_DOC, lang=lang)
    assert header in ctx, ctx


def test_partial_document_note_is_localized_too():
    """The pagination note that follows the header must not be left behind in
    Catalan while the header itself moves — a translated header over an
    untranslated note is the same bug in half the block.
    """
    ctx, shown, total = _build_document_context(PARTIAL_DOC, lang="en")
    assert shown == 1 and total == 4
    assert "Showing the first" in ctx, ctx
    assert "Mostrant les primeres" not in ctx, ctx


def test_english_document_context_carries_no_catalan_leftover():
    """Guards the whole function, not just the header: nothing below it should
    silently stay in Catalan once `lang="en"` is asked for.
    """
    ctx, _shown, _total = _build_document_context(PARTIAL_DOC, lang="en")
    for leftover in ("esta indexada", "pagines", "Mostrant"):
        assert leftover not in ctx, f"{leftover!r} leaked into the English block: {ctx!r}"


# ── the wiring, not just the function ────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_real_spanish_turn_gets_the_spanish_header(
    turn_lab, session_manager, fake_engine,
):
    """The unit tests above cover `_build_document_context` in isolation; this
    is the one that would stay green if `turn_adapters.py`'s `budget` adapter
    stopped forwarding `lang` — the production wiring, not the function.

    Spanish, not English: `_build_document_context`'s own fallback for a
    caller that passes no `lang` at all IS `"en"` (#1063's decision — this is
    turn content, never `NEXE_LANG`), so a mutation that drops the forwarding
    would go unnoticed by an English conversation, which would get the right
    header by coincidence. Spanish exposes it.

    Only the header is asserted, not the whole prompt: `_doc_framing`
    (`core/context_budget.py`), the sentence that CITES the header, is a
    separate and wider divergence — it reads `NEXE_LANG` (the server's
    voice), not `ctx.lang` (the conversation's), and that split is not
    #1063's claim to fix (see the finding's notes). This repo's own `.env`
    sets `NEXE_LANG=ca`, which is exactly what reproduces it here: after this
    fix, a Spanish conversation gets a Spanish header sitting under a
    Catalan framing sentence — the same invariant broken from the other side.

    Mutation: drop `lang=ctx.lang` from the `budget` adapter's call to
    `rc._build_turn_context` and this goes red — the fake engine receives the
    English header instead of the Spanish one the session's language has
    already turned to.
    """
    session = session_manager.get_or_create_session("doc-es-turn")
    session.attach_document(
        "informe.txt", "El pressupost puja un 4%.",
        ["El pressupost puja un 4%."], total_chunks=1,
    )
    session_manager._save_session_to_disk(session)

    seen_messages = []
    original_chat = fake_engine.chat

    async def _capturing_chat(messages, **kwargs):
        seen_messages.append(messages)
        async for chunk in original_chat(messages, **kwargs):
            yield chunk

    fake_engine.chat = _capturing_chat

    # Long enough and unambiguous enough for lingua's real detector (>=10
    # chars, #850) to seed the session's sticky language as Spanish on the
    # first turn.
    await turn_lab.ui(
        streaming=False, session_id="doc-es-turn",
        message="¿Podrías resumirme el informe adjunto, por favor? Muchas gracias de antemano.",
    )

    assert seen_messages, "the fake engine was never called"
    prompt_text = "\n".join(
        m.get("content", "") for m in seen_messages[0] if isinstance(m.get("content"), str)
    )
    assert "DOCUMENTO ADJUNTO (informe.txt):" in prompt_text, prompt_text
