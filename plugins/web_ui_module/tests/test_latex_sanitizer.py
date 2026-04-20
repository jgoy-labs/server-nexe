"""
────────────────────────────────────
Server Nexe
Location: plugins/web_ui_module/tests/test_latex_sanitizer.py
Description: Unit tests for LaTeX → Unicode sanitiser (direct + streaming).
────────────────────────────────────
"""

import pytest

from plugins.web_ui_module.core.latex_sanitizer import (
  latex_to_unicode,
  LatexStreamBuffer,
)


# ── Direct substitution (non-streaming) ──────────────────────────────


@pytest.mark.parametrize("text,expected", [
  # Arrows
  ('"Comoestas" $\\rightarrow$ "Cómo estás?"', '"Comoestas" → "Cómo estás?"'),
  ("value \\to next", "value → next"),
  ("prev \\leftarrow now", "prev ← now"),
  ("A $\\Rightarrow$ B", "A ⇒ B"),
  # Operators (inline span with content: delimiters dropped when substitution fires)
  ("increase by $\\times 2$", "increase by × 2"),
  ("2 \\times 3 = 6", "2 × 3 = 6"),
  ("x \\pm y", "x ± y"),
  # Relations (inline spans drop $ when substitution fires)
  ("$x \\geq 0$", "x ≥ 0"),
  ("a \\leq b \\leq c", "a ≤ b ≤ c"),
  ("p \\ne q", "p ≠ q"),
  # Calculus
  ("as x \\to \\infty", "as x → ∞"),
  ("\\sum x_i", "∑ x_i"),
  # Greek
  ("let \\alpha = 0.5", "let α = 0.5"),
  ("\\pi \\approx 3.14", "π ≈ 3.14"),
  ("$\\omega$ is angular", "ω is angular"),
  # Sqrt with argument
  ("\\sqrt{x}", "√(x)"),
  ("result is $\\sqrt{2}$", "result is √(2)"),
  # Ellipsis aliases
  ("wait \\ldots then go", "wait … then go"),
  ("a, b, \\dots, z", "a, b, …, z"),
])
def test_direct_substitution(text, expected):
  assert latex_to_unicode(text) == expected


@pytest.mark.parametrize("text", [
  # Currency must not be affected
  "el preu és $24.50",
  "cost: $5-10 per unit",
  "a $5 bill",
  # Shell variables must not be affected
  "my home is $HOME",
  "use $PATH to find",
  # Plain text
  "Hola, com estàs?",
  "normal conversation without math",
])
def test_preserves_non_latex_dollars(text):
  """Single $ not followed by a LaTeX command must survive intact."""
  assert latex_to_unicode(text) == text


# ── Streaming buffer ─────────────────────────────────────────────────


def _feed_all(chunks):
  buf = LatexStreamBuffer()
  out = "".join(buf.feed(c) for c in chunks)
  out += buf.flush()
  return out


def test_stream_single_chunk():
  """Whole text in one chunk = identical to direct call."""
  text = '"Comoestas" $\\rightarrow$ "Cómo estás?"'
  assert _feed_all([text]) == latex_to_unicode(text)


def test_stream_fragmented_command():
  """Token split across chunks must still resolve correctly."""
  assert _feed_all(["El $\\righ", "tarrow$ final"]) == "El → final"
  assert _feed_all(["a \\al", "pha b"]) == "a α b"
  assert _feed_all(["\\rig", "htarrow"]) == "→"


def test_stream_many_small_chunks():
  """Very fine-grained split still produces correct output."""
  chunks = list("prev $\\rightarrow$ next")
  assert _feed_all(chunks) == "prev → next"


def test_stream_preserves_currency_across_chunks():
  """Currency split across chunks must not be affected."""
  assert _feed_all(["el preu és $", "24.50"]) == "el preu és $24.50"
  assert _feed_all(["$HOM", "E"]) == "$HOME"


def test_stream_flush_emits_pending():
  """Final flush must drain any retained pending text."""
  buf = LatexStreamBuffer()
  out1 = buf.feed("trailing \\alph")
  tail = buf.flush()
  assert out1 + tail == "trailing \\alph"  # incomplete, not a real command


def test_stream_flush_emits_complete_pending():
  """If pending becomes complete command at flush, substitute."""
  buf = LatexStreamBuffer()
  buf.feed("text \\alpha")
  # pending holds "\\alpha" because it's at end and < SAFE_BUFFER chars
  tail = buf.flush()
  # After flush, the regex runs on pending → replaces \alpha with α
  # (first feed emitted "text " only because \alpha was incomplete-looking)
  assert tail in ("α", "\\alpha")  # depends on feed cut behaviour
  # Combined must be correct:
  buf2 = LatexStreamBuffer()
  assert (buf2.feed("text \\alpha") + buf2.flush()) == "text α"


def test_stream_multiple_tokens_in_chunk():
  """A chunk with multiple LaTeX tokens all substituted."""
  assert _feed_all(["x \\leq y \\geq z"]) == "x ≤ y ≥ z"


def test_stream_empty_chunks():
  """Empty chunks are harmless."""
  assert _feed_all(["", "\\alpha", ""]) == "α"
  assert _feed_all([""]) == ""


# ── Real-world sample (the case that triggered the fix) ──────────────


def test_real_world_gemma_spelling_correction():
  """Reproduces the user-reported case from 2026-04-20."""
  raw = (
    '"Comoestas" $\\rightarrow$ "¿Cómo estás?"\n'
    '"quedoao l aepser" $\\rightarrow$ "quedo a la espera"\n'
    '"atu respues promta repsuesa" $\\rightarrow$ "de tu pronta respuesta"'
  )
  expected = (
    '"Comoestas" → "¿Cómo estás?"\n'
    '"quedoao l aepser" → "quedo a la espera"\n'
    '"atu respues promta repsuesa" → "de tu pronta respuesta"'
  )
  assert latex_to_unicode(raw) == expected
