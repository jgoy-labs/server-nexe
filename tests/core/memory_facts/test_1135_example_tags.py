"""#1135 — a memory tag copied from an example in the instructions is not a fact.

Live 03/10 (MLX, Qwen3.5-9B): asked how it works, the model explained its
instructions and quoted the tags — `[MEM_SAVE: ...]`, `[MEM_DELETE: ...]`. The
server read the quote as a real request: «...» armed the delete dialog, and the
0.20 delete search offered whichever memory entry came closest. Measured the
same day: every delete example in personality/server.toml would have armed it,
one of them `L'usuari es diu ‹nom›` — the user's own name — and five save
examples («descripció completa», «nombre»…) would have been stored, unasked.

The independent review of the first fix (03/10) found the rule only stopped
the LITERAL examples: «L'usuari es diu ...», «el fet», «the fact» still passed,
and «08001» or «Python > Java» were refused. So the variants here are
GENERATED from every example in server.toml (each slot left empty, as «...»,
as X, as its own word, decorated), and the real facts include the ones the
first rule refused. An example added to the prompt is covered by the test the
day it is added.
"""

import re
import tomllib
from pathlib import Path

import pytest

from core.memory_facts import extract
from core.memory_facts.extract import extract_memory_tags, is_example_not_fact

_PERSONA = Path(__file__).resolve().parents[3] / "personality" / "server.toml"
_SLOT_RE = re.compile(r"‹([^›]*)›|<([^<>]*)>")


def _prompts() -> list[str]:
    prompts = tomllib.loads(_PERSONA.read_text(encoding="utf-8"))["personality"]["prompt"]
    return [v for k, v in prompts.items() if k != "description" and isinstance(v, str)]


def _tag_examples(kind: str) -> list[str]:
    found = set()
    for prompt in _prompts():
        found.update(m.strip() for m in re.findall(rf"\[{kind}:\s*([^\[\]\n]*)\]", prompt))
    return sorted(found)


def _confirmation_placeholders() -> list[str]:
    """The `'[fet concret]'` of «Vols que esborri '[fet concret]'?» — the words
    a model fills a tag with when it copies the question's shape."""
    found = set()
    for prompt in _prompts():
        found.update(re.findall(r"\[([a-zà-ÿ ]{3,40})\]", prompt))
    return sorted(found)


_FILLERS = [
    lambda w: "...", lambda w: "…", lambda w: "X", lambda w: w, lambda w: w.upper(),
    lambda w: "{" + w + "}", lambda w: "«" + w + "»", lambda w: "(" + w + ")", lambda w: "",
]


def _unfilled_variants() -> list[str]:
    """Each slotted example with its slots filled the ways a model quotes them."""
    out = set()
    for example in _tag_examples("MEM_SAVE") + _tag_examples("MEM_DELETE"):
        if not _SLOT_RE.search(example):
            continue
        for fill in _FILLERS:
            text = _SLOT_RE.sub(lambda m, fill=fill: fill(m.group(1) or m.group(2)), example)
            out.add(" ".join(text.split()))
    return sorted(out)


DELETE_EXAMPLES = _tag_examples("MEM_DELETE")
SAVE_EXAMPLES = _tag_examples("MEM_SAVE")
PLACEHOLDERS = _confirmation_placeholders()
VARIANTS = _unfilled_variants()

#: Not derivable from the prompt: the generic nouns, as a model rephrases them.
REPHRASED = ["el fet", "descripció", "the fact", "fact to delete", "el fet concret",
             "el fet complet", "nom", "descripción", "el hecho", "descripció del fet concret"]

#: Real facts — the last block are the ones the first rule refused (review 03/10).
REAL_FACTS = [
    "El meu peix es diu Bombolla", "el nom del gat", "L'usuari té 52 anys",
    "l'usuari treballa a Helefante", "User lives in Girona", "L'usuari es diu Jordi",
    "L'usuari es diu Jordi i treballa a Helefante", "El usuario vive en Girona",
    "L'usuari vol canviar de nom", "Full stack developer a Girona",
    "08001", "12/05/1990", "Python > Java", "l'usuari té <3 gats", "Barcelona -> Girona",
    "l'usuari diu que hola...",
]


