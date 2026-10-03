"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/text/test_1124_no_source_caption.py
Description: #1124 — a reply ended in a bare "Font:". Seen live 02/10 with
             Qwen3.5-9B on MLX: "Sí, el teu nom és Jordi.\n\nFont:". The model
             wrote "Font: [MEMORIA DE L'USUARI]", as the RAG legend invited
             it to, and the label was stripped (#1086). The source belongs to
             the badge under the message, never to its text (Jordi, 02/10):
             a caption that only held labels goes whole, live and stored, in
             every shape a model writes it. A caption in words stays, and so
             does a "Fonts:" heading a list the user asked for.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import random

import pytest

from core.context_presentation.default import _RAG_LEGEND
from core.turn.text.clean import clean_model_text
from core.turn.text.tags import TagStreamFilter
from tests.core.turn.text.test_v1_stream_is_clean import _content, _stream_v1  # noqa: F401 — fixture below
from tests.plugins.web_ui_module.test_raonament_ui_wire import _msg, _wire

LABEL = "[MEMORIA DE L'USUARI]"

# (what the model wrote, what is stored)
DROPPED = [
    (f"Sí, el teu nom és Jordi.\n\nFont: {LABEL}", "Sí, el teu nom és Jordi."),
    (f"Sí, el teu nom és Jordi. Font: {LABEL}", "Sí, el teu nom és Jordi."),
    (f"Sí.\n- Font: {LABEL}", "Sí."),
    (f"Sí.\n> Font: {LABEL}\n\nI a més, una altra cosa.", "Sí.\n\nI a més, una altra cosa."),
    (f"Sí.\nFont:\n{LABEL}", "Sí."),
    (f"Sí.\n**Fonts:**\n- {LABEL}\n- [DOCUMENTACIO TECNICA]", "Sí."),
    (f"Sí.\n\n**Fonts:** {LABEL} i [DOCUMENTACIO TECNICA]\n", "Sí."),
    ("Sí.\nFuente: [DOCUMENTACION TECNICA]", "Sí."),
    ("Yes.\nSources: [USER MEMORY], [SYSTEM DOCUMENTATION]", "Yes."),
    (f"Et dius Jordi (Font: {LABEL}).", "Et dius Jordi ."),
    (f"(Font: {LABEL}) Et dius Jordi.", "Et dius Jordi."),
    # #1102: the header of a recalled item, copied.
    ("[Font: personal_memory]\nEt dius Jordi.", "Et dius Jordi."),
    ("[Font: manual.pdf] diu que sí.", "diu que sí."),
    # A hold that gives way at a line break: what follows is read again, and
    # the caption that starts there is still found.
    (f"Sí.\nFont\nFont: {LABEL}", "Sí.\nFont"),
    (f"Sí.\n**Fonts:**\n1. {LABEL}\n2. [DOCUMENTACIO TECNICA]", "Sí."),
    (f"Sí.\n### Fonts:\n- {LABEL}", "Sí."),
    (f"Sí.\nFont: «{LABEL}»", "Sí."),
    ("Segons [Font: Informe_anual_2024_Departament_Comercial_v3.pdf], sí.", "Segons , sí."),
]

KEPT = [
    "Font: m'ho vas dir tu.",
    "Fonts:\n- Viquipèdia\n- BBC",
    "Sources: [1] [2]",
    "La Terra és rodona [Font: Wikipedia].",
    "Sobre el sol (i la lluna) parlem.",
    "La font de la plaça raja (font: l'ajuntament).",
    "font: 12px; source: x",
    # A caption with no label is the model's own sentence, even at the end.
    "La resposta té dues fonts:",
    "Font: 2024, informe anual.",
    "Fonts:\n1. Viquipèdia\n2. BBC",
    "Fa sol. Seguim.\nSegona línia",
]


def _live(text: str, step: int, *, memory: bool = False) -> str:
    f = TagStreamFilter(memory=memory, labels=True)
    return "".join(f.feed(text[i:i + step]) for i in range(0, len(text), step)) + f.flush()


# ── stored ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reply, stored", DROPPED)
def test_a_caption_that_only_held_labels_is_not_stored(reply, stored):
    assert clean_model_text(reply) == stored


@pytest.mark.parametrize("reply", KEPT)
def test_a_caption_in_words_a_list_heading_or_a_citation_is_stored(reply):
    assert clean_model_text(reply) == reply


def test_a_memory_tag_inside_a_dropped_caption_is_kept():
    """The web client reads it to paint the "saved" badge."""
    assert clean_model_text("Font: [USER MEMORY] [MEM_SAVE: es diu Jordi]") == "[MEM_SAVE: es diu Jordi]"


def test_the_spanish_document_labels_are_labels():
    """chat_rag.py sends DOCUMENTACION TECNICA / DEL SISTEMA — with the N the
    pattern never had."""
    assert clean_model_text("Hola [DOCUMENTACION TECNICA] [DOCUMENTACIÓN DEL SISTEMA] adiós") == "Hola   adiós"


# ── live ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reply, stored", DROPPED)
@pytest.mark.parametrize("step", [1, 2, 5, 1000])
def test_the_stream_shows_what_is_stored(reply, stored, step):
    assert _live(reply, step).strip() == stored


@pytest.mark.parametrize("reply", KEPT)
@pytest.mark.parametrize("step", [1, 3, 1000])
def test_the_stream_leaves_prose_as_it_is(reply, step):
    assert _live(reply, step) == reply


def test_the_stream_shows_the_answer_before_the_caption():
    f = TagStreamFilter(memory=False, labels=True)
    assert f.feed("Sí, el teu nom és Jordi.\n") == "Sí, el teu nom és Jordi.\n"


def test_any_chunking_gives_the_same_text():
    """Cut anywhere, fed in pieces of any size: one result. Random replies
    built from the shapes above, prose, labels, tags and brackets."""
    atoms = ["Font:", "Fonts:", "**Fuente:**", "Sources:", " ", "\n", "- ", "> ", "(", ")", ".", ",", " i ",
             LABEL, "[USER MEMORY]", "[DOCUMENTACION TECNICA]", "[MEM_SAVE: x]", "[1]", "[Font: personal_memory]",
             "Sí", "font", "la font", "m'ho vas dir", "Jordi", "és", "*", "_"]
    rnd = random.Random(1124)
    for _ in range(600):
        text = "".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 14)))
        whole = _live(text, 10_000, memory=True)
        for step in (1, 2, 3, 7):
            assert _live(text, step, memory=True) == whole, (text, step)


