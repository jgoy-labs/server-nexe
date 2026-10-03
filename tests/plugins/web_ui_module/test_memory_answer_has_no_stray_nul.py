"""Review 04/10 (#1139): the web reads a sentinel by the parity of NULs — every
\\x00 on its wire belongs to one. A memory command's answer is rendered by
`render_intent_for_ui`, which the stream's guard never sees, and its text can
echo what the user wrote. A stray NUL there held everything after it, and the
list of saved facts showed only its first line."""
from core.memory_facts.intents import IntentOutcome
from plugins.web_ui_module.api.wire import render_intent_for_ui


def test_a_nul_in_the_answer_text_does_not_reach_the_wire():
    rendered = render_intent_for_ui(IntentOutcome(kind="list", text="1. gat\x00\n2. gos\n3. peix"))
    body = rendered.split("\x00[MODEL:nexe-system]\x00", 1)[1]
    assert body == "1. gat\n2. gos\n3. peix"
    assert rendered.count("\x00") == 2


def test_a_nul_in_a_forgotten_fact_does_not_reach_the_wire():
    rendered = render_intent_for_ui(IntentOutcome(kind="delete", text="Fet.", mem_deleted=1,
                                                  deleted_facts=["em dic\x00 Pere"]))
    assert "[DEL:1:em dic Pere]" in rendered
    assert rendered.count("\x00") % 2 == 0
