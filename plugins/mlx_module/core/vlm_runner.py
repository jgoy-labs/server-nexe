"""The MLX vision (VLM) path, extracted from `chat.py` in #966 — slice A.

The 9 methods and 3 helpers in this file come from `MLXChatNode` with the body
verbatim: not one line was rewritten. `MLXChatNode` keeps them as delegators
under the SAME name, so the ~81 calls the suite already made keep working and
act as the golden master of the move.

`MLXVisionRunner` reads `config` live from the node (a property, not a copy):
`apply_config` replaces the config object when the model changes, and a copy
would have gone stale — the same bug family the `_is_vlm` comments already warn about.
"""
import contextlib
import copy
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .generate_helpers import (
    sanitize_messages_for_alternation,
    truncate_messages_to_budget,
)
from .model_json import _load_json_safe
from .qwen35_directive import (
    QWEN35_THINKING_DIRECTIVE,
    _inject_thinking_directive_into_messages,
    _qwen35_needs_thinking_directive,
)
from core.utils import compute_system_hash

logger = logging.getLogger(__name__)


def _prompt_has_open_think_prefix(formatted_prompt: str) -> bool:
    """Detect chat templates that inject ``<think>`` *into the prompt*.

    Empirical incident 2026-05-13: Qwen3 / Qwen3.5 / Gemma-4 chat templates
    pre-open the reasoning block when ``enable_thinking`` is true (default
    or explicit). Their tail looks like::

        <|im_start|>assistant\\n<think>\\n

    The model then generates ``[reasoning]</think>\\n[answer]`` — note the
    *missing* opening ``<think>`` in the model's own output. Downstream
    parsers (``_process_content_think_tags`` in routes_chat.py) only switch
    into "thinking" mode when they see ``<think>`` *in the stream*, so they
    miss the prefix and dump the entire reasoning verbatim into the visible
    body of the response, while the trailing ``</think>`` and final answer
    look like noise.

    This helper is the engine-side detector: if the prompt already contains
    the opener, the engine MUST emit a synthetic ``<think>\\n`` as the very
    first chunk of the stream so downstream parsers see the canonical
    ``<think>...</think>`` pattern and split correctly.

    The check is structural (looks at the prompt tail), not family-based
    (no Qwen/Gemma allowlist). gpt-oss uses a different convention with
    ``<|channel|>analysis<|message|>`` tags emitted *by the model*, so its
    prompt does NOT end in ``<think>`` and this helper returns False — its
    existing pipeline keeps working unchanged.

    Models that don't open the reasoning block in the prompt (e.g.
    thinking_enabled=False which produces the ``<think>\\n\\n</think>\\n\\n``
    tail, or models with no reasoning at all) also return False.
    """
    if not formatted_prompt:
        return False
    tail = formatted_prompt.rstrip()
    return tail.endswith("<think>")


def _render_vlm_prompt(processor, mdl_config: dict, prompt_arg, num_images: int, thinking_enabled: bool) -> str:
    """The chat template, with the thinking switch when the processor takes it.

    `enable_thinking=False` is passed only when reasoning is off; a processor
    whose template does not know it raises TypeError and gets the plain call.
    With reasoning on nothing is passed — the model's native default.
    """
    from mlx_vlm.prompt_utils import apply_chat_template

    if not thinking_enabled:
        try:
            return apply_chat_template(
                processor=processor, config=mdl_config, prompt=prompt_arg,
                num_images=num_images, enable_thinking=False,
            )
        except TypeError:
            pass  # processor template does not support enable_thinking — fall through
    return apply_chat_template(
        processor=processor, config=mdl_config, prompt=prompt_arg, num_images=num_images,
    )


def _split_resumed_answer(messages: list, continue_final: bool) -> tuple:
    """(messages before the answer being resumed, its raw text) — or the
    messages untouched and None when this is not a resume (C4.6-a-vlm)."""
    if continue_final and messages and messages[-1].get("role") == "assistant":
        return messages[:-1], messages[-1].get("content") or ""
    return messages, None


def _without_echoed_opener(formatted_prompt: str, raw_tail: str) -> str:
    """The raw generation, minus the `<think>\n` the stream itself added.

    When the template leaves the reasoning block open, `_run_vlm_streaming`
    emits a synthetic `<think>\n` first (see `_prompt_has_open_think_prefix`),
    so the answer's raw text starts with an opener the prompt already has.
    Appending it again would put `<think>` twice in the prompt of a resume.
    """
    opener = "<think>\n"
    if _prompt_has_open_think_prefix(formatted_prompt) and raw_tail.startswith(opener):
        return raw_tail[len(opener):]
    return raw_tail


def _eos_token_ids(processor) -> frozenset:
    """The token ids that end a turn for this processor's tokenizer (C4.6):
    what tells a VLM answer that stopped ON the ceiling from one cut by it."""
    tokenizer = getattr(processor, "tokenizer", processor)
    ids = getattr(tokenizer, "eos_token_ids", None)
    if ids is None:
        ids = getattr(tokenizer, "eos_token_id", None)
    if ids is None:
        return frozenset()
    if isinstance(ids, int):
        return frozenset({ids})
    try:
        return frozenset(int(i) for i in ids)
    except (TypeError, ValueError):
        return frozenset()


