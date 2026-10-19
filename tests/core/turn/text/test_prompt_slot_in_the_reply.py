"""MEM-20261016-1: a template slot copied from the prompt's examples
(«el teu nom és ‹nom›») never reaches the reader or the stored reply, but a
memory tag keeps its slot so the extractor still sees it is an example."""
from core.memory_facts.extract import extract_memory_tags
from core.turn.text.clean import clean_full_response, clean_model_text
from core.turn.text.tags import TagStreamFilter


def _stream(chunks, **kw):
    f = TagStreamFilter(**kw)
    return "".join(f.feed(c) for c in chunks) + f.flush()


def test_the_stored_reply_has_no_slot():
    assert clean_model_text("Hola, el teu nom és ‹nom›.") == "Hola, el teu nom és ."


def test_the_stream_drops_the_slot_even_split_across_chunks():
    text = "El teu nom és ‹nom› i prou."
    want = "El teu nom és  i prou."
    assert _stream([text], memory=False) == want
    assert _stream(list(text), memory=False) == want


def test_a_guillemet_that_is_not_a_slot_is_released():
    assert _stream(["a ‹ b\nc"], memory=False) == "a ‹ b\nc"
    assert _stream(["a ‹ sense tancar"], memory=False) == "a ‹ sense tancar"


def test_a_memory_tag_keeps_its_slot_so_the_example_is_still_refused():
    clean, saves, _ = clean_full_response("[MEM_SAVE: L'usuari viu a Girona ‹ciutat›] Ho recordaré.")
    assert saves == []
    assert "‹" not in clean
    # the whole path, streamed one char at a time: the tag is dropped whole
    assert _stream(list("[MEM_SAVE: L'usuari treballa a ‹lloc›] ok"), memory=True) == " ok"
    # labels only (the web UI): the tag stays whole, slot included, for its client
    assert _stream(list("[MEM_SAVE: L'usuari treballa a ‹lloc›] ok"), memory=False) == (
        "[MEM_SAVE: L'usuari treballa a ‹lloc›] ok"
    )
    assert extract_memory_tags("[MEM_SAVE: L'usuari es diu ‹nom›]")[1] == []
