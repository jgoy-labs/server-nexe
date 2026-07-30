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
from plugins._shared.chat_node import make_threadsafe_callback, base_chat_result

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


# Minimum usable KV window for the hard-refusal check (= B004 budget floor
# rationale: below this a normal conversation degenerates anyway).
_KV_MIN_TOKENS = 4096


def _estimate_required_ram(model_path: str, max_kv_size: int) -> dict:
    """Estimate the RAM (GB) an MLX load will actually occupy.

    Field-verified formula (M1 8 GB, 2026-07-23): footprint = weights +
    max_kv_size × kv_bytes_per_token + runtime baseline, and the footprint is
    FLAT during generation — the cost is the model plus the KV window, not
    the act of generating. Uses the same helpers as the B004 budget
    (config.model_kv_bytes_per_token with ``effective=True`` so
    linear-attention/sliding-window models are not over-estimated 4-6×).

    Returns a dict: ``weights`` (GB or None when not measurable), ``kv``,
    ``kv_min`` (the smallest usable window), ``required``. The old
    ``×1.2+0.6`` heuristic came from a budget table never contrasted with a
    real low-RAM machine — it refused loads that in fact succeeded (guard
    demanded 3.99 GB available; the machine ran fine at 1.91).
    """
    from .config import _RUNTIME_GB, model_kv_bytes_per_token, model_weights_gb

    weights = model_weights_gb(model_path)
    bpt = model_kv_bytes_per_token(model_path, effective=True)
    kv = bpt * max_kv_size / (1024 ** 3)
    kv_min = bpt * min(_KV_MIN_TOKENS, max_kv_size) / (1024 ** 3)
    required = max(1.5, (weights if weights is not None else 3.5) + kv + _RUNTIME_GB)
    return {"weights": weights, "kv": kv, "kv_min": kv_min, "required": required}


def _ram_guard_mode() -> str:
    """Read the pre-load RAM guard mode from ``NEXE_MLX_RAM_GUARD``.

    ``warn`` (default since 2026-07-23) logs and loads anyway, ``strict``
    refuses on the soft threshold, ``off`` loads anyway and stays quiet.
    Field measurement (M1 8 GB): ``available`` does not predict whether a
    load will work — macOS compresses and swaps pages the metric ignores
    (footprint 6.05 GB ran fine with available at 1.91), so refusing by
    default punished loads that succeed. The physically-impossible case
    (weights + minimum KV window > TOTAL RAM) still hard-refuses even in
    ``warn``. ``0``/``false``/``no`` are accepted as synonyms of ``off`` —
    they are what anyone actually types to disable a guard. Anything else
    unknown falls back to ``warn``.

    Note: ``off`` does NOT skip the work — the estimate, the psutil read and the
    diagnostic line still happen (that is the point: the numbers are what a
    field report needs). Only the refusal is suppressed.

    The escape hatch exists because a refusal was a dead end: there was no way
    for the user (or for a field measurement) to say "I know, try anyway", so
    nobody could ever check whether the threshold was refusing loads that would
    in fact have succeeded.
    """
    import os as _os_mode  # noqa: PLC0415
    raw = _os_mode.environ.get("NEXE_MLX_RAM_GUARD", "warn").strip().lower()
    if raw in ("0", "false", "no", "disabled"):
        return "off"
    return raw if raw in ("strict", "warn", "off") else "warn"


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


