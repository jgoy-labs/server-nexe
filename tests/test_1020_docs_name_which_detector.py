"""
────────────────────────────────────
Server Nexe
Location: tests/test_1020_docs_name_which_detector.py
Description: Every pattern count in the public docs must name the detector it
             counts, and match it (#1020).

             README.md said "49 jailbreak patterns" and SECURITY.md said
             "11 pattern speed-bump detector". Both numbers were true and both
             were about a DIFFERENT detector, and neither document said which:

               plugins/security/sanitizer/core/patterns.py  49 jailbreak
                                                            18 prompt-injection
               core/security/input_sanitizers.py            11 speed-bump

             A reader comparing the two documents can only conclude that one of
             them is wrong. So each claim now carries the module path it counts,
             and this gate ties the two together: the number lives next to its
             source of truth, and a pattern added to either list without a doc
             edit fails here.

             That is the whole value of the finding. Rewriting the sentences
             without a gate buys about two months — #1019 exists because this
             README already carries counts nobody re-measured.

             Sibling gate: tests/test_docs_honest_claims.py
             ::test_security_pattern_count_accurate covers the same counts in
             plugins/security/readme/README.md. This file covers the two
             top-level documents and, unlike that one, also checks that the
             numbers cannot be swapped between detectors.

             Pure text + AST parse — no network, no app boot.
────────────────────────────────────
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SANITIZER_PATTERNS = "plugins/security/sanitizer/core/patterns.py"
CORE_SANITIZERS = "core/security/input_sanitizers.py"
CORE_INJECTION = "core/security/injection_detectors.py"


def _count_list(module_rel: str, name: str) -> int:
    """Length of a module-level list literal, read with AST.

    AST rather than an import so the count is of what is WRITTEN in the file:
    a gate that imports would happily count a list some other module had
    monkeypatched, and would drag the whole plugin import chain in with it.
    """
    tree = ast.parse((REPO / module_rel).read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                assert isinstance(node.value, ast.List), (
                    f"{module_rel}::{name} is no longer a list literal — this "
                    "gate counts elements, so it must be told how to count now"
                )
                return len(node.value.elts)
    raise AssertionError(f"{module_rel} has no module-level {name!r}")


def _count_detector_functions(module_rel: str) -> int:
    tree = ast.parse((REPO / module_rel).read_text(encoding="utf-8"))
    return sum(
        1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("detect_")
    )


@dataclass(frozen=True)
class Detector:
    label: str
    module: str
    count: int


def _detectors() -> dict[str, Detector]:
    return {
        "sanitizer-jailbreak": Detector(
            "the sanitizer plugin's jailbreak patterns",
            SANITIZER_PATTERNS,
            _count_list(SANITIZER_PATTERNS, "JAILBREAK_PATTERNS"),
        ),
        "sanitizer-injection": Detector(
            "the sanitizer plugin's prompt-injection patterns",
            SANITIZER_PATTERNS,
            _count_list(SANITIZER_PATTERNS, "INJECTION_PATTERNS"),
        ),
        "core-speedbump": Detector(
            "the /ui/chat regex speed-bump",
            CORE_SANITIZERS,
            _count_list(CORE_SANITIZERS, "_JAILBREAK_PATTERNS"),
        ),
    }


# doc -> anchor path -> (detectors whose count MUST be on that line)
CLAIMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("README.md", SANITIZER_PATTERNS, ("sanitizer-jailbreak", "sanitizer-injection")),
    ("SECURITY.md", SANITIZER_PATTERNS, ("sanitizer-jailbreak", "sanitizer-injection")),
    ("SECURITY.md", CORE_SANITIZERS, ("core-speedbump",)),
)


def _anchored_line(doc: str, anchor: str) -> str:
    lines = [ln for ln in (REPO / doc).read_text(encoding="utf-8").splitlines() if anchor in ln]
    assert len(lines) == 1, (
        f"{doc} mentions {anchor} on {len(lines)} lines; this gate reads the "
        "count off the SAME line as the path, so exactly one claim is expected "
        f"(found: {lines})"
    )
    return lines[0]


def _integers(line: str) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", line)}


def test_the_three_counts_are_distinct_so_this_gate_can_tell_them_apart() -> None:
    """The premise of every other test here.

    The swap check below works by asserting that one detector's number is
    absent from another's line. If two detectors ever hold the same count that
    check silently stops discriminating — better to fail here, loudly, and make
    someone rewrite the gate than to keep a green light that means nothing.
    """
    counts = [d.count for d in _detectors().values()]
    assert len(set(counts)) == len(counts), (
        f"two detectors now have the same pattern count ({counts}); the "
        "cross-check in test_a_documented_count_cannot_belong_to_another "
        "cannot distinguish them any more"
    )


@pytest.mark.parametrize("doc,anchor,expected", CLAIMS, ids=lambda v: str(v)[:40])
def test_each_documented_count_matches_the_code_it_names(doc, anchor, expected) -> None:
    """The number and its source of truth live on the same line, and agree."""
    line = _anchored_line(doc, anchor)
    found = _integers(line)
    detectors = _detectors()
    for key in expected:
        detector = detectors[key]
        assert detector.count in found, (
            f"{doc} claims {sorted(found)} next to {anchor}, but {detector.label} "
            f"has {detector.count} entries today. Someone changed the list and "
            f"not the document.\n    {line.strip()}"
        )


@pytest.mark.parametrize("doc,anchor,expected", CLAIMS, ids=lambda v: str(v)[:40])
def test_a_documented_count_cannot_belong_to_another_detector(doc, anchor, expected) -> None:
    """#1020 itself: the two counts were true and about different detectors.

    Having the right number is not enough — it has to be next to the right
    path. A line that cites the sanitizer module while carrying the
    speed-bump's count is exactly the confusion this finding is about.
    """
    line = _anchored_line(doc, anchor)
    found = _integers(line)
    for key, detector in _detectors().items():
        if key in expected:
            continue
        assert detector.count not in found, (
            f"{doc}, on the line that cites {anchor}, carries {detector.count} — "
            f"which is the count of {detector.label}, in {detector.module}. That "
            "is #1020: a true number filed under the wrong detector.\n"
            f"    {line.strip()}"
        )


@pytest.mark.parametrize("doc", ["README.md", "SECURITY.md"])
def test_every_injection_detector_count_in_the_docs_is_the_real_one(doc) -> None:
    """The other number both documents repeat: "N injection detectors".

    Three copies across the two files (README twice, SECURITY once), so it is
    checked wherever the phrase appears rather than at one blessed line.
    """
    real = _count_detector_functions(CORE_INJECTION)
    assert real, f"{CORE_INJECTION} defines no detect_* function"
    claims = re.findall(r"(\d+)\s+injection detectors", (REPO / doc).read_text(encoding="utf-8"))
    assert claims, f"{doc} no longer states how many injection detectors there are"
    wrong = sorted({int(c) for c in claims} - {real})
    assert not wrong, (
        f"{doc} says {wrong} injection detectors; {CORE_INJECTION} defines "
        f"{real} detect_* functions"
    )
