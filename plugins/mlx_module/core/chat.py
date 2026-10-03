# -*- coding: utf-8 -*-
"""
MLXChatNode - LLM node based on mlx-lm for Apple Silicon.

PREFIX MATCHING via MLXPromptCacheManager.

Features:
- Model singleton (loaded once, reused)
- MLXPromptCacheManager: trie-based cache with prefix matching
- Reuses KV states from prefix (system + history)
- Only processes new tokens each turn → speedup 5-10x

Requires:
- Apple Silicon (M1/M2/M3/M4)
- mlx-lm >= 0.30.0
- Model MLX format (safetensors)

"""
import asyncio
import functools
import gc
import atexit
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from .config import MLXConfig
# Re-exported: the VLM path that used them now lives in vlm_runner, but the suite
# imports them from here (test_multimodal, test_vlm_thinking_propagation).
from .qwen35_directive import (  # noqa: F401
    QWEN35_THINKING_DIRECTIVE,
    _inject_thinking_directive_into_messages,
    _qwen35_needs_thinking_directive,
)
from . import model_loader
from .text_runner import MLXTextRunner
# Re-exported: they live in model_loader since #966, but the suite and existing
# code import them from here. `noqa: F401` = deliberate re-export.
from .model_loader import (  # noqa: F401
    _detect_vlm_capability,
    _estimate_required_ram,
    _memory_snapshot_gb,
    _ram_guard_mode,
    _require_torch,
    _sanitize_safetensors_index,
)
# Re-exported: they live in the VLM module since #966, but the suite and existing
# code import them from here. `noqa: F401` = deliberate re-export.
from .vlm_runner import (  # noqa: F401
    MLXVisionRunner,
    _chunked_prefill_is_broken,
    _prefill_step_kwargs,
    _prompt_has_open_think_prefix,
)
from plugins._shared.chat_node import make_threadsafe_callback, base_chat_result
from core.turn.reasoning import finish_split, wrap_for_split

logger = logging.getLogger(__name__)


# Dedicated single-worker executor for ALL MLX operations.
#
# Empirical incident 2026-05-13: ``asyncio.to_thread()`` picks an arbitrary
# thread from the default pool. MLX maintains ``default_stream`` *per thread*,
# so when the prompt-cache KV is created on thread A and the next generation
# runs on thread B, MLX raises::
#
#     RuntimeError: There is no Stream(gpu, 1) in current thread.
#
# The state is permanently corrupted — every subsequent MLX call fails and
# the only recovery is a full server restart. Cancelling a generation
# mid-stream (Stop button in the UI) reliably reproduces it.
#
# Fix: pin every MLX entry point (``_generate_vlm``, ``_generate_blocking``,
# and any future ``reset_model`` style ops) to a single dedicated worker
# thread. With max_workers=1 the executor serialises requests on the same
# thread, so the per-thread ``default_stream`` stays consistent across
# turns and across cancel/abort transitions.
#
# max_workers=1 is correct: MLX already serialises generation internally via
# ``MLXChatNode._lock``, so we'd be queueing at the asyncio level anyway —
# moving the queue into the executor keeps everything on one thread without
# changing the effective concurrency contract.
_MLX_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-worker")

# Register an atexit cleanup so the dedicated MLX worker doesn't
# linger as a non-daemon thread on shutdown. `wait=False` + `cancel_futures=True`
# lets us tear down even when a generation is mid-flight (Stop button race,
# sidecar SIGTERM). Without this, the interpreter may hang at exit waiting for
# the executor thread to drain.
atexit.register(_MLX_EXECUTOR.shutdown, wait=False, cancel_futures=True)


# Known VLM architectures (config.json → architectures[])


# Vision key patterns in the safetensors weight map (fallback when architecture is unknown)








# vision_config alone is not sufficient — some non-VL models (e.g. Qwen3.5 MoE)
# include it as a config artefact without actual vision weights. Only trust it
# when the architecture name also contains one of these keywords.










# Minimum usable KV window for the hard-refusal check (= B004 budget floor
# rationale: below this a normal conversation degenerates anyway).












