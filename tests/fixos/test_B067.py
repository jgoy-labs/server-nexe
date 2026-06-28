"""
Test fix B067: la recepta de knowledge per al timeout era enganyosa.

Dos defectes corregits:
 1. Apuntava a NEXE_DEFAULT_MAX_TOKENS (limit de SORTIDA, empitjora el timeout)
    en comptes de NEXE_OLLAMA_STREAM_TIMEOUT (el timeout real, default 300s).
 2. Documentava un error "408" que el codi MAI emet: quan Ollama supera el
    stream timeout, httpx llanca ReadTimeout NO capturat -> el handler general
    retorna 500. La fila ha d'alinear-se: 408 -> 500.

A mes, USAGE.md deia "Timeout is 600s" -> corregit a 300s
(default real: core/config.py:529 Field(300.0, ... NEXE_OLLAMA_STREAM_TIMEOUT)).

Test de coherencia acotat (NOMES llegeix els .md del seu univers, EXCLOU
.embeddings/). No fa re-embed.
"""
from pathlib import Path

import pytest

# Arrel del repo: .../server-nexe/tests/fixos/test_B067.py -> parents[2]
_ROOT = Path(__file__).resolve().parents[2]
_KNOWLEDGE = _ROOT / "knowledge"
_LANGS = ("en", "ca", "es")


def _read(rel: str) -> str:
    """Llegeix un fitxer de knowledge. Defensa: mai dins .embeddings/."""
    path = _KNOWLEDGE / rel
    assert ".embeddings" not in path.parts, "El test no ha de tocar .embeddings/"
    return path.read_text(encoding="utf-8")


def _timeout_lines(text: str) -> list[str]:
    """Retorna les linies que parlen de timeout (no les de chunk_size del frontmatter)."""
    out = []
    for line in text.splitlines():
        low = line.lower()
        if "timeout" in low and "chunk_size" not in low:
            out.append(line)
    return out


@pytest.mark.parametrize("lang", _LANGS)
@pytest.mark.parametrize("doc", ("ERRORS.md", "API.md"))
def test_timeout_recipe_points_to_stream_timeout(lang: str, doc: str):
    """Les files de timeout NO han de mencionar la recepta dolenta i SI la bona."""
    text = _read(f"{lang}/{doc}")
    lines = _timeout_lines(text)
    assert lines, f"{lang}/{doc}: no s'ha trobat cap linia de timeout"

    joined = "\n".join(lines)
    assert "NEXE_DEFAULT_MAX_TOKENS" not in joined, (
        f"{lang}/{doc}: la recepta de timeout encara apunta a NEXE_DEFAULT_MAX_TOKENS "
        f"(limit de sortida, empitjora el timeout). Linies: {lines!r}"
    )
    assert "NEXE_OLLAMA_STREAM_TIMEOUT" in joined, (
        f"{lang}/{doc}: la recepta de timeout hauria d'apuntar a "
        f"NEXE_OLLAMA_STREAM_TIMEOUT. Linies: {lines!r}"
    )


@pytest.mark.parametrize("lang", _LANGS)
def test_errors_timeout_status_is_500_not_408(lang: str):
    """La fila de timeout d'ERRORS ha de documentar 500 (el que el servidor emet), no 408."""
    text = _read(f"{lang}/ERRORS.md")
    lines = _timeout_lines(text)
    joined = "\n".join(lines)
    assert "408" not in joined, (
        f"{lang}/ERRORS.md: la fila de timeout encara documenta 408, que el codi "
        f"MAI emet (ReadTimeout no capturat -> 500). Linies: {lines!r}"
    )
    assert "500" in joined, (
        f"{lang}/ERRORS.md: la fila de timeout hauria de documentar 500. Linies: {lines!r}"
    )


@pytest.mark.parametrize("lang", _LANGS)
def test_usage_timeout_is_300_not_600(lang: str):
    """USAGE.md ha de dir 300s (default real), no 600s."""
    text = _read(f"{lang}/USAGE.md")
    lines = _timeout_lines(text)
    joined = "\n".join(lines)
    assert "600" not in joined, (
        f"{lang}/USAGE.md: la linia de timeout encara diu 600 (no existeix cap 600 "
        f"al codi; el default real es 300s). Linies: {lines!r}"
    )
    assert "300" in joined, (
        f"{lang}/USAGE.md: la linia de timeout hauria de dir 300s. Linies: {lines!r}"
    )
