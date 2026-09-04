"""
────────────────────────────────────
Server Nexe
Location: tests/test_1019_readme_counts_agree.py
Description: The READMEs' own numbers must agree with each other, and with
             the CI they describe (#1019).

             There are THREE of them — README.md, README-ca.md, README-es.md —
             and each states a test count in three places (the intro, "Built to
             Grow", and "## Testing") plus a coverage figure in two. All nine
             claims said 7694 / ~85% from 2026-07-04, long after the suite had
             grown past it, and all three "## Testing" paragraphs claimed CI ran
             the full suite on every push while the `tests` job deselects five
             markers.

             The translations are the reason this gate reads all three rather
             than one: the English file was corrected first and the other two
             were left saying the old number and the false sentence — which is a
             worse state than before, because now the documents disagree with
             each other as well as with the code.

             What this gate can check, and what it deliberately cannot:

             * It CANNOT compare the published number against the real size of
               the suite. Counting the suite from inside the suite means
               re-invoking pytest in a subprocess — ~80 s and recursive. Doing
               it properly needs a measured, versioned artefact in the shape of
               scripts/complexity_baseline.json, plus a script and a rule for
               who regenerates it. That is infrastructure of its own; the
               Director filed it separately rather than smuggle it in here.

             * It CAN catch the failure mode this README actually has, which is
               not stating a wrong number — it is updating one of the three
               copies and leaving the other two behind. That check needs no
               knowledge of the right answer, so it works from today.

             * It CAN tie the two claims that DO have a source of truth in the
               repo to that source: the advertised coverage against the CI's
               own --cov-fail-under, and the "what CI runs" sentence against the
               marker filter of the `tests` job.

             Note on shape: nothing here is parametrized — not over the three
             files and not over data read from ci.yml. Two reasons, and the
             second is the one that settles it.

             First, arithmetic: a parametrized test grows or shrinks the suite
             when its data changes, and the number this very file guards IS the
             size of the suite. Parametrizing over the READMEs would take this
             file from 4 tests to 12, which would change the correct answer in
             the nine lines it checks. A gate that moves the number by measuring
             it is a gate that cannot be right.

             Second, and more important: the claim is that all nine lines agree
             with EACH OTHER. That is inherently cross-file. A per-file
             parametrization cannot express it — it would check each document
             for internal consistency and still pass with three documents
             contradicting one another, which is exactly the state this ALERT
             was raised about. The loops are inside the tests because the
             assertion is about the set, not about any one member of it.

             Diagnosis does not suffer for it: every failure names the file and
             the line number of each disagreeing claim.

             Pure text parse — no network, no subprocess, no app boot.
────────────────────────────────────
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"

# All three are published; all three carry the same claims.
READMES = ("README.md", "README-ca.md", "README-es.md")

# Must START with a digit: `[\d,]+` alone also matches the bare comma in
# "code, tests, audits" of the intro paragraph and invents a phantom claim.
TESTS_CLAIM = re.compile(r"(\d[\d,]*)\s+tests\b")
# `coverage` in English, `cobertura` in the two translations. Without the second
# alternative this gate reads the English file and silently finds nothing to
# check in the other two — a green light over the exact gap it exists to close.
COVERAGE_CLAIM = re.compile(r"~?\s*(\d+)\s*%\s*(?:code\s+)?(?:coverage|cobertura)")


def _text(readme: str) -> str:
    path = REPO / readme
    assert path.exists(), f"{readme} is gone — the gate is guarding a file that moved"
    return path.read_text(encoding="utf-8")


def _claims(pattern: re.Pattern) -> dict[int, list[str]]:
    """Every match of `pattern` across the three READMEs, value -> where.

    Keyed by the claimed number so a disagreement reads as "this many said X,
    this many said Y", with file:line for each.
    """
    found: dict[int, list[str]] = {}
    for readme in READMES:
        for number, line in enumerate(_text(readme).splitlines(), 1):
            for match in pattern.finditer(line):
                value = int(match.group(1).replace(",", ""))
                found.setdefault(value, []).append(f"{readme}:{number}")
    return found


def _testing_paragraph(readme: str) -> str:
    """The prose of '## Testing', up to its first code block.

    Scoped to the prose on purpose: the bash example below it names some
    markers already, and a check that counted those would pass without the
    sentence ever telling the reader anything.
    """
    match = re.search(r"^## Testing\s*\n(.*?)(?=^```)", _text(readme), re.MULTILINE | re.DOTALL)
    assert match, f"{readme} has no '## Testing' section with prose before its example"
    return match.group(1)


def _ci_unit_test_step() -> str:
    """The `run:` of the step that executes the unit suite in the `tests` job."""
    jobs = (yaml.safe_load(CI.read_text(encoding="utf-8")) or {}).get("jobs") or {}
    steps = (jobs.get("tests") or {}).get("steps") or []
    for step in steps:
        run = str(step.get("run", ""))
        if "pytest tests" in run:
            return run
    raise AssertionError("the `tests` job of ci.yml no longer runs `pytest tests`")


def test_every_readme_line_claims_the_same_test_count() -> None:
    """Nine copies of one number is nine chances to update only some of them.

    Which is how we got here twice: 7694 stood for two months while three
    paragraphs agreed with each other, and then the English file was corrected
    alone and the two translations were left behind.
    """
    claims = _claims(TESTS_CLAIM)
    assert claims, "no README states a test count any more"
    assert len(claims) == 1, (
        "the READMEs state different test counts: "
        + "; ".join(f"{value} at {sorted(where)}" for value, where in sorted(claims.items()))
    )


def test_every_readme_line_claims_the_same_coverage() -> None:
    claims = _claims(COVERAGE_CLAIM)
    assert claims, "no README states a coverage figure any more"
    assert len(claims) == 1, (
        "the READMEs state different coverage figures: "
        + "; ".join(f"{value}% at {sorted(where)}" for value, where in sorted(claims.items()))
    )


def test_the_advertised_coverage_is_not_below_what_ci_enforces() -> None:
    """One of the two numbers has a source of truth in the repo: the floor the
    CI already fails under. Advertising less than that is a claim the pipeline
    contradicts on every run."""
    floor = re.search(r"--cov-fail-under=(\d+)", CI.read_text(encoding="utf-8"))
    assert floor, "ci.yml no longer pins --cov-fail-under"
    advertised = _claims(COVERAGE_CLAIM)
    assert advertised, "no README states a coverage figure"
    below = {value: sorted(where) for value, where in advertised.items() if value < int(floor.group(1))}
    assert not below, (
        f"CI fails under {floor.group(1)}% but the READMEs advertise less: {below}"
    )


def test_the_testing_paragraph_says_which_markers_ci_leaves_out() -> None:
    """"CI runs the full suite on every push" was false: the `tests` job
    deselects five markers, so the number next to that sentence is not the
    number of tests the sentence implies.

    The markers are read out of ci.yml rather than listed here, so tightening
    or loosening the filter without touching the README fails.
    """
    excluded = set(re.findall(r"\bnot\s+([A-Za-z_][A-Za-z0-9_]*)", _ci_unit_test_step()))
    assert excluded, "the CI unit-test step no longer deselects any marker"
    gaps = {}
    for readme in READMES:
        paragraph = _testing_paragraph(readme)
        missing = sorted(marker for marker in excluded if marker not in paragraph)
        if missing:
            gaps[readme] = missing
    assert not gaps, (
        f"these '## Testing' paragraphs do not mention markers the CI `tests` job "
        f"deselects: {gaps} (it runs with: not {', not '.join(sorted(excluded))}). "
        "A reader adding up the number and the sentence gets a suite that does "
        "not exist. The marker names stay in English in every language: they are "
        "pytest identifiers, not prose."
    )