def _chunked_prefill_is_broken(model_path: str) -> bool:
    """True for architectures where mlx_vlm's chunked prefill crashes.

    Reproduced on mlx_vlm 0.4.4 with Qwen3-VL (``Qwen3VLForConditionalGeneration``)
    and a text-only prompt: as soon as the prompt exceeds the chunk size,
    ``models/qwen3_vl/language.py`` does ``visual_pos_masks[:, n_to_process:]``
    with ``visual_pos_masks`` still None and raises TypeError. Verified at
    645/4.2k/8.8k tokens against step sizes 2048/512/128 — every chunked
    combination fails, only disabling chunking survives.

    No catalog model uses this architecture, so this is not a shipped bug; the
    check exists so that lowering the chunk size does not make a user-supplied
    Qwen3-VL model fail *earlier* (at 512 tokens instead of 2048) than it does
    today. Their behaviour is left exactly as it was.
    """
    if not model_path:
        return False
    config = _load_json_safe(Path(model_path) / "config.json")
    if not config:
        return False
    architectures = config.get("architectures") or []
    if isinstance(architectures, str):
        architectures = [architectures]
    blob = " ".join(str(a) for a in architectures) + " " + str(config.get("model_type", ""))
    return "qwen3vl" in blob.lower().replace("_", "").replace("-", "")


#: #1123: the user message a prompt is rendered with to find where THIS turn's
#: user message starts. Any text: only where the two renders part matters.
_PROBE_TEXT = "\u2063"


def _common_prefix_len(a: list, b: list) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _drop_cache(state) -> None:
    state.cache = None
    state.token_ids = None


def _reuse_metrics(had_cache: bool, cached_tokens: int, reused) -> tuple:
    """#1123: what the generation reused, when the boundary step knows it."""
    if reused is None:
        return had_cache, cached_tokens
    return reused > 0, reused


def _snapshot_cache(state) -> tuple:
    """The prompt cache as it is now, safe from the generation that follows
    (#1123). A KV layer only ever writes past its offset, so a shallow copy
    that keeps the offset is enough; a recurrent layer (ArraysCache) replaces
    its arrays, so its list is copied."""
    layers = []
    for layer in state.cache:
        kept = copy.copy(layer)
        inner = getattr(layer, "cache", None)
        if isinstance(inner, list):
            kept.cache = list(inner)
        layers.append(kept)
    return layers, list(state.token_ids)


@contextlib.contextmanager
def _positions_follow_the_cache(model):
    """Text over a reused cache is numbered from where the cache ends (#1123).

    mlx_vlm 0.4.4, every model whose language model keeps `_rope_deltas` (the
    Qwen VL family, Qwen3.5 included): a text-only `get_input_embeddings` sets
    it to None, and the first forward then takes positions from
    `get_rope_index` over the NEW tokens alone — 0, 1, 2… — while the cache
    already holds positions 0…offset-1. Measured 02/10 with Qwen3.5-4B: the
    same greedy conversation answered differently with the cache than
    without. A zero delta, which is what text has, sends that forward down
    the branch that counts from the cache's offset; a cold call (offset 0)
    still takes `get_rope_index`. An image turn sets its own deltas and is
    left alone (it starts cold, see `_cache_at_turn_boundary`)."""
    lm = getattr(model, "language_model", None)
    if lm is None or not hasattr(lm, "_rope_deltas"):
        yield
        return
    import mlx.core as mx

    original = model.get_input_embeddings

    def text_counts_from_the_cache(input_ids=None, pixel_values=None, **kwargs):
        out = original(input_ids, pixel_values, **kwargs)
        if pixel_values is None and input_ids is not None:
            lm._rope_deltas = mx.zeros((input_ids.shape[0], 1), dtype=input_ids.dtype)
        return out

    model.get_input_embeddings = text_counts_from_the_cache
    try:
        yield
    finally:
        del model.get_input_embeddings


def _prefill_step_kwargs(model_path: str = "") -> Dict[str, int]:
    """Chunk size for the VLM prefill, as kwargs to splat into mlx_vlm calls.

    mlx_vlm's default is 2048 (``generate.py:DEFAULT_PREFILL_STEP_SIZE``), which
    on a low-RAM machine costs more peak memory than it needs to. Measured on
    Qwen3.5-4B-MLX-4bit (M4 Max, peak via ``mx.get_peak_memory()``):

        prompt ~8.0k tokens: 2048 -> 5.15 GB / 5.22 s
                              512 -> 4.06 GB / 5.27 s   <- default here
                              128 -> 3.66 GB / 6.07 s
                             None -> 12.43 GB / 6.51 s  (chunking disabled)

    512 takes the memory win at no measurable latency cost; 128 buys another
    0.4 GB for ~16% more time, so it is opt-in rather than the default. Note
    that ``None`` disables chunking entirely and is catastrophic on long
    prompts — ``NEXE_MLX_PREFILL_STEP=default`` therefore means "leave the
    library default alone", not "disable".
    """
    import os as _os_pf  # noqa: PLC0415
    raw = _os_pf.environ.get("NEXE_MLX_PREFILL_STEP", "").strip().lower()
    if raw == "default":
        return {}
    if _chunked_prefill_is_broken(model_path):
        # Leave this model exactly as it was: a smaller chunk would only move
        # the upstream crash to a shorter prompt. See _chunked_prefill_is_broken.
        logger.warning(
            "MLX: chunked prefill is broken upstream for this architecture (%s) — "
            "leaving mlx_vlm's default untouched", model_path,
        )
        return {}
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return {"prefill_step_size": value}
        except ValueError:
            pass
        logger.warning(
            "NEXE_MLX_PREFILL_STEP=%r is not a positive integer or 'default' — using 512", raw
        )
    return {"prefill_step_size": 512}

