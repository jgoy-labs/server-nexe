"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/core/latex_sanitizer.py
Description: Convert LaTeX math notation in LLM output to Unicode glyphs.
  Some models (Gemma, etc.) emit LaTeX like $\\rightarrow$ in plain chat
  answers. The frontend uses marked.js without KaTeX, so users would see
  the literal string. We centralise the substitution server-side so every
  client (web UI, API v1, future CLI/MCP) benefits.

  Two-pass approach:
    1. INLINE_MATH_RE scans for $...$ spans. If the span contains a known
       LaTeX command, substitute the inner content AND drop the delimiters.
       Otherwise leave it alone (currency, shell vars, etc.).
    2. BARE_LATEX_UNICODE substitutes bare \\command occurrences outside
       of spans.

  Streaming buffer handles chunks that split a LaTeX token or that leave
  an open $ without its closing counterpart.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
from typing import List, Pattern, Tuple


BARE_LATEX_UNICODE: List[Tuple[Pattern, str]] = [
  (re.compile(r'\\rightarrow\b|\\to\b'), '→'),
  (re.compile(r'\\leftarrow\b|\\gets\b'), '←'),
  (re.compile(r'\\Rightarrow\b'), '⇒'),
  (re.compile(r'\\Leftarrow\b'), '⇐'),
  (re.compile(r'\\leftrightarrow\b'), '↔'),
  (re.compile(r'\\uparrow\b'), '↑'),
  (re.compile(r'\\downarrow\b'), '↓'),
  (re.compile(r'\\times\b'), '×'),
  (re.compile(r'\\div\b'), '÷'),
  (re.compile(r'\\pm\b'), '±'),
  (re.compile(r'\\cdot\b'), '·'),
  (re.compile(r'\\leq\b|\\le\b'), '≤'),
  (re.compile(r'\\geq\b|\\ge\b'), '≥'),
  (re.compile(r'\\neq\b|\\ne\b'), '≠'),
  (re.compile(r'\\approx\b'), '≈'),
  (re.compile(r'\\equiv\b'), '≡'),
  (re.compile(r'\\infty\b'), '∞'),
  (re.compile(r'\\sum\b'), '∑'),
  (re.compile(r'\\prod\b'), '∏'),
  (re.compile(r'\\int\b'), '∫'),
  (re.compile(r'\\partial\b'), '∂'),
  (re.compile(r'\\alpha\b'), 'α'),
  (re.compile(r'\\beta\b'), 'β'),
  (re.compile(r'\\gamma\b'), 'γ'),
  (re.compile(r'\\delta\b'), 'δ'),
  (re.compile(r'\\pi\b'), 'π'),
  (re.compile(r'\\sigma\b'), 'σ'),
  (re.compile(r'\\theta\b'), 'θ'),
  (re.compile(r'\\mu\b'), 'μ'),
  (re.compile(r'\\lambda\b'), 'λ'),
  (re.compile(r'\\omega\b'), 'ω'),
  (re.compile(r'\\ldots\b|\\dots\b'), '…'),
  (re.compile(r'\\sqrt\{([^}]*)\}'), r'√(\1)'),
]

# Inline math span: $...$ on a single line, up to 200 chars of content.
# Conservative upper bound: real inline math is typically much shorter.
_INLINE_MATH_RE = re.compile(r'\$([^$\n]{1,200})\$')

# Maximum characters to retain an unclosed $ before giving up (treat as currency)
_UNCLOSED_DOLLAR_LIMIT = 100

# Longest bare command + a bit: \leftrightarrow = 14; 24 is comfortable.
_SAFE_BUFFER = 24

# Matches "\\letters" at the end of a string (potentially incomplete).
_INCOMPLETE_LATEX = re.compile(r'\\[a-zA-Z]*$')


def _apply_bare(text: str) -> str:
  for pat, repl in BARE_LATEX_UNICODE:
    text = pat.sub(repl, text)
  return text


def _replace_inline_span(match: re.Match) -> str:
  inner = match.group(1)
  converted = _apply_bare(inner)
  # If the bare substitution changed anything, it was real math — drop $..$
  # delimiters too. Otherwise leave the original string (e.g. "$5, $10").
  if converted != inner:
    return converted
  return match.group(0)


def latex_to_unicode(text: str) -> str:
  """Replace known LaTeX math tokens with Unicode glyphs."""
  text = _INLINE_MATH_RE.sub(_replace_inline_span, text)
  text = _apply_bare(text)
  return text


class LatexStreamBuffer:
  """Buffers stream chunks to avoid splitting LaTeX tokens across chunks.

  Retains:
    - trailing "\\letters" that could be an incomplete command, and
    - any unclosed "$" within the last UNCLOSED_DOLLAR_LIMIT chars
      (so $\\rightarrow$ split across chunks is reassembled before substitution).

  Currency-like unclosed dollars older than UNCLOSED_DOLLAR_LIMIT are emitted
  as-is to avoid retaining pending forever.

  Usage:
    buf = LatexStreamBuffer()
    for chunk in stream:
      out = buf.feed(chunk)
      if out:
        yield out
    tail = buf.flush()
    if tail:
      yield tail
  """

  def __init__(self) -> None:
    self._pending: str = ""

  def feed(self, chunk: str) -> str:
    combined = self._pending + chunk
    cut = len(combined)

    # 1. Unclosed $: find last $ position; if odd number of $ overall,
    #    the last one is an opener waiting for a closer.
    open_dollar = self._last_unclosed_dollar(combined)
    if open_dollar >= 0 and len(combined) - open_dollar <= _UNCLOSED_DOLLAR_LIMIT:
      cut = min(cut, open_dollar)

    # 2. Incomplete bare LaTeX command at the end.
    last_bs = combined.rfind('\\')
    if last_bs >= 0 and len(combined) - last_bs < _SAFE_BUFFER:
      tail = combined[last_bs:]
      if _INCOMPLETE_LATEX.match(tail):
        cut = min(cut, last_bs)

    emit = latex_to_unicode(combined[:cut])
    self._pending = combined[cut:]
    return emit

  def flush(self) -> str:
    result = latex_to_unicode(self._pending)
    self._pending = ""
    return result

  @staticmethod
  def _last_unclosed_dollar(text: str) -> int:
    positions = [i for i, c in enumerate(text) if c == '$']
    if len(positions) % 2 == 1:
      return positions[-1]
    return -1
