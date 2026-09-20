"""The prompt's scaffolding answers in the turn's language, not the server's (#1072).

`_inject_context_into_messages` writes everything that WRAPS the turn's
content: the B030 untrusted-context delimiters, the data-only ack turn, the
sentence that frames an attached document and the one that frames retrieval.
All four came out of a single `_lang_key`, and that key was read from
`NEXE_LANG` — the server's own voice — while the content they wrap already
follows `ctx.lang`:

* the document HEADER follows the turn since #1063
  (`tests/core/turn/test_document_block_speaks_the_turn_lang.py`);
* the RAG SECTION LABELS the framing sentence cites by name are built by
  `chat_rag._format_results`, and BOTH doors pass `ctx.lang` to it
  (`turn_adapters.py`, `adapters_api.py`).

So with this repo's own `.env` (`NEXE_LANG=ca`) an English conversation got an
`ATTACHED DOCUMENT (x.txt)` header underneath a framing sentence in Catalan —
#1063's bug, inverted, and surviving a fix that looked straight at it. The
#1063 comment even asserted the sentence "already answers in the turn's
language"; it did not.

The pair is what matters here, not either half: these tests assert the header
and the sentence that cites it come out in the SAME language, which is the
invariant `core/endpoints/chat_rag.py` calls deliberate.
"""
from __future__ import annotations

import pytest

from core.context_budget import _inject_context_into_messages

BUDGET = {"doc_truncated_pct": 0, "doc_kept_chars": 5000}


def _inject(*, lang, document_context="", rag_context="", has_image=False):
    messages, _pct, _injected = _inject_context_into_messages(
        [], "quina és la contrasenya?", document_context, rag_context,
        BUDGET, 5000, 0, lang, has_image=has_image,
    )
    return "\n".join(
        m.get("content", "") for m in messages if isinstance(m.get("content"), str)
    )


# ── the document's framing sentence ──────────────────────────────────────────

def test_document_framing_follows_the_turn_not_nexe_lang(monkeypatch):
    """Mutation: drop `lang` from `_assemble_engine_messages`'s call and this
    goes red — the sentence reverts to Catalan while the turn is English.
    """
    monkeypatch.setenv("NEXE_LANG", "ca")

    text = _inject(lang="en", document_context="the password is PINYA-COLADA-42")

    assert "Answer based on the ATTACHED DOCUMENT" in text, text
    assert "Respon basant-te en el DOCUMENT ADJUNTAT" not in text, text


def test_no_turn_lang_still_falls_back_to_the_server(monkeypatch):
    """The fallback is not a swap: a caller with no turn language in hand gets
    what it got before (`NEXE_LANG`), the same shape `_build_document_context`
    uses for `lang=None`. Without this, the fix would be a silent behaviour
    change for every path that does not thread the turn through.
    """
    monkeypatch.setenv("NEXE_LANG", "ca")

    text = _inject(lang=None, document_context="contingut")

    assert "Respon basant-te en el DOCUMENT ADJUNTAT" in text, text


# ── the retrieval framing sentence, which cites the section labels ───────────

def test_rag_instruction_follows_the_turn_too(monkeypatch):
    """The sentence names the labels — `[SYSTEM DOCUMENTATION]` and siblings —
    and `_format_results` already builds those in the turn's language at both
    doors. Leaving this one on `NEXE_LANG` is precisely what broke the
    correspondence `chat_rag` calls deliberate.
    """
    monkeypatch.setenv("NEXE_LANG", "ca")

    text = _inject(lang="en", rag_context="[SYSTEM DOCUMENTATION] nexe runs locally")

    assert "RETRIEVED INFORMATION. USE IT to answer." in text, text
    assert "INFORMACIO RECUPERADA" not in text, text


@pytest.mark.parametrize("lang,fragment", [
    ("ca", "Respon basant-te en el DOCUMENT ADJUNTAT"),
    ("es", "Responde basandote en el DOCUMENTO ADJUNTO"),
    ("en", "Answer based on the ATTACHED DOCUMENT"),
    ("fr", "Answer based on the ATTACHED DOCUMENT"),  # unsupported -> en, as its neighbours
])
def test_framing_in_each_supported_language(lang, fragment, monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "ca")
    assert fragment in _inject(lang=lang, document_context="contingut")


# ── the wiring, and the pair the whole finding is about ──────────────────────

@pytest.mark.asyncio
async def test_a_real_spanish_turn_gets_header_and_sentence_in_the_same_language(
    turn_lab, session_manager, fake_engine, monkeypatch,
):
    """The one that would stay green if only the unit above were fixed.

    Spanish, deliberately: the fallback for a caller with no `lang` is the
    server's `NEXE_LANG`, which this repo sets to `ca`, so a Catalan
    conversation would pass by coincidence. Spanish contradicts both the
    server's voice AND `_build_document_context`'s own `en` fallback, so
    either half reverting shows up here.

    Mutation: remove `lang` from the `_inject_context_into_messages` call in
    `core/turn/assemble.py` and this goes red on the sentence while the header
    stays Spanish — the exact split #1072 describes.
    """
    monkeypatch.setenv("NEXE_LANG", "ca")

    session = session_manager.get_or_create_session("scaffolding-es-turn")
    session.attach_document(
        "informe.txt", "El presupuesto sube un 4%.",
        ["El presupuesto sube un 4%."], total_chunks=1,
    )
    session_manager._save_session_to_disk(session)

    seen_messages = []
    original_chat = fake_engine.chat

    async def _capturing_chat(messages, **kwargs):
        seen_messages.append(messages)
        async for chunk in original_chat(messages, **kwargs):
            yield chunk

    fake_engine.chat = _capturing_chat

    await turn_lab.ui(
        streaming=False, session_id="scaffolding-es-turn",
        message="¿Podrías resumirme el informe adjunto, por favor? Muchas gracias de antemano.",
    )

    assert seen_messages, "the fake engine was never called"
    prompt_text = "\n".join(
        m.get("content", "") for m in seen_messages[0] if isinstance(m.get("content"), str)
    )
    # the header (#1063) and the sentence that cites it (#1072), together
    assert "DOCUMENTO ADJUNTO (informe.txt):" in prompt_text, prompt_text
    assert "Responde basandote en el DOCUMENTO ADJUNTO" in prompt_text, prompt_text
    assert "Respon basant-te" not in prompt_text, prompt_text


# ── the image note, same pattern, same finding ───────────────────────────────

def test_image_note_follows_the_turn_not_nexe_lang(monkeypatch):
    """The image note (#1081) is the sibling #1072 already fixed for the
    document and the RAG legend: scaffolding that used to be built from
    `NEXE_LANG` while everything around it follows the conversation. It moved
    off `_inject_image_block` (which had this exact bug) and now goes through
    the same `ContextShape`/`ContextFraming` port as the document's sentence,
    because the two can appear in the SAME turn — an image and a document
    attached together would put two different languages in one prompt.

    Mutation: drop `has_image` (or `lang`) from the `budget` adapter's call
    and this goes red.
    """
    monkeypatch.setenv("NEXE_LANG", "ca")

    text = _inject(lang="en", has_image=True)

    assert "The user has attached an image" in text, text
    assert "L'usuari ha adjuntat una imatge" not in text, text


def test_image_note_without_turn_lang_keeps_the_server_language(monkeypatch):
    monkeypatch.setenv("NEXE_LANG", "ca")

    text = _inject(lang=None, has_image=True)

    assert "L'usuari ha adjuntat una imatge" in text, text