def _free_prompt_caches() -> None:
    """Drop the text and VLM prompt-cache states: KV bound to a model that is
    going away (reset_model, and a hot swap since #1137)."""
    try:
        from .prompt_cache_manager import get_prompt_cache_manager
        get_prompt_cache_manager().clear()
    except Exception as e:
        logger.warning("MLXChatNode: error clearing cache manager: %s", e)
    try:
        from .vlm_cache_manager import get_vlm_cache_manager
        get_vlm_cache_manager().clear()
    except Exception as e:
        logger.warning("MLXChatNode: error clearing VLM cache manager: %s", e)


class MLXChatNode:
    """
    Inference engine for MLX adapted for server-nexe.

    Maintains:
    - A single loaded model (singleton)
    - MLXPromptCacheManager for prefix matching (trie-based)
    - Reuses KV states from prefix (system + history)
    - Only processes new tokens each turn

    Class Attributes:
        _model: MLX model singleton
        _tokenizer: Tokenizer singleton
        _lock: Lock for thread-safety
        _config: Active configuration
    """

    _model: Optional[Any] = None
    _tokenizer: Optional[Any] = None  # tokenizer (text) or processor (VLM)
    _lock: threading.RLock = threading.RLock()  # RLock: safe against accidental re-entrant calls
    _config: Optional[MLXConfig] = None
    _is_vlm: bool = False  # True if the loaded model is a VLM
    _template_think_prefix: Optional[bool] = None  # template pre-opens <think> (#984)

    def __init__(self, config: Optional[MLXConfig] = None):
        """
        Initializes the MLX node.

        Args:
            config: MLX configuration (or loads from .env if None)
        """
        self.config = config or MLXConfig.from_env()

        # Update singleton config if it changes
        if (MLXChatNode._config is None or
                MLXChatNode._config.model_path != self.config.model_path):
            MLXChatNode._config = self.config
            MLXChatNode._model = None  # Force reload
            MLXChatNode._is_vlm = False  # Reset: will be re-detected during _get_model()
            MLXChatNode._template_think_prefix = None  # re-probe the new template

    def apply_config(self, new_config: "MLXConfig") -> None:
        """Hot-swap the active model config and invalidate the class singletons.

        Mirrors the reset that __init__ performs when the model path changes:
        swaps the shared _config, drops the cached _model so the next
        _get_model() reloads, and resets _is_vlm for re-detection. Public entry
        point so web_ui calls MLXModule.switch_model() instead of reaching into
        these class-level privates directly (B073).
        """
        old_path = getattr(MLXChatNode._config, "model_path", None)
        self.config = new_config
        MLXChatNode._config = new_config
        MLXChatNode._model = None
        MLXChatNode._is_vlm = False
        MLXChatNode._template_think_prefix = None
        if old_path != new_config.model_path:
            # #1137: the old model's prompt caches used to stay until LRU pushed
            # them out — never, if the new model is text-only and the VLM path
            # does not run again. With up to 4 VLM conversations kept, that is
            # up to 4 KV windows held for a model that is gone.
            #
            # On the MLX worker, like every MLX op (see _MLX_EXECUTOR): the clear
            # imports vlm_cache_manager, which imports mlx_vlm.generate, whose
            # module-level generation_stream belongs to the thread that imports
            # it first. Run from this request thread it left the worker with
            # "There is no Stream(gpu, 0) in current thread" on every turn
            # (live 03/10). Queued behind a generation in flight, ahead of the next.
            _MLX_EXECUTOR.submit(_free_prompt_caches)

    def _get_model(self) -> tuple:
        """Model and tokenizer/processor (lazy singleton).

        HOW it loads lives in `model_loader`; the singleton stays here, and it is
        this class's state. Access goes through the module on purpose (see the
        `model_loader` docstring): one resolution site for `_detect_vlm_capability`.
        """
        if MLXChatNode._model is None:
            model_loader.load_model_into(MLXChatNode, self.config)
        return MLXChatNode._model, MLXChatNode._tokenizer

    # NOTE: Legacy cache methods (_get_or_create_cache, _touch_lru, _destroy_cache)
    # have been removed. We now use MLXPromptCacheManager for real prefix matching.


    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes generation with MLX.

        Args:
            inputs: Dict with system, messages, messages_for_cache, session_id, stream_callback

        Returns:
            Dict with response, tokens, metrics, etc.
        """
        start_time = time.time()

        system = inputs.get("system", "")
        messages = inputs.get("messages", [])
        # messages_for_cache: version of messages for cache (without memory context)
        messages_for_cache = inputs.get("messages_for_cache", messages)
        session_id = inputs.get("session_id", "default")
        stream_callback = inputs.get("stream_callback")
        max_tokens_override = inputs.get("max_tokens")
        temperature_override = inputs.get("temperature")
        top_p_override = inputs.get("top_p")  # opt-in nucleus sampling; None → self.config.top_p
        thinking_enabled = inputs.get("thinking_enabled", True)  # True = model decides; False = force off
        images = inputs.get("images")  # Optional[List[bytes]] — VLM support
        # cancel_event: threading.Event-like; route handler sets it when the
        # HTTP client disconnects so streaming loops can break early instead
        # of running to max_tokens. None disables cancellation (back-compat).
        cancel_event = inputs.get("cancel_event")
        # FD-S6: resume the LAST assistant message instead of opening a new
        # turn. Text path only — enforced below.
        continue_final = bool(inputs.get("continue_final", False))

        # Log for debugging
        logger.info(
            "MLXChatNode: session=%s, msgs=%d",
            session_id[:8] if session_id else "none",
            len(messages)
        )

        # Capture event loop for thread-safe streaming
        loop = asyncio.get_running_loop()

        threadsafe_callback = make_threadsafe_callback(loop, stream_callback)

        try:
            # VLM path: if the model is a VLM, all generation goes through mlx_vlm.
            # We use _detect_vlm_capability (reads config.json of the current model) as
            # the primary source — it is always fresh and does not depend on the _is_vlm
            # singleton which can go stale when switching from VLM → text within the same session.
            is_vlm = model_loader._detect_vlm_capability(self.config.model_path)
            # C4.6: the VLM path resumes too — the default models (Qwen3.5,
            # Gemma 4) are VLMs. `_prepare_vlm_prompt` ends the prompt inside
            # the answer being resumed (continue_final_message).
            # ADR-010: this engine's model writes its reasoning INTO the text;
            # the plugin that knows how is the one that splits it, and hands
            # the caller {thinking, content} chunks.
            split = await self._reasoning_split(loop, is_vlm, thinking_enabled, continue_final)
            to_bridge, structured_cb = wrap_for_split(stream_callback, split)
            threadsafe_callback = make_threadsafe_callback(loop, to_bridge)
            # Pin MLX calls to the dedicated single-worker executor so all
            # operations share one thread and the per-thread default_stream
                # stays consistent across turns (see _MLX_EXECUTOR docstring).
            if is_vlm:
                result = await loop.run_in_executor(
                    _MLX_EXECUTOR,
                    functools.partial(
                        self._generate_vlm,
                        system, messages, images or [],
                        threadsafe_callback if stream_callback else None,
                        max_tokens_override, temperature_override,
                        thinking_enabled,
                        cancel_event,
                        session_id,
                        top_p=top_p_override,
                        continue_final=continue_final,
                    ),
                )
            else:
                # Run generation in thread (MLX is blocking)
                # With PREFIX MATCHING via MLXPromptCacheManager
                # Pass messages (for generation) and messages_for_cache (to store clean cache)
                result = await loop.run_in_executor(
                    _MLX_EXECUTOR,
                    functools.partial(
                        self._generate_blocking,
                        system,
                        messages,
                        messages_for_cache,  # To store clean cache (without memory context)
                        threadsafe_callback if stream_callback else None,
                        session_id,  # To separate caches per session
                        max_tokens_override,
                        temperature_override,
                        thinking_enabled,
                        cancel_event,
                        top_p=top_p_override,
                        continue_final=continue_final,
                    ),
                )

            # #984: the ceiling landed inside the reasoning, so the turn holds
            # no answer at all. Raising the budget does not fix this — measured
            # on Qwen3.5-9B, a model that loops on an ambiguous prompt burns
            # 8192 the same way it burns 2048. Ask again with thinking off,
            # which is the one thing measured to answer (the same question
            # returns in ~2900 tokens). One retry, never a chain.
            result = await self._answer_or_retry_without_thinking(
                loop,
                result,
                thinking_enabled=thinking_enabled,
                is_vlm=is_vlm,
                system=system,
                messages=messages,
                messages_for_cache=messages_for_cache,
                images=images,
                callback=threadsafe_callback if stream_callback else None,
                session_id=session_id,
                max_tokens=max_tokens_override,
                temperature=temperature_override,
                top_p=top_p_override,
                cancel_event=cancel_event,
                continue_final=continue_final,
            )

            reasoning_text, response_text = finish_split(structured_cb, split, result["text"])

            elapsed_ms = int((time.time() - start_time) * 1000)

            context_used = result["prompt_tokens"] + result["tokens"]
            system_tokens = len(system) // 4  # Estimate
            prompt_tps = result.get("prompt_tps", 0)

            # Use prefix_reused from the cache manager (based on real tokens)
            prefix_reuse = result.get("prefix_reused", False)
            cached_tokens = result.get("cached_tokens", 0)
            actual_prefill = result.get("actual_prefill_tokens", result["prompt_tokens"])

            # Calculate real speedup
            if cached_tokens > 0:
                reuse_ratio = (cached_tokens + actual_prefill) / max(actual_prefill, 1)
            else:
                reuse_ratio = 1.0

            # Calculate time per phase (ms)
            generation_tps = result["tokens_per_second"]
            prefill_ms = int((actual_prefill / prompt_tps * 1000) if prompt_tps > 0 else 0)
            generation_ms = int((result["tokens"] / generation_tps * 1000) if generation_tps > 0 else 0)
            overhead_ms = elapsed_ms - prefill_ms - generation_ms

            logger.info(
                "MLXChatNode: prefix=%s (cached=%d, new=%d), "
                "prefill=%.1f tok/s, gen=%.1f tok/s, %dms (p:%d g:%d), %.0f MB",
                "REUSED" if prefix_reuse else "FULL",
                cached_tokens,
                actual_prefill,
                prompt_tps,
                generation_tps,
                elapsed_ms,
                prefill_ms,
                generation_ms,
                result.get("peak_memory_mb", 0)
            )

            return {
                **base_chat_result(
                    response=response_text,
                    model_used=self.config.model_path,
                    elapsed_ms=elapsed_ms,
                    tokens=result["tokens"],
                    tokens_per_second=generation_tps,
                    prompt_tokens=result["prompt_tokens"],
                    context_used=context_used,
                    system_tokens=system_tokens,
                    system_prompt=system,
                ),
                "cache_active": result.get("cache_active", False),  # Compatibility alias
                "prefix_reuse": prefix_reuse,  # True = prefix matching succeeded
                "reuse_ratio": round(reuse_ratio, 2),  # Cached/new tokens ratio
                "cached_tokens": cached_tokens,  # Tokens reused from cache
                "actual_prefill_tokens": actual_prefill,  # Tokens actually processed
                "identity_hash": result.get("identity_hash", ""),  # System prompt hash
                # FD-S5: why generation stopped ('length' = cut by the
                # max_tokens ceiling) and whether a Continue can resume it.
                "finish_reason": result.get("finish_reason"),
                # Which path produced that finish_reason. The VLM one guesses
                # it (mlx_vlm reports none), so callers that turn it into a
                # contract signal — /v1's build_openai_response — must be able
                # to tell the guess from mlx_lm's real answer.
                "vlm": is_vlm,
                # #984: this answer came from the no-thinking retry, because the
                # first pass spent the whole ceiling inside <think>.
                "thinking_retry": result.get("thinking_retry", False),
                # ADR-010: the reasoning, apart from the answer ("" when the
                # model did not reason or the split does not apply).
                "thinking": reasoning_text,
                "continuable": self._compute_continuable(result, is_vlm),
                "peak_memory_mb": round(result.get("peak_memory_mb", 0), 1),
                "prompt_tps": round(prompt_tps, 1),
                # Timing breakdown
                "timing": {
                    "prefill_ms": prefill_ms,      # Time to process new tokens
                    "generation_ms": generation_ms, # Time to generate output
                    "overhead_ms": max(0, overhead_ms),  # Overhead
                },
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "MLXChatNode error after %dms: %s",
                elapsed_ms,
                str(e)
            )
            raise


    @property
    def _vlm(self) -> "MLXVisionRunner":
        """The VLM runner, built on first use.

        LAZY on purpose, not built in `__init__`: the suite creates nodes with
        `MLXChatNode.__new__(MLXChatNode)` to skip config loading, and
        with eager construction those nodes were left without `_vlm`. A node
        has to keep working exactly the same however it was
        built — which is what it did before #966.
        """
        runner = self.__dict__.get("_vlm_runner")
        if runner is None:
            runner = MLXVisionRunner(self)
            self.__dict__["_vlm_runner"] = runner
        return runner

    # ── VLM path (#966 slice A) ──────────────────────────────────────────────
    # The bodies live in `vlm_runner.MLXVisionRunner`. These delegators
    # keep the names so existing calls (and the suite) do not change.
    # The two `staticmethod`s stay that way: the suite calls them on the
    # CLASS (`MLXChatNode._reset_rotated_vlm_state(state)`).

    def _normalize_image_input(self, raw) -> bytes:
        return self._vlm._normalize_image_input(raw)

    def _prepare_vlm_prompt(self, messages: List[Dict], system: str, processor, has_image: bool, thinking_enabled: bool=True, max_tokens: Optional[int]=None, continue_final: bool=False) -> str:
        return self._vlm._prepare_vlm_prompt(messages, system, processor, has_image, thinking_enabled, max_tokens, continue_final)

    def _log_vlm_kv_request(self, model, prompt_cache_state=None) -> None:
        return self._vlm._log_vlm_kv_request(model, prompt_cache_state)

    def _run_vlm_streaming(self, model, processor, formatted_prompt: str, tmp_path: Optional[str], max_tokens: Optional[int], stream_callback: Callable[[str], None], cancel_event: Any=None, prompt_cache_state: Any=None, temperature: Optional[float]=None, top_p: Optional[float]=None):
        return self._vlm._run_vlm_streaming(model, processor, formatted_prompt, tmp_path, max_tokens, stream_callback, cancel_event, prompt_cache_state, temperature, top_p)

    def _run_vlm_oneshot(self, model, processor, formatted_prompt: str, tmp_path: Optional[str], max_tokens: Optional[int], temperature: Optional[float]=None, top_p: Optional[float]=None):
        return self._vlm._run_vlm_oneshot(model, processor, formatted_prompt, tmp_path, max_tokens, temperature, top_p)

    def _extract_vlm_metrics(self, result_obj, result_text: str, elapsed_ms: int, prefix_reused: bool=False, cached_tokens: int=0, identity_hash: str='', max_tokens_used: 'Optional[int]'=None, eos_ids: frozenset=frozenset()) -> Dict[str, Any]:
        return self._vlm._extract_vlm_metrics(result_obj, result_text, elapsed_ms, prefix_reused, cached_tokens, identity_hash, max_tokens_used, eos_ids)

    def _generate_vlm(self, system: str, messages: List[Dict], images: List[bytes], stream_callback: Optional[Callable[[str], None]]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, thinking_enabled: bool=True, cancel_event: Any=None, session_id: str='default', top_p: Optional[float]=None, continue_final: bool=False) -> Dict[str, Any]:
        return self._vlm._generate_vlm(system, messages, images, stream_callback, max_tokens, temperature, thinking_enabled, cancel_event, session_id, top_p, continue_final)

    _reset_rotated_vlm_state = staticmethod(MLXVisionRunner._reset_rotated_vlm_state)
    _reset_untrimmable_vlm_state = staticmethod(MLXVisionRunner._reset_untrimmable_vlm_state)







    async def _answer_or_retry_without_thinking(
        self, loop, result: Dict[str, Any], *, thinking_enabled: bool,
        is_vlm: bool, system: str, messages: List[Dict],
        messages_for_cache: List[Dict], images, callback, session_id: str,
        max_tokens, temperature, top_p, cancel_event, continue_final,
    ) -> Dict[str, Any]:
        """Return ``result``, or a second generation of the same turn with
        reasoning off when the first one starved the answer (#984).

        The retry keeps the dispatch of the first pass — a VLM-capable model
        routes every turn through the vision runner, image or not — and flips
        the one flag that matters. It runs at most once per turn, so a retry
        that starves again is returned as it is rather than chained.

        A turn the user stopped is never retried: Stop means stop, and the
        engine must not answer back with a generation nobody asked for.
        """
        if cancel_event is not None and cancel_event.is_set():
            return result
        if not self._answer_starved_by_thinking(
            result.get("text", ""), result.get("finish_reason"), thinking_enabled,
            self._template_opens_think(),
        ):
            return result
        logger.warning(
            "MLXChatNode: the ceiling cut the turn inside <think> and left no "
            "answer — retrying once with thinking disabled (#984)"
        )
        # Close the reasoning block the starved pass left open, or the retry's
        # answer is invisible. The web UI's think parser carries `in_think`
        # across chunks (_process_content_think_tags): an unclosed <think>
        # leaves it True, and every token that follows — the whole retry — is
        # swallowed as reasoning. Emitting the closer is the mirror of the
        # synthetic <think> opener vlm_runner already emits for templates that
        # inject the tag into the prompt.
        if callback is not None:
            callback("</think>\n")
        if is_vlm:
            retry = functools.partial(
                self._generate_vlm,
                system, messages, images or [],
                callback,
                max_tokens, temperature,
                False,  # thinking off — the whole point of the retry
                cancel_event,
                session_id,
                top_p=top_p,
            )
        else:
            retry = functools.partial(
                self._generate_blocking,
                system,
                messages,
                messages_for_cache,
                callback,
                session_id,
                max_tokens,
                temperature,
                False,  # thinking off — the whole point of the retry
                cancel_event,
                top_p=top_p,
                continue_final=continue_final,
            )
        try:
            retried = await loop.run_in_executor(_MLX_EXECUTOR, retry)
        except Exception as exc:  # noqa: BLE001 — degrade to pass 1, never lose the turn
            logger.error(
                "MLXChatNode: the no-thinking retry failed (%s) — keeping the "
                "reasoning-only turn rather than failing the request (#984)", repr(exc),
            )
            return result
        return {**retried, "thinking_retry": True}

    async def _reasoning_split(self, loop, is_vlm: bool, thinking_enabled: bool,
                               continue_final: bool) -> Optional[Dict[str, bool]]:
        """How this turn's text is split into reasoning and answer (ADR-010).

        None for `continue_final`: FD-S6 resumes a truncated turn from its
        exact raw text, the legacy path that dies at C4.6 — left untouched.
        gpt-oss writes harmony channels. A text-path template that opens
        <think> in the prompt means the model starts INSIDE the block (the VLM
        runner re-emits a synthetic opener itself, so it does not).
        """
        if continue_final:
            return None
        harmony = "gpt-oss" in str(self.config.model_path).lower()
        starts_inside = False
        if thinking_enabled and not is_vlm and not harmony:
            # the probe may load the model: MLX work stays on its own thread
            # `is True`: a probe that cannot answer must not change the turn
            starts_inside = (await loop.run_in_executor(_MLX_EXECUTOR, self._template_opens_think)) is True
        return {"starts_inside": starts_inside, "harmony": harmony}

    def _template_opens_think(self) -> bool:
        """Whether this model's chat template pre-opens ``<think>`` in the prompt.

        A property of the template, not of the turn, so it is resolved once per
        loaded model and reset alongside the other per-model singletons. Qwen3 /
        Qwen3.5 / Gemma-4 end the prompt with ``assistant\\n<think>\\n``, which
        means the model's OWN output carries no opening tag — only the closer.
        Without this, starvation on the text path is invisible: the VLM runner
        prepends a synthetic opener, the text runner does not.
        """
        cached = MLXChatNode._template_think_prefix
        if cached is not None:
            return cached
        value = False
        try:
            _, tokenizer = self._get_model()
            prompt = tokenizer.apply_chat_template(
                [{"role": "user", "content": "x"}],
                add_generation_prompt=True, tokenize=False,
            )
            if isinstance(prompt, str):
                value = _prompt_has_open_think_prefix(prompt)
        except Exception as exc:  # noqa: BLE001 — detection must never break a turn
            logger.debug("MLXChatNode: could not probe the chat template: %s", exc)
        MLXChatNode._template_think_prefix = value
        return value

    @staticmethod
    def _answer_starved_by_thinking(
        text: str, finish_reason: "str | None", thinking_enabled: bool,
        block_opened_by_prompt: bool = False,
    ) -> bool:
        """True when the ceiling ended the turn inside the reasoning (#984).

        Measured on Qwen3.5-9B: the turn stops at ``length`` with the reasoning
        block never closed, so every token generated is reasoning and the user
        is left with a paragraph cut mid-sentence and no answer — and no
        Continue either, because a VLM-capable model disables it.

        The block counts as open whether the tag came from the model or from
        the template (``block_opened_by_prompt``): Qwen-family templates inject
        it into the prompt, so on the text path the output carries no opener at
        all and only this flag can tell starvation from a plain answer cut
        mid-sentence.

        A closed block means the answer began, however short: that turn was cut
        while ANSWERING, which is what Continue is for.

        Not covered: reasoning conventions that use neither tag — Gemma-4's
        ``<|channel|>thought`` and gpt-oss's harmony ``analysis`` channel. Those
        starve the same way and this returns False for them.
        """
        if not thinking_enabled or finish_reason != "length":
            return False
        if "</think>" in text:
            return False
        return block_opened_by_prompt or "<think>" in text

    def _compute_continuable(self, result: Dict[str, Any], is_vlm: bool) -> bool:
        """Whether a truncated answer can be resumed with a Continue (FD-S6).

        Both paths since C4.6: the VLM path resumes with
        `continue_final_message`, and its "length" now excludes an answer
        whose last token was an end of turn (`_extract_vlm_metrics`). `is_vlm`
        no longer decides; it stays in the signature for the callers. The KV
        gate keeps a Continue chain from crossing the rotating window (which
        would evict the system prompt and degenerate mid-chain, B004) and from
        hitting the untrimmable-when-full corner of RotatingKVCache.
        """
        if result.get("finish_reason") != "length":
            return False
        used = result.get("prompt_tokens", 0) + result.get("tokens", 0)
        headroom_needed = used + self.config.max_tokens + 512
        return headroom_needed < self.config.max_kv_size



    @property
    def _text(self) -> "MLXTextRunner":
        """Lazy, like `_vlm`: the suite creates nodes with `__new__`."""
        runner = self.__dict__.get("_text_runner")
        if runner is None:
            runner = MLXTextRunner(self)
            self.__dict__["_text_runner"] = runner
        return runner

    # ── Text path (#966 slice C) ─────────────────────────────────────────────
    # The bodies live in `text_runner.MLXTextRunner`; these delegators
    # keep the names and signatures so existing calls do not change.

    def _generate_blocking(self, system: str, messages: List[Dict], messages_for_cache: List[Dict], stream_callback: Optional[Callable[[str], None]], session_id: str='default', max_tokens: Optional[int]=None, temperature: Optional[float]=None, thinking_enabled: bool=True, cancel_event: Any=None, top_p: Optional[float]=None, continue_final: bool=False) -> Dict[str, Any]:
        return self._text._generate_blocking(system, messages, messages_for_cache, stream_callback, session_id, max_tokens, temperature, thinking_enabled, cancel_event, top_p, continue_final)

    def _generate_blocking_inner(self, system: str, messages: List[Dict], messages_for_cache: List[Dict], stream_callback: Optional[Callable[[str], None]], session_id: str='default', max_tokens: Optional[int]=None, temperature: Optional[float]=None, thinking_enabled: bool=True, cancel_event: Any=None, top_p: Optional[float]=None, continue_final: bool=False) -> Dict[str, Any]:
        return self._text._generate_blocking_inner(system, messages, messages_for_cache, stream_callback, session_id, max_tokens, temperature, thinking_enabled, cancel_event, top_p, continue_final)


    @classmethod
    def reset_model(cls) -> None:
        """Destroy model, tokenizer and all caches."""
        with cls._lock:
            _free_prompt_caches()

            # Destroy model
            if cls._model is not None:
                del cls._model
                cls._model = None

            if cls._tokenizer is not None:
                del cls._tokenizer
                cls._tokenizer = None

            cls._config = None

            # Release memory
            try:
                import mlx.core as mx
                mx.clear_cache()  # Replaces mx.metal.clear_cache (deprecated)
            except Exception as e:
                logger.warning("MLXChatNode: error clearing cache: %s", e)

            gc.collect()
            logger.info("MLXChatNode: model and all caches reset")

    @classmethod
    def get_pool_stats(cls) -> Dict[str, Any]:
        """Return cache statistics."""
        # Get cache manager stats
        cache_manager_stats = {}
        try:
            from .prompt_cache_manager import get_prompt_cache_manager
            cache_manager = get_prompt_cache_manager()
            cache_manager_stats = cache_manager.get_stats()
        except Exception as e:
            logger.debug("MLX stats collection failed: %s", e)  # nosec B110 - Stats optional

        return {
            "model_loaded": cls._model is not None,
            "model_path": cls._config.model_path if cls._config else None,
            "max_kv_size": cls._config.max_kv_size if cls._config else 0,
            "cache_manager": cache_manager_stats,
        }