def _memory_snapshot_gb(vm: Any) -> Dict[str, float]:
    """Extract a full memory picture (GB) from a psutil vmem tuple, defensively.

    Any missing or non-numeric attribute becomes ``-1.0`` so that the diagnostic
    log line can never raise from inside the guard (tests and older psutil
    builds do not necessarily expose every macOS field).
    """
    snapshot: Dict[str, float] = {}
    for field in ("total", "available", "free", "active", "inactive", "wired"):
        try:
            snapshot[field] = float(getattr(vm, field)) / (1024 ** 3)
        except (AttributeError, TypeError, ValueError):
            snapshot[field] = -1.0
    return snapshot


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

    def apply_config(self, new_config: "MLXConfig") -> None:
        """Hot-swap the active model config and invalidate the class singletons.

        Mirrors the reset that __init__ performs when the model path changes:
        swaps the shared _config, drops the cached _model so the next
        _get_model() reloads, and resets _is_vlm for re-detection. Public entry
        point so web_ui calls MLXModule.switch_model() instead of reaching into
        these class-level privates directly (B073).
        """
        self.config = new_config
        MLXChatNode._config = new_config
        MLXChatNode._model = None
        MLXChatNode._is_vlm = False

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
                _vm = psutil.virtual_memory()
                avail_gb = _vm.available / (1024 ** 3)
                # Field-verified estimate (2026-07-23): weights + KV window +
                # runtime, via the same B004 helpers as the budget — never a
                # local copy of the formula.
                _est = _estimate_required_ram(
                    self.config.model_path, self.config.max_kv_size
                )
                required_gb = _est["required"]
                _mode = _ram_guard_mode()
                _below = avail_gb < required_gb
                # Diagnostic BEFORE the decision. The 1.0.7 threshold was derived
                # from a budget table and never contrasted with a measurement on
                # a real low-RAM machine, so the log has to carry the whole
                # picture and not just `available`: on macOS psutil reports
                # `available` as inactive+free, which ignores purgeable and
                # compressor-reclaimable pages the kernel would hand over on
                # demand. Without these numbers a field report cannot tell a
                # justified refusal from an over-conservative one.
                _snap = _memory_snapshot_gb(_vm)
                logger.log(
                    logging.WARNING if _below else logging.INFO,
                    "MLX RAM guard [%s]: need ~%.2f GB (weights %s + kv %.2f + runtime) · "
                    "available %.2f GB · "
                    "total %.2f · free %.2f · inactive %.2f · active %.2f · wired %.2f (GB) · model=%s",
                    _mode, required_gb,
                    f"{_est['weights']:.2f}" if _est["weights"] is not None else "?",
                    _est["kv"], avail_gb, _snap["total"], _snap["free"],
                    _snap["inactive"], _snap["active"], _snap["wired"],
                    self.config.model_path,
                )
                # Hard refusal — the only one the default (warn) mode keeps:
                # weights + a minimum usable KV window do not fit in TOTAL
                # RAM. Not "low available" (macOS reclaims pages on demand):
                # guaranteed thrash/jetsam. Skipped when the weights could
                # not be measured (a fallback guess must never refuse) or
                # when total is unknown (defensive psutil / test mocks).
                _total_known = (
                    isinstance(_snap["total"], (int, float)) and _snap["total"] > 0
                )
                _impossible = (
                    _est["weights"] is not None
                    and _total_known
                    and _est["weights"] + _est["kv_min"] > _snap["total"]
                )
                if _impossible and _mode != "off":
                    import os as _os_oom  # noqa: PLC0415
                    _lang = _os_oom.environ.get("NEXE_LANG", "en")[:2]
                    # Contract: routes_chat._is_oom detects OOM by substring
                    # and _oom_notice keeps the switch-engine advice only when
                    # "MLX" appears in the text (pinned by contract test).
                    _hard_msgs = {
                        "ca": (
                            "Memòria insuficient: aquest model no cap a la RAM "
                            f"d'aquest Mac amb MLX (pesos ~{_est['weights']:.1f} GB "
                            f"+ context mínim ~{_est['kv_min']:.1f} GB > "
                            f"{_snap['total']:.0f} GB totals). Fes servir Ollama "
                            "per a aquest model."
                        ),
                        "es": (
                            "Memoria insuficiente: este modelo no cabe en la RAM "
                            f"de este Mac con MLX (pesos ~{_est['weights']:.1f} GB "
                            f"+ contexto mínimo ~{_est['kv_min']:.1f} GB > "
                            f"{_snap['total']:.0f} GB totales). Usa Ollama "
                            "para este modelo."
                        ),
                        "en": (
                            "Not enough memory: this model cannot fit in this "
                            f"Mac's RAM with MLX (weights ~{_est['weights']:.1f} GB "
                            f"+ minimum context ~{_est['kv_min']:.1f} GB > "
                            f"{_snap['total']:.0f} GB total). Use Ollama "
                            "for this model."
                        ),
                    }
                    raise RuntimeError(_hard_msgs.get(_lang, _hard_msgs["en"]))
                elif _below and _mode == "warn":
                    logger.warning(
                        "MLX RAM guard: below threshold (need ~%.1f GB, have ~%.1f GB) "
                        "but mode is warn — loading anyway",
                        required_gb, avail_gb,
                    )
                elif _below and _mode == "strict":
                    logger.warning(
                        "MLXChatNode: refusing to load — need ~%.1f GB, have ~%.1f GB available",
                        required_gb, avail_gb,
                    )
                    import os as _os_oom  # noqa: PLC0415
                    _lang = _os_oom.environ.get("NEXE_LANG", "en")[:2]
                    _oom_msgs = {
                        "ca": "Memòria insuficient per carregar el model amb MLX. Canvia el motor a Ollama (fa servir molta menys memòria) o tanca altres aplicacions i torna-ho a provar.",
                        "es": "Memoria insuficiente para cargar el modelo con MLX. Cambia el motor a Ollama (usa mucha menos memoria) o cierra otras aplicaciones e inténtalo de nuevo.",
                        "en": "Not enough memory to load the model with MLX. Switch the engine to Ollama (it uses far less memory) or close other applications and try again.",
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

            # The lazy imports are wrapped so a broken dependency combo
            # surfaces as a curated message, not a raw AttributeError deep in
            # transformers (finding 820: an old bundle shipping
            # transformers>=5.13 died at mlx_lm's tokenizer registration with
            # "'str' object has no attribute '__module__'").
            def _curated_import_error(exc):
                return RuntimeError(
                    "MLX engine unavailable: incompatible dependency "
                    "(transformers/mlx-lm — finding 820). Reinstall "
                    "server-nexe or switch the engine to Ollama."
                )

            if is_vlm:
                try:
                    _require_torch()
                    try:
                        from mlx_vlm import load
                    except (ImportError, AttributeError) as exc:
                        raise _curated_import_error(exc) from exc
                    MLXChatNode._model, MLXChatNode._tokenizer = load(self.config.model_path)
                except MissingDependencyError:
                    # PyTorch not installed — load vision-capable model in text-only
                    # mode via mlx-lm. Vision weights are ignored; text inference works.
                    logger.warning(
                        "MLXChatNode: PyTorch unavailable — loading VLM %s in text-only mode",
                        self.config.model_path[-40:] if self.config.model_path else "(empty)",
                    )
                    MLXChatNode._is_vlm = False
                    try:
                        from mlx_lm import load
                    except (ImportError, AttributeError) as exc:
                        raise _curated_import_error(exc) from exc
                    MLXChatNode._model, MLXChatNode._tokenizer = load(self.config.model_path)
            else:
                try:
                    from mlx_lm import load
                except (ImportError, AttributeError) as exc:
                    raise _curated_import_error(exc) from exc
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
            is_vlm = _detect_vlm_capability(self.config.model_path)
            if continue_final and is_vlm:
                # FD-S6 scope: mlx_vlm does the prefix matching internally on
                # the real input_ids and has no continue support — phase 1 is
                # text-only by design (D-C).
                raise ValueError(
                    "continue_final is not supported on the VLM path"
                )
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
                    response=result["text"],
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

    @staticmethod
    def _reset_rotated_vlm_state(prompt_cache_state) -> bool:
        """Review #826 (major): mai reutilitzar un RotatingKVCache ja rotat.

        Amb max_kv_size, mlx_vlm crea RotatingKVCache al 1r torn; el camí de
        reuse (generate.py) trima amb semàntica de KVCache PLA
        (`keys[:, :, :prefix_len]` + offset) — un cop el buffer ha rotat,
        aquest trim conserva brossa entrellaçada com a "prefix" de la
        conversa. Si detectem rotació, resetegem l'estat: es perd el reuse
        d'AQUEST torn (re-prefill) però mai es corromp el context. Retorna
        True si s'ha resetejat.
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
        except TypeError:  # fakes no iterables als tests
            return False
        if rotated:
            prompt_cache_state.cache = None
            prompt_cache_state.token_ids = None
            logger.info(
                "MLX VLM cache: RotatingKVCache rotated — state reset "
                "(fresh bounded cache this turn; prefix reuse skipped, #826)"
            )
        return rotated

    def _log_vlm_kv_request(self, model, prompt_cache_state=None) -> None:
        """#826/#845 instrumentation, VLM twin of "MLX cache created:" (text path).

        Records whether the requested max_kv_size can actually be enforced:
        mlx_vlm delegates to language_model.make_cache() when the model
        defines it (Qwen3.5/gemma…), IGNORING the limit — FD-S7 needs this
        verdict in the field logs to (re)attribute degeneration.
        """
        lang_model = getattr(model, "language_model", None)
        owned = hasattr(lang_model, "make_cache")
        # Review #826: INFO només quan mlx_vlm CREARÀ el cache (com el twin
        # "MLX cache created:" del camí text); en reuse (torns 2+) el veredicte
        # és el mateix fet per-sessió → DEBUG per no inundar el log.
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
            # Review #826: un RotatingKVCache rotat no es pot reutilitzar (el
            # trim de mlx_vlm assumeix KVCache pla) — reset abans de passar-lo.
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

    def _compute_continuable(self, result: Dict[str, Any], is_vlm: bool) -> bool:
        """Whether a truncated answer can be resumed with a Continue (FD-S6).

        Only the MLX text path qualifies (VLM has no reliable finish_reason
        and no continue support; its KV is bounded since #826 except for
        models with a model-owned make_cache — #845, FD-S7). The KV gate
        keeps a Continue chain from crossing the rotating window (which would
        evict the system prompt and degenerate mid-chain, B004) and from
        hitting the untrimmable-when-full corner of RotatingKVCache.
        """
        if result.get("finish_reason") != "length" or is_vlm:
            return False
        used = result.get("prompt_tokens", 0) + result.get("tokens", 0)
        headroom_needed = used + self.config.max_tokens + 512
        return headroom_needed < self.config.max_kv_size

    def _extract_vlm_metrics(
        self,
        result_obj,
        result_text: str,
        elapsed_ms: int,
        prefix_reused: bool = False,
        cached_tokens: int = 0,
        identity_hash: str = "",
        max_tokens_used: "Optional[int]" = None,
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
            # heuristic: hitting the ceiling exactly. False positive when EOS
            # lands on the limit; acceptable because the VLM marker is
            # informative-only (never continuable).
            "finish_reason": (
                "length"
                if (max_tokens_used and gen_tokens >= max_tokens_used)
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
        cache_state = get_vlm_cache_manager().get_or_create(model_key)
        had_cache = cache_state is not None and getattr(cache_state, "cache", None) is not None
        # Best-effort reuse count for the log/metrics (text-only prompts tokenize
        # cleanly; with images the count is approximate). The real saving is
        # always visible in the prefill time regardless of this number.
        cached_tokens = 0
        if had_cache:
            try:
                _tok = getattr(processor, "tokenizer", processor)
                cached_tokens = cache_state.find_prefix_length(_tok.encode(formatted_prompt))
            except Exception:  # nosec B110: metric estimate only — never blocks generation
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
                result_text, result_obj = self._run_vlm_streaming(
                    model, processor, formatted_prompt, tmp_path,
                    max_tokens, stream_callback, cancel_event,
                    prompt_cache_state=cache_state,
                    temperature=temperature, top_p=top_p,
                )
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
        )

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
        top_p: Optional[float] = None,
        continue_final: bool = False,
    ) -> Dict[str, Any]:
        """
        Blocking generation with MLX and PREFIX MATCHING (executed in thread).

        Helpers in generate_helpers.py.
        """
        with MLXChatNode._lock:
            return self._generate_blocking_inner(
                system, messages, messages_for_cache,
                stream_callback, session_id, max_tokens, temperature,
                thinking_enabled, cancel_event, top_p,
                continue_final=continue_final,
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
        top_p: Optional[float] = None,
        continue_final: bool = False,
    ) -> Dict[str, Any]:
        """Inner generation logic, called under lock."""
        from mlx_lm.sample_utils import make_sampler
        from .prompt_cache_manager import get_prompt_cache_manager

        model, tokenizer = self._get_model()
        cache_manager = get_prompt_cache_manager(max_size=self.config.max_session_caches)

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
            continue_final=continue_final,
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

        # 4. Create sampler — top_p is opt-in (mirror of temperature): the request
        # value wins when set, else fall back to the engine config default (≈0.9).
        # `is not None` (never truthiness); schema enforces gt=0.0 so 0.0 never arrives.
        sampler = make_sampler(
            temp=temperature if temperature is not None else self.config.temperature,
            top_p=top_p if top_p is not None else self.config.top_p,
        )

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
            text, tokenizer, cached_kv, len(full_tokens),
            continue_final=continue_final,
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

            # Clear VLM prompt-cache states too (KV caches bound to the old
            # model — free them on reload, mirror of the text path above).
            try:
                from .vlm_cache_manager import get_vlm_cache_manager
                get_vlm_cache_manager().clear()
            except Exception as e:
                logger.warning("MLXChatNode: error clearing VLM cache manager: %s", e)

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
