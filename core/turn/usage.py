"""What an engine says one call cost, in tokens (pla-tokens-reals, A).

One shape for every engine, one place where it is kept (`record_llm_call` /
`note_usage` in `core.turn.budget`), and everything that shows tokens — the
turn trace, the metrics, the web footer — reads it from there.

The rule is `None` for what the engine did not say. Never `0` (it would read
as "this cost nothing") and never an estimate dressed as a count: the footer
may still estimate, but it has to say so.
"""
from __future__ import annotations

from typing import Any, Optional

#: The in-band chunk an in-process engine's bridge sends the web door once the engine is done
#: (`{SENTINEL: usage}`, no text), like `__nexe_trunc__` does for the ceiling cut.
SENTINEL = "__nexe_usage__"

#: The keys of a usage dict. Every one is an int or None.
KEYS = ("tokens_in", "tokens_out", "cached_in")


def _count(value: Any) -> Optional[int]:
    """A non-negative int, else None (bools, strings and negatives are not counts)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def make(tokens_in: Any = None, tokens_out: Any = None, cached_in: Any = None) -> Optional[dict]:
    """The usage dict, or None when the engine said nothing at all.

    A call that really ran read at least one token in and wrote at least one out, so a
    `0` there is an engine (or a body builder) filling a field it did not know: it is
    "not said". Only `cached_in` may be a real zero (a cache miss).
    """
    usage = {"tokens_in": _count(tokens_in) or None, "tokens_out": _count(tokens_out) or None,
             "cached_in": _count(cached_in)}
    return usage if any(v is not None for v in usage.values()) else None


def from_engine_result(result: Any) -> Optional[dict]:
    """An in-process engine's `chat()` result (MLX, llama.cpp): `prompt_tokens`,
    `tokens` and, for MLX, `cached_tokens` (the prefix it reused). An engine that had
    no counter sets `usage_estimated`: it still fills the fields (the context window
    maths reads them) but they are not a count."""
    if not isinstance(result, dict) or result.get("usage_estimated"):
        return None  # the engine could not count: its numbers are a guess, and a guess is not said
    return make(result.get("prompt_tokens"), result.get("tokens"), result.get("cached_tokens"))


def from_ollama(data: Any) -> Optional[dict]:
    """The last line of an Ollama reply (and the whole non-stream body)."""
    if not isinstance(data, dict):
        return None
    return make(data.get("prompt_eval_count"), data.get("eval_count"))


def from_openai(usage: Any) -> Optional[dict]:
    """An OpenAI-shaped `usage` (`prompt_tokens`/`completion_tokens`) or an
    Anthropic one (`input_tokens`/`output_tokens`, `cache_read_input_tokens`)."""
    if not isinstance(usage, dict):
        return None
    details = usage.get("prompt_tokens_details")
    cached = (details or {}).get("cached_tokens") if isinstance(details, dict) else None
    if cached is None:  # Anthropic's name, then DeepSeek's
        cached = usage.get("cache_read_input_tokens", usage.get("prompt_cache_hit_tokens"))
    tokens_in = usage.get("prompt_tokens", usage.get("input_tokens"))
    tokens_out = usage.get("completion_tokens", usage.get("output_tokens"))
    return make(tokens_in, tokens_out, cached)


def from_response(response: Any) -> Optional[dict]:
    """The `usage` of a finished JSON reply (`/v1`, non-stream), OpenAI-shaped.

    The builders of that body write `0` for what the engine did not say; `make` reads
    that as "not said". The cache count rides in `prompt_tokens_details`, when known.
    """
    usage = response.get("usage") if isinstance(response, dict) else None
    return from_openai(usage)


def from_chunk(chunk: Any) -> Optional[dict]:
    """What one stream chunk says the call cost, in whatever alphabet the chunk is.

    The bridge's sentinel (MLX, llama.cpp), an Ollama `done` line, or an API
    provider's chunk carrying its `usage`. Plain text chunks say nothing.
    """
    if not isinstance(chunk, dict):
        return None
    if isinstance(chunk.get(SENTINEL), dict):
        return chunk[SENTINEL]
    if isinstance(chunk.get("usage"), dict):
        return from_openai(chunk["usage"])
    if chunk.get("done"):
        return from_ollama(chunk)
    return None


def merge(first: Optional[dict], later: Optional[dict]) -> Optional[dict]:
    """Two statements about one call: what the later one says wins, the rest stays."""
    if not first or not later:
        return later or first
    return {key: later.get(key) if later.get(key) is not None else first.get(key) for key in KEYS}