def test_prose_without_a_caption_word_is_never_changed():
    atoms = ["Hola", " ", "\n", "- ", "(", ")", ".", ":", " i ", "[1]", "món", "**", "és", "sol", "a:b"]
    rnd = random.Random(2411)
    for _ in range(400):
        text = "".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 16)))
        assert _live(text, 1) == text, text


async def test_what_the_filter_holds_reaches_the_screen_when_the_engine_fails():
    # Deferred: core.turn.stream imported first closes an import cycle through
    # core.endpoints (policy.py imports it back) — pre-existing, not this test's.
    from core.turn.stream import Delta, Failed, StreamFlags, engine_events

    async def gen():
        yield {"message": {"content": "Hola.\nFo"}}
        raise RuntimeError("engine died")

    events = [ev async for ev in engine_events(gen(), "qwen3", StreamFlags())]
    shown = "".join("".join(e.wire) for e in events if isinstance(e, Delta))
    assert shown == "Hola.\nFo"
    assert isinstance(events[-1], Failed)


# ── both doors ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_web_wire_has_no_caption():
    wire, _h, _e = await _wire([_msg(c) for c in ["Sí, el teu nom és Jordi. Fo", "nt: [MEMORIA DE L'USU", "ARI]"]], None)
    assert "Sí, el teu nom és Jordi." in wire
    assert "Font" not in wire and "MEMORIA" not in wire


def test_v1_has_no_caption(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "test-chat-key-9999")
    status, lines = _stream_v1(["Yes, you are Jordi.\n\nSour", "ces: [USER MEM", "ORY]"])
    text = _content(lines)
    assert status == 200
    assert "Yes, you are Jordi." in text
    assert "Sources" not in text and "USER MEMORY" not in text


# ── the legend no longer asks for it ────────────────────────────────────────

@pytest.mark.parametrize("lang", ["ca", "es", "en"])
def test_the_legend_does_not_ask_to_cite_or_spell_a_caption(lang):
    legend = _RAG_LEGEND[lang].lower()
    for word in ("cita", "cite", "font:", "fonts:", "fuente:", "fuentes:", "source:", "sources:"):
        assert word not in legend, word