def test_the_examples_are_really_read_from_the_prompt():
    # Not vacuous: an empty or renamed prompt section must not make the
    # parametrised tests below pass by having nothing to check.
    assert "descripció del fet" in DELETE_EXAMPLES
    assert "L'usuari es diu ‹nom›" in DELETE_EXAMPLES
    assert {"descripció completa", "nombre", "hecho", "full description"} <= set(SAVE_EXAMPLES)
    assert {"fet concret", "hecho concreto", "specific fact"} <= set(PLACEHOLDERS)
    assert {"L'usuari es diu ...", "L'usuari es diu nom", "User is X years old"} <= set(VARIANTS)


def test_the_rule_reads_the_same_examples():
    # The production rule derives its skeletons from the same file: one per
    # slotted example (shared ones collapse).
    slotted = {e for e in DELETE_EXAMPLES + SAVE_EXAMPLES if _SLOT_RE.search(e)}
    assert 0 < len(extract._example_skeletons()) <= len(slotted)


def test_the_live_case_arms_nothing():
    reply = (
        "Si l'usuari em diu un fet nou, el meu sistema detecta el tag `[MEM_SAVE: ...]` i el guarda. "
        "Si l'usuari demana oblidar un fet, primer li demano confirmació. Només si confirma, "
        "executo l'acció `[MEM_DELETE: ...]` al torn següent."
    )
    clean, facts, deletes = extract_memory_tags(reply, user_input="explica'm el teu funcionament")
    assert deletes == []
    assert facts == []
    assert "MEM_DELETE" not in clean and "MEM_SAVE" not in clean


@pytest.mark.parametrize("example", DELETE_EXAMPLES + PLACEHOLDERS + VARIANTS + REPHRASED)
def test_a_delete_example_or_its_variant_arms_nothing(example):
    _, _, deletes = extract_memory_tags(f"Així funciono: [MEM_DELETE: {example}]")
    assert deletes == []


@pytest.mark.parametrize("example", SAVE_EXAMPLES + VARIANTS + REPHRASED)
def test_a_save_example_or_its_variant_is_not_stored(example):
    # Saves need no confirmation (#696): a quoted example went straight to memory.
    _, facts, _ = extract_memory_tags(f"Així funciono: [MEM_SAVE: {example}]")
    assert facts == []


@pytest.mark.parametrize("content", ["...", "…", "-", "?!", "<fet>", "‹nom›", "[nom]", "  .  "])
def test_a_content_with_nothing_to_name_or_a_slot_names_no_fact(content):
    assert is_example_not_fact(content)


@pytest.mark.parametrize("content", ["L'usuari viu a {lloc}", "El usuario vive en «lugar»",
                                     "User moved to (place) last year"])
def test_a_decorated_slot_word_in_a_sentence_of_its_own_names_no_fact(content):
    # Not one of the prompt's skeletons («viu a» is in none), not all template:
    # only the decoration around the slot word says it is one.
    assert is_example_not_fact(content)


@pytest.mark.parametrize("fact", REAL_FACTS)
def test_a_real_fact_is_a_fact(fact):
    assert not is_example_not_fact(fact)


@pytest.mark.parametrize("fact", [f for f in REAL_FACTS if len(f) >= 3])
def test_a_real_fact_still_arms_a_delete(fact):
    _, _, deletes = extract_memory_tags(f"D'acord. [MEM_DELETE: {fact}]")
    assert deletes == [fact]


@pytest.mark.parametrize("fact", ["L'usuari es diu Jordi", "L'usuari té 52 anys", "El usuario vive en Girona",
                                  "L'usuari vol canviar de nom"])
def test_a_real_fact_is_still_stored(fact):
    _, facts, _ = extract_memory_tags(f"Ho recordaré. [MEM_SAVE: {fact}]")
    assert facts == [fact]


def test_an_unreadable_prompt_keeps_the_generic_rules(monkeypatch, caplog):
    def _broken(_text):
        raise tomllib.TOMLDecodeError("broken", "", 0)
    monkeypatch.setattr(extract.tomllib, "loads", _broken)
    extract._example_skeletons.cache_clear()
    try:
        assert extract._example_skeletons() == ()
        assert "cannot read the prompt's examples" in caplog.text
        assert is_example_not_fact("L'usuari es diu ...")  # the lone «...» still names nothing
        assert not is_example_not_fact("L'usuari es diu Jordi")
    finally:
        monkeypatch.undo()
        extract._example_skeletons.cache_clear()
