"""#1151 — the cases the web client's `_dropQuotedMemTags` is held to are what the
server's `_drop_quoted_tags` answers (the two are one rule in two languages).
`quoted_tag_span.mjs` runs the same table against the JavaScript."""
import json
from pathlib import Path

from core.memory_facts.extract import _drop_quoted_tags

CASES = json.loads((Path(__file__).parent / "lib" / "quoted_tag_cases.json").read_text(encoding="utf-8"))


def test_the_shared_cases_are_what_the_server_does():
    assert len(CASES) >= 8
    for case in CASES:
        assert _drop_quoted_tags(case["input"]) == case["expected"], case["input"]
    # The table is not all identity: some inputs lose a span, some keep it.
    assert any(c["input"] != c["expected"] for c in CASES)
    assert any(c["input"] == c["expected"] for c in CASES)