class MLXVisionRunner:
    """The VLM path of `MLXChatNode`. The bodies are the originals, untouched."""

    def __init__(self, node):
        self._node = node

    @property
    def config(self):
        """Live from the node: `apply_config` replaces the config object."""
        return self._node.config

    def _get_model(self) -> tuple:
        """Delegation to the node: resolved at call time, because tests patch
        `MLXChatNode._get_model` AFTER the node is built."""
        return self._node._get_model()

    def _normalize_image_input(self, raw) -> bytes:
        if isinstance(raw, str):
            import base64
            if raw.startswith("data:"):
                try:
                    raw = raw.split(",", 1)[1]
                except IndexError:
                    pass
            try:
                raw = base64.b64decode(raw, validate=False)
            except Exception as exc:
                raise ValueError(
                    f"VLM image[0] is str but not valid base64: {exc}"
                ) from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError(
                f"VLM image[0] must be bytes or base64 str, got {type(raw).__name__}"
            )
        return bytes(raw)

    def _prepare_vlm_prompt(
        self,
        messages: List[Dict],
        system: str,
        processor,
        has_image: bool,
        thinking_enabled: bool = True,
        max_tokens: Optional[int] = None,
        continue_final: bool = False,
    ) -> str:
        """Build the VLM prompt with thinking control.

        `continue_final` (C4.6, FD-S6): the last message is the assistant answer
        being resumed, and the prompt must END inside it. Built as the prompt
        the answer was generated from (the history before it, with the
        generation prompt) plus the raw text the model generated — the exact
        prefix by construction, whatever the template. `continue_final_message`
        was measured first (26/09): exact for Qwen3.5, Qwen3-VL and Gemma 4
        e4b, NOT for Gemma 4 31B, whose generation prompt opens an empty
        thought channel that a rendered final message does not carry.

        Empirically detected 2026-05-13 (Qwen3.5-27B-4bit on MLX): the VLM
        branch was ignoring the user's Raonament toggle entirely. Root cause:
        ``execute()`` did not forward ``thinking_enabled`` to ``_generate_vlm``,
        and ``_prepare_vlm_prompt`` did not pass ``enable_thinking`` down to
        ``mlx_vlm.prompt_utils.apply_chat_template``. The Qwen3/Qwen3.5
        ``chat_template.jinja`` reads the ``enable_thinking`` Jinja variable to
        decide whether to inject ``<think>\\n\\n</think>\\n\\n`` (suppressed)
        or ``<think>\\n`` (force-thinking). With the kwarg missing the template
        defaulted to the second branch and the model thought every time.

        Fix: forward ``enable_thinking=False`` through ``apply_chat_template``
        (mlx_vlm forwards kwargs to ``processor.apply_chat_template`` which in
        turn passes them to the Jinja template). When ``thinking_enabled`` is
        True we pass nothing — preserving the model's native default
        behaviour (which for Qwen3.5 happens to be "always think").

        Tokenizer/processor combinations that don't recognise ``enable_thinking``
        will raise ``TypeError``; we fall back to the no-kwarg call so older or
        non-Qwen processors keep working.
        """
        import os

        try:
            with open(
                os.path.join(self.config.model_path, "config.json")
            ) as _cf:
                mdl_config = json.load(_cf)
        except Exception:
            mdl_config = {"model_type": ""}

        # #860: sanitize before templating, like the text path does at
        # generate_helpers.py:226. Without this the two branches built
        # different prompts from the same history — the text one merging
        # consecutive same-role turns, this one emitting them back to back,
        # which is malformed for every VL model in the catalog. /ui/chat
        # cannot produce that history (SessionManager collapses adjacent
        # roles first), but /v1/chat/completions does not sanitize at all and
        # the OpenAI wire format lets a client send it.
        # System is prepended AFTER: sanitize drops system messages by design.
        sanitized = sanitize_messages_for_alternation(messages)

        # #845: the same prompt-level ceiling the text path got in 47efa879.
        # It has to be here and not at the caller because the order is load
        # bearing (generate_helpers.py:231): alternation must hold for the
        # messages actually KEPT, so sanitize first, measure second.
        #
        # A VLM processor is NOT a tokenizer — Qwen3VLProcessor has no
        # .encode(), it exposes .tokenizer. Passing the processor straight in
        # would raise AttributeError on every VLM turn, which with the default
        # model means every turn.
        #
        # With an image attached the estimate undercounts: image tokens never
        # pass through the text tokenizer. That is accepted — this is a net
        # against unbounded growth, not an exact accountant (same caveat the
        # cache accounting already carries below).
        if self.config.max_kv_size is not None:
            budget_tokenizer = getattr(processor, "tokenizer", None)
            if budget_tokenizer is None and hasattr(processor, "encode"):
                budget_tokenizer = processor
            if budget_tokenizer is None:
                logger.warning(
                    "VLM context budget skipped: processor %s exposes neither "
                    "a tokenizer nor encode(), so the prompt cannot be measured "
                    "(#845). The conversation grows unbounded.",
                    type(processor).__name__,
                )
            else:
                sanitized = truncate_messages_to_budget(
                    system,
                    sanitized,
                    budget_tokenizer,
                    self.config.max_kv_size,
                    max_tokens if max_tokens is not None else self.config.max_tokens,
                )

        sanitized, resumed_tail = _split_resumed_answer(sanitized, continue_final)

        all_messages: List[Dict[str, Any]] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        if sanitized:
            all_messages.extend(sanitized)

        # Qwen3.5-only: when Raonament=ON, reinforce thinking in the system
        # prompt because the chat template alone is not enough (model mimics
        # historial turns and skips reasoning in multi-turn conversations).
        # See _qwen35_needs_thinking_directive docstring for the rationale.
        if _qwen35_needs_thinking_directive(
            str(mdl_config.get("model_type", "")), thinking_enabled
        ):
            all_messages = _inject_thinking_directive_into_messages(
                all_messages, QWEN35_THINKING_DIRECTIVE
            )

        formatted = _render_vlm_prompt(
            processor, mdl_config, all_messages if all_messages else "",
            1 if has_image else 0, thinking_enabled,
        )
        if resumed_tail is None:
            return formatted
        return formatted + _without_echoed_opener(formatted, resumed_tail)

    @staticmethod
    def _reset_rotated_vlm_state(prompt_cache_state) -> bool:
        """Review #826 (major): never reuse a RotatingKVCache that has already rotated.

        With max_kv_size, mlx_vlm creates a RotatingKVCache on the 1st turn; the
        reuse path (generate.py) trims with PLAIN KVCache semantics
        (`keys[:, :, :prefix_len]` + offset) — once the buffer has rotated,
        that trim keeps interleaved garbage as the "prefix" of the
        conversation. If we detect rotation, we reset the state: this turn
        loses its reuse (re-prefill) but the context is never corrupted. Returns
        True if it was reset.
        """
        cache = getattr(prompt_cache_state, "cache", None)
        if not cache:
            return False
        try:
            rotated = any(
                type(c).__name__ == "RotatingKVCache"
                and getattr(c, "offset", 0) >= (getattr(c, "max_size", None) or float("inf"))
                for c in cache
            )
        except TypeError:  # non-iterable fakes in tests
            return False
        if rotated:
            prompt_cache_state.cache = None
            prompt_cache_state.token_ids = None
            logger.info(
                "MLX VLM cache: RotatingKVCache rotated — state reset "
                "(fresh bounded cache this turn; prefix reuse skipped, #826)"
            )
        return rotated

    @staticmethod
    def _reset_untrimmable_vlm_state(prompt_cache_state, new_token_ids) -> bool:
        """#849 (P1): never reuse a cache that mlx_vlm cannot trim.

        Sibling of the #826 guard, but looking at what actually decides the
        corruption: **whether the layers can be trimmed**, not whether they rotated.

        In ``mlx_vlm/generate.py`` (0.4.4) the reuse path trims the
        ``input_ids`` to the common prefix UNCONDITIONALLY, while the
        KV trim sits inside ``if hasattr(c, "keys") and c.keys is not None``.
        For a hybrid model that is not all-or-nothing: measured with
        ``Qwen3.5-4B-4bit`` and a POPULATED cache, ``make_cache()`` returns **8
        KVCache + 24 ArraysCache** (``layer_types`` = 8 full_attention + 24
        linear_attention) → **8 layers trim to the prefix and 24 keep the
        whole previous turn**. It is not "spare context": it is misalignment
        BETWEEN layers, and the model generates with two histories at once.

        It also cannot be fixed by trimming from the other side: ``ArraysCache`` is
        recurrent state (linear attention), ``is_trimmable()`` is False and
        ``mlx_lm.trim_prompt_cache`` refuses it. A compressed state cannot be
        cut at an arbitrary token — that is not an implementation bug.
        Upstream handles it in mlx-vlm 0.6.x with an ``exact`` mode (a snapshot of
        the whole prefix for mixed layouts); we are pinned to 0.4.4
        (mlx-lm/transformers) and the hole is known and OPEN at mlx-lm #980.

        The cheap alternative to a reset was also measured (reuse only when the
        prefix covers the WHOLE cache, with no trim): in a 3-turn chat the
        leftover tokens are **122 every turn** and they are the ``<think>`` block —
        the reasoning chain is stored in the cache and the next prompt does not
        re-serialize it. So the "no trim needed" case **never arrives**
        with thinking on, and conditional reuse would equal this reset
        with more code. The condition stays anyway because when it DOES hold
        (exact prefix) reuse is correct and worth keeping.

        Accepted cost: hybrid models go back to ``cached=0`` and the
        prefill grows. Speed is spent producing good text, instead of
        being gained while producing bad text.

        Returns:
            True if the state was reset (this turn re-prefills in full).
        """
        cache = getattr(prompt_cache_state, "cache", None)
        token_ids = getattr(prompt_cache_state, "token_ids", None)
        if not cache or not token_ids:
            return False
        try:
            all_trimmable = all(
                hasattr(c, "keys") and getattr(c, "keys", None) is not None for c in cache
            )
        except TypeError:  # non-iterable fakes in tests
            return False
        # All trimmable (pure KV) → mlx_vlm's trim is correct and the
        # 4× prefill is kept. This guard has nothing to say.
        if all_trimmable:
            return False
        # There are untrimmable layers. The ONLY case where reuse is still
        # safe is an EXACT prefix of the new prompt (no trim
        # pending). If we cannot check that — no ids, or the tokenizer
        # raises — the guard fails CLOSED: a metric may fail open, a
        # correctness guard may not. (The wiring test caught it: with a
        # processor that has no `.encode` the previous version let the
        # misaligned cache through on the very path it was meant to protect.)
        if new_token_ids is None:
            prefix_len = -1
        else:
            try:
                prefix_len = prompt_cache_state.find_prefix_length(new_token_ids)
            except Exception:  # nosec B110: test fakes / unusual tokenizer
                prefix_len = -1
        if prefix_len >= len(token_ids):
            return False
        prompt_cache_state.cache = None
        prompt_cache_state.token_ids = None
        logger.info(
            "MLX VLM cache: untrimmable layers (hybrid model), prefix %s < cached %d "
            "— state reset; this turn re-prefills instead of reusing a misaligned "
            "context (#849)",
            prefix_len if prefix_len >= 0 else "unknown",
            len(token_ids),
        )
        return True

    def _log_vlm_kv_request(self, model, prompt_cache_state=None) -> None:
        """#826/#845 instrumentation, VLM twin of "MLX cache created:" (text path).

        Records whether the requested max_kv_size can actually be enforced:
        mlx_vlm delegates to language_model.make_cache() when the model
        defines it (Qwen3.5/gemma…), IGNORING the limit — FD-S7 needs this
        verdict in the field logs to (re)attribute degeneration.
        """
        lang_model = getattr(model, "language_model", None)
        owned = hasattr(lang_model, "make_cache")
        # Review #826: INFO only when mlx_vlm will CREATE the cache (like the
        # "MLX cache created:" twin on the text path); on reuse (turns 2+) the
        # verdict is the same per-session fact → DEBUG so the log is not flooded.
        creating = prompt_cache_state is None or getattr(prompt_cache_state, "cache", None) is None
        logger.log(
            logging.INFO if creating else logging.DEBUG,
            "MLX VLM cache request: max_kv_size=%d %s",
            self.config.max_kv_size,
            "(model-owned make_cache — NOT enforced inside mlx_vlm, #845)"
            if owned else "(enforced via mlx_vlm prompt cache)",
        )

    def _run_vlm_streaming(
        self,
        model,
        processor,
        formatted_prompt: str,
        tmp_path: Optional[str],
        max_tokens: Optional[int],
        stream_callback: Callable[[str], None],
        cancel_event: Any = None,
        prompt_cache_state: Any = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ):
        from mlx_vlm import stream_generate as vlm_stream

        # See _prompt_has_open_think_prefix docstring: when the chat template
        # injects <think> into the prompt (Qwen3, Qwen3.5, Gemma-4 with
        # thinking on), the model's stream omits the opening tag, breaking
        # downstream split. Re-emit the missing opener as the first chunk so
        # the canonical <think>...</think> pattern reaches the client.
        prepend_think = _prompt_has_open_think_prefix(formatted_prompt)

        full_text = ""
        last = None
        emitted_prefix = False
        # prompt_cache_state (mlx_vlm >= 0.4): reuse the KV cache from previous
        # turns — mlx_vlm finds the common prefix and prefills only new tokens,
        # then updates the state. Passed only when present so an older mlx_vlm
        # that doesn't accept this kwarg keeps working unchanged (no reuse).
        cache_kwargs = {}
        if prompt_cache_state is not None:
            # Review #826: a rotated RotatingKVCache cannot be reused (mlx_vlm's
            # trim assumes a flat KVCache) — reset before passing it in.
            self._reset_rotated_vlm_state(prompt_cache_state)
            cache_kwargs["prompt_cache_state"] = prompt_cache_state
        # #826: cap the KV on the VLM path too (the text path already does via
        # make_prompt_cache). mlx_vlm honours max_kv_size when it CREATES the
        # prompt_cache; with a reused prompt_cache_state (turns 2+) the
        # existing cache is passed through unchanged. Models whose
        # language_model defines make_cache() (Qwen3.5 & co.) ignore the limit
        # inside mlx_vlm (#845, FD-S7) — the log below records the verdict.
        cache_kwargs["max_kv_size"] = self.config.max_kv_size
        self._log_vlm_kv_request(model, prompt_cache_state)
        # Sampling params: mlx_vlm >= 0.4 accepts temperature/top_p via **kwargs.
        # Passed only when set so unset values (and older mlx_vlm) keep prior
        # behavior. This also fixes temperature being dropped on the VLM path.
        sampling_kwargs = {}
        if temperature is not None:
            sampling_kwargs["temperature"] = temperature
        if top_p is not None:
            sampling_kwargs["top_p"] = top_p
        for chunk in vlm_stream(
            model=model,
            processor=processor,
            image=tmp_path,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.config.max_tokens,
            **cache_kwargs,
            **sampling_kwargs,
            **_prefill_step_kwargs(self.config.model_path),
        ):
            # Honour client-side cancel: when the HTTP client disconnects,
            # the route handler sets cancel_event so we exit early instead of
            # running to max_tokens (~100s of useless generation that blocks
            # the single-worker MLX executor for subsequent requests).
            if cancel_event is not None and cancel_event.is_set():
                logger.info("MLXChatNode: cancel_event set — breaking VLM stream loop")
                break
            delta = getattr(chunk, "text", "") or ""
            if delta:
                if prepend_think and not emitted_prefix:
                    stream_callback("<think>\n")
                    full_text += "<think>\n"
                    emitted_prefix = True
                stream_callback(delta)
                full_text += delta
            last = chunk
        return full_text, last

    def _stream_from_turn_boundary(self, model, processor, formatted_prompt, *args, turn, **kwargs):
        """`_run_vlm_streaming`, with the cache kept at THIS turn's boundary (#1123).

        mlx_vlm stores the prompt AND the generated answer in the cache, and
        reuses it only when the next prompt starts with all of it. The next
        prompt never does: the generation prompt's tail (Qwen3.5 with
        reasoning off: `<think>\\n\\n</think>\\n\\n`), the recalled context and
        the clock line are not rendered back into the history, and the stored
        answer is the cleaned one. A KV cache is trimmed back to the common
        prefix; a hybrid model's recurrent layers cannot be (#849), so every
        follow-up in a conversation re-read the whole prompt (4 of 4 on
        02/10, with the common prefix always 4 tokens short).

        The cache is first brought to where this turn's user message starts —
        what the next turn renders the same — copied there, used for this
        turn, and put back to the copy. The next turn reuses all of it and
        reads only the last exchange and its own message.
        """
        state = kwargs.get("prompt_cache_state")
        with _positions_follow_the_cache(model):
            # `reused`: the tokens this turn found already in the cache from an
            # earlier one — what the metrics report, not what the cache held
            # before the boundary step dropped or extended it.
            snapshot, reused = self._cache_at_turn_boundary(model, processor, formatted_prompt, turn, state)
            try:
                text, last = self._run_vlm_streaming(model, processor, formatted_prompt, *args, **kwargs)
            finally:
                if snapshot is not None:
                    state.cache, state.token_ids = snapshot
        return text, last, reused

    def _cache_at_turn_boundary(self, model, processor, formatted_prompt, turn, state):
        """Brings `state` to this turn's boundary and returns a copy to restore
        after the generation, or None to leave the cache as mlx_vlm leaves it
        (no boundary found: the reuse mlx_vlm does on its own, as before).
        A resume adds no user message: its boundary is the one already kept."""
        if state is None:
            return None, None
        messages, system, thinking_enabled, continue_final, has_image = turn
        if has_image:
            # mlx_vlm numbers an image turn's new tokens from 0 over a reused
            # cache, and its image positions are not a plain offset away
            # (mrope): it starts cold, as every hybrid turn did before.
            _drop_cache(state)
            return None, 0
        if continue_final:
            reused = len(state.token_ids) if getattr(state, "cache", None) is not None and state.token_ids else 0
        else:
            if not messages or messages[-1].get("role") != "user":
                return None, None
            split = self._turn_boundary(processor, formatted_prompt, messages, system, thinking_enabled)
            if split is None:
                return None, None  # no boundary: mlx_vlm reuses on its own, as before
            reused = self._prefill_to_boundary(model, processor, split, state)
            if reused is None:
                return None, 0
        if getattr(state, "cache", None) is None or not getattr(state, "token_ids", None):
            return None, reused
        return _snapshot_cache(state), reused

    def _turn_boundary(self, processor, formatted_prompt, messages, system, thinking_enabled):
        """Where this turn's own messages start in the prompt: the text to
        prefill up to its last token, that token, and the ids — or None.

        Found by rendering the same history with a stand-in user message, so
        it holds for any chat template."""
        from core.turn.assemble import TURN_START_KEY  # deferred: core is imported lazily here

        tok = getattr(processor, "tokenizer", processor)
        # Where this turn's own messages begin: marked by the web door (the
        # recalled context and the image note are turns of their own, placed
        # before the user's message); without the mark, the user's message.
        start = next((i for i, m in enumerate(messages) if m.get(TURN_START_KEY)), len(messages) - 1)
        try:
            probe = self._prepare_vlm_prompt(
                list(messages[:start]) + [{"role": "user", "content": _PROBE_TEXT}],
                system, processor, False, thinking_enabled=thinking_enabled,
            )
            full_ids = list(tok.encode(formatted_prompt))
            boundary = full_ids[:_common_prefix_len(full_ids, list(tok.encode(probe)))]
            if len(boundary) < 2 or len(boundary) >= len(full_ids):
                return None
            text = tok.decode(boundary[:-1], skip_special_tokens=False)
            if list(tok.encode(text)) != boundary[:-1]:
                return None
        except Exception:  # nosec B110: an unusual processor only loses the reuse
            logger.debug("MLX VLM cache: no turn boundary for this prompt", exc_info=True)
            return None
        return text, boundary[-1], boundary

    def _prefill_to_boundary(self, model, processor, split, state) -> Optional[int]:
        """Fills the cache up to the boundary and not one token more. Returns
        how many of its tokens came from an earlier turn, or None when it
        could not, with the cache dropped.

        mlx_vlm has no prefill-only call, and its generation feeds the first
        token it samples back into the cache before yielding it. So the
        prompt goes in one token short, and the sampler is made to "sample"
        the boundary's last token: the cache ends exactly on the boundary.

        It only ever EXTENDS the kept cache. A kept cache that is not a prefix
        of the boundary is dropped first, so mlx_vlm never trims one here — a
        hybrid model's recurrent layers cannot be cut (#849), and gemma-4's
        rotating window cannot be cut flat (#826; review 02/10: an edited
        conversation answered from a corrupted window). A kept cache already
        at the boundary (a regenerate) is used as it is."""
        import mlx.core as mx
        from mlx_vlm import stream_generate as vlm_stream

        text, last_id, boundary = split
        self._reset_rotated_vlm_state(state)
        kept = list(state.token_ids or []) if getattr(state, "cache", None) is not None else []
        if kept == boundary:
            return len(kept)
        if kept and kept != boundary[:len(kept)]:
            _drop_cache(state)
            kept = []
        forced = mx.array([last_id], dtype=mx.uint32)
        started = time.time()
        try:
            for _ in vlm_stream(
                model=model, processor=processor, prompt=text, max_tokens=1,
                prompt_cache_state=state, sampler=lambda _logprobs: forced,
                max_kv_size=self.config.max_kv_size,
                **_prefill_step_kwargs(self.config.model_path),
            ):
                pass
        except Exception:
            # Half-filled layers under the old ids: no cache rather than that.
            _drop_cache(state)
            logger.warning("MLX VLM cache: the turn boundary could not be filled; this turn starts cold (#1123)",
                           exc_info=True)
            return None
        if list(state.token_ids or []) != boundary:
            # The cache does not end where the boundary does: drop it rather
            # than reuse a cache that does not match its ids.
            _drop_cache(state)
            logger.warning("MLX VLM cache: the turn boundary did not line up; this turn starts cold (#1123)")
            return None
        logger.info(
            "MLX VLM cache: at the turn boundary (%d tokens, %d of them read now, %d ms) (#1123)",
            len(boundary), len(boundary) - len(kept), int((time.time() - started) * 1000),
        )
        return len(kept)

    def _run_vlm_oneshot(
        self,
        model,
        processor,
        formatted_prompt: str,
        tmp_path: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ):
        from mlx_vlm import generate as vlm_generate

        # Sampling params passed only when set (see _run_vlm_streaming).
        sampling_kwargs = {}
        if temperature is not None:
            sampling_kwargs["temperature"] = temperature
        if top_p is not None:
            sampling_kwargs["top_p"] = top_p
        self._log_vlm_kv_request(model)
        one = vlm_generate(
            model=model,
            processor=processor,
            image=tmp_path,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.config.max_tokens,
            verbose=False,
            max_kv_size=self.config.max_kv_size,  # #826 — see _run_vlm_streaming
            **sampling_kwargs,
            **_prefill_step_kwargs(self.config.model_path),
        )
        text = one.text if hasattr(one, "text") else str(one)
        if _prompt_has_open_think_prefix(formatted_prompt):
            # Same fix as the streaming path: re-emit the synthetic <think>\n
            # opener so downstream parsers recognise the reasoning block.
            text = "<think>\n" + text
        return text, one

    def _extract_vlm_metrics(
        self,
        result_obj,
        result_text: str,
        elapsed_ms: int,
        prefix_reused: bool = False,
        cached_tokens: int = 0,
        identity_hash: str = "",
        max_tokens_used: "Optional[int]" = None,
        eos_ids: "frozenset" = frozenset(),
    ) -> Dict[str, Any]:
        prompt_tokens = getattr(result_obj, "prompt_tokens", 0)
        gen_tokens = getattr(result_obj, "generation_tokens", len(result_text.split()))
        prompt_tps = getattr(result_obj, "prompt_tps", 0) or 0
        gen_tps = getattr(result_obj, "generation_tps", 0) or 0
        peak_memory = getattr(result_obj, "peak_memory", 0) or 0

        return {
            "text": result_text,
            "tokens": gen_tokens,
            "tokens_per_second": round(gen_tps, 1) if gen_tps else round(
                gen_tokens / max(elapsed_ms / 1000, 0.001), 1
            ),
            "prompt_tokens": prompt_tokens,
            "prefix_reused": prefix_reused,
            "cached_tokens": cached_tokens,
            "actual_prefill_tokens": max(prompt_tokens - cached_tokens, 0),
            "prompt_tps": round(prompt_tps, 1),
            "peak_memory_mb": round(peak_memory, 1),
            "identity_hash": identity_hash,
            "vlm": True,
            # FD-S5: mlx_vlm's GenerationResult has NO finish_reason —
            # the ceiling reached, and (C4.6) the last token not an end of
            # turn: a VLM answer is continuable now, so an answer that ended
            # naturally ON the limit must not read as cut.
            "finish_reason": (
                "length"
                if (
                    max_tokens_used and gen_tokens >= max_tokens_used
                    and getattr(result_obj, "token", None) not in eos_ids
                )
                else None
            ),
        }

    def _generate_vlm(
        self,
        system: str,
        messages: List[Dict],
        images: List[bytes],
        stream_callback: Optional[Callable[[str], None]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        thinking_enabled: bool = True,
        cancel_event: Any = None,
        session_id: str = "default",
        top_p: Optional[float] = None,
        continue_final: bool = False,
    ) -> Dict[str, Any]:
        """VLM generation with mlx_vlm (text + image). Uses mlx_vlm.generate().

        API mlx-vlm >= 0.4: `image` is a path (str) or list of paths, and `generate()`
        returns a `GenerationResult` with .text + real metrics (not a bare string).

        thinking_enabled forwarded to _prepare_vlm_prompt so the chat template
        sees the Raonament toggle (fix 2026-05-13 — see _prepare_vlm_prompt
        docstring for the upstream root cause).
        """
        import os
        import tempfile

        model, processor = self._get_model()
        has_image = bool(images)
        formatted_prompt = self._prepare_vlm_prompt(
            messages, system, processor, has_image, thinking_enabled=thinking_enabled,
            max_tokens=max_tokens, continue_final=continue_final,
        )

        # Prefix-cache for the VLM path (mlx_vlm native PromptCacheState), keyed
        # per session like the text path (_generate_blocking). Without this the
        # VLM path re-prefilled the whole context every turn (the historical
        # cached=0): MLXPromptCacheManager was only wired into the text path, so
        # any VLM model (e.g. the Qwen3.5 family — VL at every tier) never
        # reused its KV cache. get_or_create returns None on older mlx_vlm with
        # no PromptCacheState → no reuse, identical to the previous behaviour.
        from .vlm_cache_manager import get_vlm_cache_manager
        identity_hash = compute_system_hash(system)
        session_key = session_id[:8] if session_id else "default"
        model_key = f"{self.config.model_path}:{identity_hash}:{session_key}"
        cache_state = get_vlm_cache_manager(
            self.config.max_vlm_session_caches
        ).get_or_create(model_key)
        had_cache = cache_state is not None and getattr(cache_state, "cache", None) is not None
        # Best-effort reuse count for the log/metrics (text-only prompts tokenize
        # cleanly; with images the count is approximate). The real saving is
        # always visible in the prefill time regardless of this number.
        cached_tokens = 0
        if had_cache:
            try:
                _tok = getattr(processor, "tokenizer", processor)
                _new_ids = _tok.encode(formatted_prompt)
            except Exception:  # nosec B110: metric estimate only — never blocks generation
                _new_ids = None
            # #849: the guard runs BEFORE the count and is called ALWAYS (also with
            # _new_ids None: there it decides by layer type and fails closed).
            # When it fires, the metrics have to tell the truth
            # (prefix_reused=False, cached=0) — otherwise the log again promises
            # a reuse that did not happen, which is what made #843 unreadable.
            if self._reset_untrimmable_vlm_state(cache_state, _new_ids):
                had_cache = False
            elif _new_ids is not None:
                try:
                    cached_tokens = cache_state.find_prefix_length(_new_ids)
                except Exception:  # nosec B110: metric estimate only
                    cached_tokens = 0

        tmp_path = None
        try:
            if has_image:
                raw = self._normalize_image_input(images[0])
                tmp = tempfile.NamedTemporaryFile(
                    prefix="nexe_vlm_", suffix=".img", delete=False
                )
                tmp.write(raw)
                tmp.flush()
                tmp.close()
                tmp_path = tmp.name

            start_time = time.time()
            if stream_callback:
                result_text, result_obj, reused = self._stream_from_turn_boundary(
                    model, processor, formatted_prompt, tmp_path,
                    max_tokens, stream_callback, cancel_event,
                    prompt_cache_state=cache_state,
                    temperature=temperature, top_p=top_p,
                    turn=(messages, system, thinking_enabled, continue_final, has_image),
                )
                had_cache, cached_tokens = _reuse_metrics(had_cache, cached_tokens, reused)
            else:
                result_text, result_obj = self._run_vlm_oneshot(
                    model, processor, formatted_prompt, tmp_path, max_tokens,
                    temperature=temperature, top_p=top_p,
                )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        elapsed_ms = int((time.time() - start_time) * 1000)
        return self._extract_vlm_metrics(
            result_obj, result_text, elapsed_ms,
            prefix_reused=had_cache, cached_tokens=cached_tokens,
            identity_hash=identity_hash,
            max_tokens_used=max_tokens or self.config.max_tokens,
            eos_ids=_eos_token_ids(processor),
        )
