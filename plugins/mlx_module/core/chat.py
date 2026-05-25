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
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import MLXConfig
from ..exceptions import MissingDependencyError
from .generate_helpers import (
    prepare_tokens,
    lookup_prefix_cache,
    determine_tokens_to_process,
    run_streaming_generation,
    save_cache_post_generation,
    extract_metrics,
)
from core.utils import compute_system_hash

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

# F3.3 BUG-NB-8: register an atexit cleanup so the dedicated MLX worker doesn't
# linger as a non-daemon thread on shutdown. `wait=False` + `cancel_futures=True`
# lets us tear down even when a generation is mid-flight (Stop button race,
# sidecar SIGTERM). Without this, the interpreter may hang at exit waiting for
# the executor thread to drain.
atexit.register(_MLX_EXECUTOR.shutdown, wait=False, cancel_futures=True)


# Known VLM architectures (config.json → architectures[])
_VLM_ARCHITECTURES = {
    # Qwen VL family
    "Qwen2VLForConditionalGeneration",
    "Qwen2_5_VLForConditionalGeneration",
    "Qwen3VLForConditionalGeneration",
    "Qwen3_5MoeForConditionalGeneration",
    # Llava family
    "LlavaNextForConditionalGeneration",
    "LlavaForConditionalGeneration",
    "LlavaOnevisionForConditionalGeneration",
    # Google
    "PaliGemmaForConditionalGeneration",
    "Gemma3ForConditionalGeneration",
    "Gemma4ForConditionalGeneration",
    # InternVL
    "InternVLChatModel",
    "InternVL2ChatModel",
    # Others
    "MiniCPMV",
    "Idefics3ForConditionalGeneration",
    "MllamaForConditionalGeneration",
}


# Vision key patterns in the safetensors weight map (fallback when architecture is unknown)
_VLM_WEIGHT_PATTERNS = (
    "vision_tower",
    "vision_model",
    "visual.",
    "mm_projector",
    "image_newline",
    "patch_embed",
)


def _require_torch() -> None:
    """Verifies that torch is available; raises MissingDependencyError if not."""
    try:
        import torch  # noqa: F401
    except ImportError as exc:
        raise MissingDependencyError(
            "This VL model requires PyTorch. "
            "Reinstall server-nexe to get the full bundle."
        ) from exc


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


QWEN35_THINKING_DIRECTIVE = (
    "[CRITICAL INSTRUCTION]\n"
    "You MUST reason step-by-step inside <think>...</think> tags before "
    "answering. Always think first, even for simple greetings. This is a "
    "strict, non-negotiable requirement that overrides every other rule "
    "in this system prompt.\n"
    "[/CRITICAL INSTRUCTION]"
)


def _qwen35_needs_thinking_directive(model_type: str, thinking_enabled: bool) -> bool:
    """Decide if the Qwen3.5 thinking-force directive must be injected.

    Empirical incident 2026-05-13: with Raonament=ON the Qwen3.5 family on
    MLX silently skips reasoning in multi-turn conversations. Root cause is
    *not* the chat template (which already pre-opens ``<think>`` by default)
    but the model itself: when the prior assistant turns in the history
    contain no ``<think>...</think>`` blocks, Qwen3.5 mimics that pattern
    and emits ``</think>`` right after the prompt opener, producing a direct
    answer with no visible reasoning box on the client.

    The fix is scoped to ``model_type startswith 'qwen3_5'`` only, per
    Jordi's explicit instruction:

    - gpt-oss: uses native ``<|channel|>analysis<|message|>`` reasoning,
      already works on MLX.
    - gemma-4: no thinking support in the family.
    - other Qwen (qwen2, qwen3 base): not currently bundled; explicit guard
      against false positives.

    Returns True iff (a) the toggle is ON, (b) the model is Qwen3.5.
    """
    if not thinking_enabled:
        return False
    return model_type.startswith("qwen3_5")


