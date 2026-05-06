"""B7 r4: docs públics coincideixen amb la realitat del codi.

Cada test verifica empíricament que un dels claims falsos detectats per
auditoria F16c (i el claim 8 afegit per auditor B6) ha estat corregit.

Origen: nat/dev/server-nexe/diari/prompts/onada-2-blockers-r4/B7-docs-claims-falsos.md
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_v1_endpoint_status_consistency():
    """B7: status declarats a v1.py coincideixen amb realitat empírica.

    Endpoints que retornen 501 (`embeddings/encode`, `rag/search`,
    `documents/`) NO poden declarar `status: "implemented"` al registre v1.
    """
    text = (REPO / "core/endpoints/v1.py").read_text(encoding="utf-8")
    for endpoint in ("embeddings", "rag", "documents"):
        block = re.search(
            rf'"{endpoint}":\s*\{{[^}}]*"status":\s*"([^"]+)"',
            text,
        )
        assert block, f"No s'ha trobat el bloc de {endpoint!r} a v1.py"
        status = block.group(1)
        assert status != "implemented", (
            f"{endpoint} status = {status!r} però l'endpoint retorna 501"
        )


def test_v1_version_string_dynamic():
    """B7: la string de versió a v1.py NO és '0.9.0' hardcoded."""
    text = (REPO / "core/endpoints/v1.py").read_text(encoding="utf-8")
    assert "Nexe 0.9.0 Versioned API" not in text, (
        "Hardcoded version 0.9.0 — usar __version__ dinàmic"
    )


def test_changelog_has_1_0_2_entry():
    """B7: CHANGELOG té entry per 1.0.2-beta entre 1.0.1 i 1.0.3."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.0.2-beta]" in text, (
        "Entry [1.0.2-beta] absent al CHANGELOG"
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
    """B7: READMEs documenten que /chat directe està removed v1.0.3-beta."""
    text = (REPO / plugin_readme).read_text(encoding="utf-8")
    assert (
        "Removed" in text
        or "removed" in text
        or f"~~{removed_ep}~~" in text
    ), f"{plugin_readme} no documenta que {removed_ep} està removed (returns 403)"


def test_security_pattern_count_accurate():
    """B7: el nombre de patterns al README coincideix amb la realitat."""
    text = (REPO / "plugins/security/readme/README.md").read_text(encoding="utf-8")
    assert "69 patrons" not in text, (
        "README diu 69 patrons; realitat 47+18=65"
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
        f"README no coincideix amb el real "
        f"({n_jailbreak} jailbreak + {n_injection} injection)"
    )


def test_no_phantom_versions_in_v1_py():
    """B7 (regressió): cap version string ≠ __version__ a v1.py."""
    text = (REPO / "core/endpoints/v1.py").read_text(encoding="utf-8")
    phantom = re.findall(r"\bNexe\s+\d+\.\d+\.\d+", text)
    assert not phantom, f"Phantom version strings: {phantom}"


def test_filter_rag_injection_docstring_no_overclaim_brackets():
    """C23 resolt: NFKC no normalitza ⟦⟧ — però _NON_NFKC_BRACKET_MAP sí.

    Verifica que el codi conté la taula de substitució explícita per a brackets
    CJK i matemàtics (C23 v1.0.4), i que el gap ja no apareix als 'Known gaps'.
    """
    import unicodedata

    # NFKC segueix sense normalitzar ⟦⟧ (invariant de Python, no del nostre codi)
    assert unicodedata.normalize("NFKC", "⟦") == "⟦"
    assert unicodedata.normalize("NFKC", "⟧") == "⟧"

    text = (REPO / "core/endpoints/chat_sanitization.py").read_text(encoding="utf-8")

    # C23: la taula de substitució explícita ha d'existir al mòdul
    assert "_NON_NFKC_BRACKET_MAP" in text, (
        "_NON_NFKC_BRACKET_MAP no trobat — C23 no implementat"
    )
    assert "「" in text and "⟦" in text, (
        "Brackets CJK/matemàtics no a la taula de substitució"
    )

    # El gap CJK/matemàtic ja NO hauria d'aparèixer com a pendent als Known gaps
    known_gaps_section = re.search(
        r"Known gaps:.*?(?=Args:|Returns:|\"\"\")",
        text,
        re.DOTALL,
    )
    if known_gaps_section:
        gap_text = known_gaps_section.group(0)
        assert "CJK" not in gap_text, (
            "C23 resolt però el docstring segueix llistant-lo com a gap"
        )
