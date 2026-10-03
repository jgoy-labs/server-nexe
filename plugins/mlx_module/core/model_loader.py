"""MLX model load: vision detection, the RAM guard, and the three load branches.

Extracted from `chat.py` in #966 (slice B). The bodies are the originals; the only
changes are two mechanical, uniform substitutions, `MLXChatNode.` -> `node_cls.`
and `self.config` -> `config`, because the code no longer lives inside a class method.

**`chat.py` reaches it THROUGH THE MODULE** (`model_loader._detect_vlm_capability(...)`),
not by importing the names. That is deliberate: both `execute()` and the load call
`_detect_vlm_capability`, and if each side resolved its own copy, a `patch` on one
would intercept one and miss the other — same function, two behaviours. With a single
resolution site, that divergence cannot exist.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

from ..exceptions import MissingDependencyError
from .model_json import _load_json_safe

logger = logging.getLogger(__name__)


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


_VLM_WEIGHT_PATTERNS = (
    "vision_tower",
    "vision_model",
    "visual.",
    "mm_projector",
    "image_newline",
    "patch_embed",
)


_VLM_ARCH_KEYWORDS = (
    "vl", "vision", "visual", "llava", "intern",
    "qwen2vl", "qwen2_5_vl", "qwen3vl",
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


def load_model_into(node_cls, config) -> None:
    """Load the model and leave the singletons set on `node_cls`.

    Body moved from `MLXChatNode._get_model` with no logic change: it keeps the
    exact assignment order of `_is_vlm` (before the load, and False on the
    fallback path without PyTorch), which is observable if the load fails halfway.
    """
    try:
        import psutil
        _vm = psutil.virtual_memory()
        avail_gb = _vm.available / (1024 ** 3)
        # Field-verified estimate (2026-07-23): weights + KV window +
        # runtime, via the same B004 helpers as the budget — never a
        # local copy of the formula.
        _est = _estimate_required_ram(
            config.model_path, config.max_kv_size
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
            config.model_path,
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
            # Contract: core.turn.errors.is_oom_error detects OOM by
            # substring and wire._oom_notice (web UI) keeps the switch-engine
            # advice only when "MLX" appears in the text (pinned by contract test).
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
    _sanitize_safetensors_index(config.model_path)

    is_vlm = _detect_vlm_capability(config.model_path)
    node_cls._is_vlm = is_vlm

    logger.info(
        "MLXChatNode: loading %s model %s (max_kv_size=%d)",
        "VLM" if is_vlm else "text",
        config.model_path[-50:] if config.model_path else "(empty)",
        config.max_kv_size
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
            node_cls._model, node_cls._tokenizer = load(config.model_path)
        except MissingDependencyError:
            # PyTorch not installed — load vision-capable model in text-only
            # mode via mlx-lm. Vision weights are ignored; text inference works.
            logger.warning(
                "MLXChatNode: PyTorch unavailable — loading VLM %s in text-only mode",
                config.model_path[-40:] if config.model_path else "(empty)",
            )
            node_cls._is_vlm = False
            try:
                from mlx_lm import load
            except (ImportError, AttributeError) as exc:
                raise _curated_import_error(exc) from exc
            node_cls._model, node_cls._tokenizer = load(config.model_path)
    else:
        try:
            from mlx_lm import load
        except (ImportError, AttributeError) as exc:
            raise _curated_import_error(exc) from exc
        node_cls._model, node_cls._tokenizer = load(config.model_path)

    logger.info("MLXChatNode: model loaded successfully (vlm=%s)", is_vlm)