def _inject_thinking_directive_into_messages(
    messages: List[Dict[str, Any]], directive: str
) -> List[Dict[str, Any]]:
    """Return a copy of ``messages`` with ``directive`` reinforcing thinking.

    The directive is **prepended** to the system message content (not
    appended) so it stays visible at the top of long system prompts —
    empirically the Nexe system prompt is ~4000 chars, and appending the
    directive at the end caused the model to ignore it (lost in context).
    If no system message exists, a new one is inserted at index 0.

    The original list is not mutated.
    """
    if not directive:
        return messages
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        existing = str(first.get("content") or "").strip()
        first["content"] = f"{directive}\n\n{existing}" if existing else directive
        return [first, *messages[1:]]
    return [{"role": "system", "content": directive}, *messages]


def _sanitize_safetensors_index(model_path: str) -> bool:
    """Disable a safetensors index that declares shards which do not exist.

    Known upstream-HuggingFace mislabeling pattern (empirically detected
    2026-05-13 with ``mlx-community/gemma-3-4b-it-4bit``): the repo ships a
    single ``model.safetensors`` (~3.4 GB) but ``model.safetensors.index.json``
    declares a multi-shard layout (``model-00001-of-00002.safetensors`` +
    ``model-00002-of-00002.safetensors``) pointing at files that don't exist
    in the repo at all. ``mlx_lm.load`` then tries to open the declared shards
    and raises ``FileNotFoundError``, with the user-facing symptom being a
    silent failure to load this otherwise-valid model.

    The fix that mlx-lm itself uses internally (when no index is present): load
    ``model.safetensors`` directly. Renaming the stale index to ``.stale``
    triggers exactly that fallback path. The original is preserved (not
    deleted) so an operator can inspect it or restore it after an upstream fix.

    Idempotent: re-running on a model that already has the index renamed (or
    no index at all) is a no-op. Failures during the JSON read are logged and
    treated as "do nothing" rather than blocking the load — the upstream
    ``mlx_lm.load`` will surface the real error if the model is truly broken.

    Returns
    -------
    bool
        True if a stale index was detected and disabled. False if no action
        was needed (no index, valid index, or read error).
    """
    if not model_path:
        return False
    root = Path(model_path)
    idx_path = root / "model.safetensors.index.json"
    if not idx_path.is_file():
        return False
    try:
        data = json.loads(idx_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "MLX %s: could not parse safetensors index for sanity check (%s) — "
            "leaving as-is and letting mlx_lm.load surface any error.",
            root.name, e,
        )
        return False
    weight_map = data.get("weight_map", {})
    if not weight_map:
        return False
    declared_shards = set(weight_map.values())
    missing = sorted(s for s in declared_shards if not (root / s).is_file())
    if not missing:
        return False
    bak = root / "model.safetensors.index.json.stale"
    try:
        idx_path.rename(bak)
    except OSError as e:
        logger.error(
            "MLX %s: stale safetensors index detected (declared shards %s do not "
            "exist) but rename to .stale failed: %s. Load may fail.",
            root.name, missing, e,
        )
        return False
    logger.warning(
        "MLX %s: stale safetensors index disabled — declared shards %s did not "
        "exist on disk (renamed to %s). Falling back to single-file load. This "
        "is a known upstream HuggingFace repo mislabeling; not a local corruption.",
        root.name, missing, bak.name,
    )
    return True


# vision_config alone is not sufficient — some non-VL models (e.g. Qwen3.5 MoE)
# include it as a config artefact without actual vision weights. Only trust it
# when the architecture name also contains one of these keywords.
_VLM_ARCH_KEYWORDS = (
    "vl", "vision", "visual", "llava", "intern",
    "qwen2vl", "qwen2_5_vl", "qwen3vl",
)


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON from path. Returns None if missing or unparseable."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:  # nosec B110: optional VLM inspection — fail-closed (return None)
        return None


def _vlm_from_config(config: Dict[str, Any]) -> bool:
    """Signal 1+2: VLM detection from config.json architectures + vision_config."""
    archs = set(config.get("architectures", []))
    if archs & _VLM_ARCHITECTURES:
        return True
    if "vision_config" in config and config.get("vision_config") and archs:
        arch_str = " ".join(archs).lower()
        return any(kw in arch_str for kw in _VLM_ARCH_KEYWORDS)
    return False


