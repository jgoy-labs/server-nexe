"""B7 r4: public docs match the reality of the code.

Each test verifies empirically that one of the false claims detected by
audit F16c (and claim 8 added by auditor B6) has been corrected.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_v1_endpoint_status_consistency():
    """B7: statuses declared in v1.py match empirical reality.

    Endpoints that return 501 (`embeddings/encode`, `rag/search`,
    `documents/`) CANNOT declare `status: "implemented"` in the v1 registry.
    """
    text = (REPO / "core/endpoints/v1.py").read_text(encoding="utf-8")
    for endpoint in ("embeddings", "rag", "documents"):
        block = re.search(
            rf'"{endpoint}":\s*\{{[^}}]*"status":\s*"([^"]+)"',
            text,
        )
        assert block, f"Block for {endpoint!r} not found in v1.py"
        status = block.group(1)
        assert status != "implemented", (
            f"{endpoint} status = {status!r} but the endpoint returns 501"
        )


def test_v1_version_string_dynamic():
    """B7: the version string in v1.py is NOT '0.9.0' hardcoded."""
    text = (REPO / "core/endpoints/v1.py").read_text(encoding="utf-8")
    assert "Nexe 0.9.0 Versioned API" not in text, (
        "Hardcoded version 0.9.0 — use dynamic __version__"
    )


def test_changelog_has_1_0_2_entry():
    """B7: CHANGELOG has an entry for 1.0.2-beta between 1.0.1 and 1.0.3."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.0.2-beta]" in text, (
        "Entry [1.0.2-beta] absent from CHANGELOG"
    )


@pytest.mark.parametrize(
    "plugin_readme,removed_ep",
    [
        ("plugins/mlx_module/readme/README.md", "/mlx/chat"),
        ("plugins/llama_cpp_module/readme/README.md", "/llama-cpp/chat"),
        ("plugins/ollama_module/readme/README.md", "/ollama/api/chat"),
    ],
)
def test_plugin_readme_marks_chat_as_removed(plugin_readme, removed_ep):
    """B7: READMEs document that direct /chat is removed in v1.0.3-beta."""
    text = (REPO / plugin_readme).read_text(encoding="utf-8")
    assert (
        "Removed" in text
        or "removed" in text
        or f"~~{removed_ep}~~" in text
    ), f"{plugin_readme} does not document that {removed_ep} is removed (returns 403)"


def test_security_pattern_count_accurate():
    """B7: the number of patterns in the README matches reality."""
    text = (REPO / "plugins/security/readme/README.md").read_text(encoding="utf-8")
    assert "69 patrons" not in text, (
        "README says 69 patterns; reality is 47+18=65"
    )

    from plugins.security.sanitizer.core.patterns import (
        INJECTION_PATTERNS,
        JAILBREAK_PATTERNS,
    )
    n_jailbreak = len(JAILBREAK_PATTERNS)
    n_injection = len(INJECTION_PATTERNS)
    assert (
        str(n_jailbreak) in text
        or f"{n_jailbreak}+{n_injection}" in text
        or f"{n_jailbreak} + {n_injection}" in text
    ), (
        f"README does not match reality "
        f"({n_jailbreak} jailbreak + {n_injection} injection)"
    )


def test_no_phantom_versions_in_v1_py():
    """B7 (regression): no version string ≠ __version__ in v1.py."""
    text = (REPO / "core/endpoints/v1.py").read_text(encoding="utf-8")
    phantom = re.findall(r"\bNexe\s+\d+\.\d+\.\d+", text)
    assert not phantom, f"Phantom version strings: {phantom}"


def test_filter_rag_injection_docstring_no_overclaim_brackets():
    """C23 resolved: NFKC does not normalise ⟦⟧ — but _NON_NFKC_BRACKET_MAP does.

    Verifies that the code contains the explicit substitution table for
    CJK and mathematical brackets (C23 v1.0.4), and that the gap no longer appears in 'Known gaps'.
    """
    import unicodedata

    # NFKC still does not normalise ⟦⟧ (Python invariant, not our code)
    assert unicodedata.normalize("NFKC", "⟦") == "⟦"
    assert unicodedata.normalize("NFKC", "⟧") == "⟧"

    text = (REPO / "core/endpoints/chat_sanitization.py").read_text(encoding="utf-8")

    # C23: the explicit substitution table must exist in the module
    assert "_NON_NFKC_BRACKET_MAP" in text, (
        "_NON_NFKC_BRACKET_MAP not found — C23 not implemented"
    )
    assert "「" in text and "⟦" in text, (
        "CJK/mathematical brackets not in substitution table"
    )

    # The CJK/mathematical gap should NO longer appear as pending in Known gaps
    known_gaps_section = re.search(
        r"Known gaps:.*?(?=Args:|Returns:|\"\"\")",
        text,
        re.DOTALL,
    )
    if known_gaps_section:
        gap_text = known_gaps_section.group(0)
        assert "CJK" not in gap_text, (
            "C23 resolved but docstring still lists it as a gap"
        )