def _vlm_from_safetensors(root: Path) -> bool:
    """Signal 3: VLM detection from weight_map keys in safetensors index."""
    idx = _load_json_safe(root / "model.safetensors.index.json")
    if idx is None:
        return False
    wm = idx.get("weight_map", {})
    return any(
        any(p in key for p in _VLM_WEIGHT_PATTERNS)
        for key in wm
    )


def _detect_vlm_capability(model_path: str) -> bool:
    """Detects whether the model is a VLM by combining 3 signals (any-of):

    1. config.json → architectures[] contains a known VLM architecture
    2. config.json → contains vision_config (standard HF signal)
    3. model.safetensors.index.json → weight_map has vision keys (vision_tower,
       vision_model, visual., mm_projector, ...)

    The last step covers mislabeled models or new architectures.
    """
    if not model_path:
        return False
    root = Path(model_path)
    config = _load_json_safe(root / "config.json")
    if config is None:
        return False
    return _vlm_from_config(config) or _vlm_from_safetensors(root)


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

    def _get_model(self) -> tuple:
        """
        Get model and tokenizer/processor (lazy load singleton).
        Automatically branches between mlx_lm (text) and mlx_vlm (VLM) based on config.json.

        Returns:
            tuple: (model, tokenizer_or_processor)
        """
        if MLXChatNode._model is None:
            try:
                import psutil
                avail_gb = psutil.virtual_memory().available / (1024 ** 3)
                if avail_gb < 1.5:
                    _lang = os.environ.get("NEXE_LANG", "ca")[:2]
                    _oom_msgs = {
                        "ca": "Memòria insuficient per carregar el model d'IA. Tanca altres aplicacions per alliberar memòria i torna-ho a provar.",
                        "es": "Memoria insuficiente para cargar el modelo de IA. Cierra otras aplicaciones para liberar memoria e inténtalo de nuevo.",
                        "en": "Not enough memory to load the AI model. Close other applications to free up memory and try again.",
                    }
                    raise RuntimeError(_oom_msgs.get(_lang, _oom_msgs["en"]))
            except ImportError:
                pass

            # Disable a stale safetensors index before load (known upstream HF
            # mislabeling pattern — see _sanitize_safetensors_index docstring).
            _sanitize_safetensors_index(self.config.model_path)

            is_vlm = _detect_vlm_capability(self.config.model_path)
            MLXChatNode._is_vlm = is_vlm

            logger.info(
                "MLXChatNode: loading %s model %s (max_kv_size=%d)",
                "VLM" if is_vlm else "text",
                self.config.model_path[-50:] if self.config.model_path else "(empty)",
                self.config.max_kv_size
            )

            if is_vlm:
                try:
                    _require_torch()
                    from mlx_vlm import load
                    MLXChatNode._model, MLXChatNode._tokenizer = load(self.config.model_path)
                except MissingDependencyError:
                    # PyTorch not installed — load vision-capable model in text-only
                    # mode via mlx-lm. Vision weights are ignored; text inference works.
                    logger.warning(
                        "MLXChatNode: PyTorch unavailable — loading VLM %s in text-only mode",
                        self.config.model_path[-40:] if self.config.model_path else "(empty)",
                    )
                    MLXChatNode._is_vlm = False
                    from mlx_lm import load
                    MLXChatNode._model, MLXChatNode._tokenizer = load(self.config.model_path)
            else:
                from mlx_lm import load
                MLXChatNode._model, MLXChatNode._tokenizer = load(self.config.model_path)

            logger.info("MLXChatNode: model loaded successfully (vlm=%s)", is_vlm)

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
        thinking_enabled = inputs.get("thinking_enabled", True)  # True = model decides; False = force off
        images = inputs.get("images")  # Optional[List[bytes]] — VLM support
        # cancel_event: threading.Event-like; route handler sets it when the
        # HTTP client disconnects so streaming loops can break early instead
        # of running to max_tokens. None disables cancellation (back-compat).
        cancel_event = inputs.get("cancel_event")

        # Log for debugging
        logger.info(
            "MLXChatNode: session=%s, msgs=%d",
            session_id[:8] if session_id else "none",
            len(messages)
        )

        # Capture event loop for thread-safe streaming
        loop = asyncio.get_running_loop()

        def threadsafe_callback(text: str) -> None:
            """Bridge streaming tokens from the MLX worker thread to the async event loop."""
            if stream_callback and callable(stream_callback):
                loop.call_soon_threadsafe(stream_callback, text)

        try:
            # VLM path: if the model is a VLM, all generation goes through mlx_vlm.
            # We use _detect_vlm_capability (reads config.json of the current model) as
            # the primary source — it is always fresh and does not depend on the _is_vlm
            # singleton which can go stale when switching from VLM → text within the same session.
            is_vlm = _detect_vlm_capability(self.config.model_path)
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
                    ),
                )

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
                "response": result["text"],
                "model_used": self.config.model_path,
                "elapsed_ms": elapsed_ms,
                "tokens": result["tokens"],
                "tokens_per_second": round(generation_tps, 1),
                "prompt_tokens": result["prompt_tokens"],
                "context_used": context_used,
                "system_tokens": system_tokens,
                "system_prompt": system,
                "cache_active": result.get("cache_active", False),  # Compatibility alias
                "prefix_reuse": prefix_reuse,  # True = prefix matching succeeded
                "reuse_ratio": round(reuse_ratio, 2),  # Cached/new tokens ratio
                "cached_tokens": cached_tokens,  # Tokens reused from cache
                "actual_prefill_tokens": actual_prefill,  # Tokens actually processed
                "identity_hash": result.get("identity_hash", ""),  # System prompt hash
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
    ) -> str:
        """Build the VLM prompt with thinking control.

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
        from mlx_vlm.prompt_utils import apply_chat_template

        try:
            with open(
                os.path.join(self.config.model_path, "config.json")
            ) as _cf:
                mdl_config = json.load(_cf)
        except Exception:
            mdl_config = {"model_type": ""}

        all_messages: List[Dict[str, Any]] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        if messages:
            all_messages.extend(messages)

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

        prompt_arg = all_messages if all_messages else ""
        num_images = 1 if has_image else 0

        if not thinking_enabled:
            try:
                return apply_chat_template(
                    processor=processor,
                    config=mdl_config,
                    prompt=prompt_arg,
                    num_images=num_images,
                    enable_thinking=False,
                )
            except TypeError:
                pass  # processor template does not support enable_thinking — fall through

        return apply_chat_template(
            processor=processor,
            config=mdl_config,
            prompt=prompt_arg,
            num_images=num_images,
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
        for chunk in vlm_stream(
            model=model,
            processor=processor,
            image=tmp_path,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.config.max_tokens,
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

    def _run_vlm_oneshot(
        self,
        model,
        processor,
        formatted_prompt: str,
        tmp_path: Optional[str],
        max_tokens: Optional[int],
    ):
        from mlx_vlm import generate as vlm_generate

        one = vlm_generate(
            model=model,
            processor=processor,
            image=tmp_path,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.config.max_tokens,
            verbose=False,
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
            "prefix_reused": False,
            "cached_tokens": 0,
            "actual_prefill_tokens": prompt_tokens,
            "prompt_tps": round(prompt_tps, 1),
            "peak_memory_mb": round(peak_memory, 1),
            "identity_hash": "",
            "vlm": True,
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
        )

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
                result_text, result_obj = self._run_vlm_streaming(
                    model, processor, formatted_prompt, tmp_path,
                    max_tokens, stream_callback, cancel_event,
                )
            else:
                result_text, result_obj = self._run_vlm_oneshot(
                    model, processor, formatted_prompt, tmp_path, max_tokens,
                )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        elapsed_ms = int((time.time() - start_time) * 1000)
        return self._extract_vlm_metrics(result_obj, result_text, elapsed_ms)

    def _generate_blocking(
        self,
        system: str,
        messages: List[Dict],
        messages_for_cache: List[Dict],
        stream_callback: Optional[Callable[[str], None]],
        session_id: str = "default",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        thinking_enabled: bool = True,
        cancel_event: Any = None,
    ) -> Dict[str, Any]:
        """
        Blocking generation with MLX and PREFIX MATCHING (executed in thread).

        Helpers in generate_helpers.py.
        """
        with MLXChatNode._lock:
            return self._generate_blocking_inner(
                system, messages, messages_for_cache,
                stream_callback, session_id, max_tokens, temperature,
                thinking_enabled, cancel_event,
            )

    def _generate_blocking_inner(
        self,
        system: str,
        messages: List[Dict],
        messages_for_cache: List[Dict],
        stream_callback: Optional[Callable[[str], None]],
        session_id: str = "default",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        thinking_enabled: bool = True,
        cancel_event: Any = None,
    ) -> Dict[str, Any]:
        """Inner generation logic, called under lock."""
        from mlx_lm.sample_utils import make_sampler
        from .prompt_cache_manager import get_prompt_cache_manager

        model, tokenizer = self._get_model()
        cache_manager = get_prompt_cache_manager(max_size=8)

        # Model key for cache (path + identity_hash + session_id)
        identity_hash = compute_system_hash(system)
        session_key = session_id[:8] if session_id else "default"
        model_key = f"{self.config.model_path}:{identity_hash}:{session_key}"

        # Read model_type once for the Qwen3.5 thinking-force directive.
        # Cheap read (single JSON load) and safe to fail to empty string —
        # the directive helper guards against blank/unknown model_type.
        try:
            with open(Path(self.config.model_path) / "config.json") as _cf:
                model_type = str(json.load(_cf).get("model_type", ""))
        except OSError:
            model_type = ""

        # 1. Prepare tokens (tokenization + sanitization)
        full_tokens, cache_lookup_tokens, all_messages, all_cache_messages = prepare_tokens(
            system, messages, messages_for_cache, tokenizer,
            thinking_enabled=thinking_enabled,
            model_type=model_type,
        )
        total_tokens = len(full_tokens)

        # 2. Lookup prefix cache
        cached_kv, cached_token_count, prefix_reused = lookup_prefix_cache(
            cache_manager, model_key, cache_lookup_tokens, model, self.config.max_kv_size
        )

        logger.info(
            "MLXChatNode: identity=%s, full=%d, cached=%d, new=%d, prefix_reuse=%s",
            identity_hash[:8], total_tokens, cached_token_count,
            total_tokens - cached_token_count, "YES" if prefix_reused else "NO"
        )

        # 3. Determine tokens to process
        tokens_to_process, new_tokens = determine_tokens_to_process(
            full_tokens, cached_token_count, prefix_reused
        )

        # 4. Create sampler
        sampler = make_sampler(temp=temperature if temperature is not None else self.config.temperature, top_p=self.config.top_p)

        # 5. Run generation with streaming
        text, last_response, _ = run_streaming_generation(
            model, tokenizer, tokens_to_process, max_tokens if max_tokens is not None else self.config.max_tokens,
            sampler, cached_kv, stream_callback,
            cache_manager, model_key, cache_lookup_tokens,
            model_path=self.config.model_path,
            cancel_event=cancel_event,
        )

        # 6. Save cache post-generation (clean messages, without memory context)
        save_cache_post_generation(
            cache_manager, model_key, all_cache_messages,
            text, tokenizer, cached_kv, len(full_tokens)
        )

        # 7. Extract and return metrics
        return extract_metrics(
            last_response, text, prefix_reused, cached_token_count,
            total_tokens, new_tokens, identity_hash
        )

    @classmethod
    def reset_model(cls) -> None:
        """Destroy model, tokenizer and all caches."""
        with cls._lock:
            # Clear cache manager (prefix matching)
            try:
                from .prompt_cache_manager import get_prompt_cache_manager
                cache_manager = get_prompt_cache_manager()
                cache_manager.clear()
            except Exception as e:
                logger.warning("MLXChatNode: error clearing cache manager: %s", e)

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
