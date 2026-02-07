# -*- coding: utf-8 -*-
"""
MLXChatNode - LLM node based on mlx-lm for Apple Silicon.

VERSION 2.0 - REAL PREFIX MATCHING via MLXPromptCacheManager.
Split 2026-01-01: Helpers moved to generate_helpers.py (Lesson 10)

Features:
- Singleton model (loaded once, reused)
- MLXPromptCacheManager: trie-based cache with prefix matching
- Reuses KV states from the prefix (system + history)
- Only processes new tokens per turn -> 5-10x speedup

Requires:
- Apple Silicon (M1/M2/M3/M4)
- mlx-lm >= 0.30.0
- MLX model format (safetensors)

Part of: PLA_OPTIMITZACIO_LLM_MODULAR - MLX Backend
"""
import asyncio
import gc
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .config import MLXConfig
# Split 2026-01-01: Helpers for _generate_blocking
from .generate_helpers import (
    prepare_tokens,
    lookup_prefix_cache,
    determine_tokens_to_process,
    run_streaming_generation,
    save_cache_post_generation,
    extract_metrics,
)
from core.utils import compute_system_hash
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"mlx_module.logs.{key}", fallback, **kwargs)


class MLXChatNode:
    """
    Inference engine for MLX adapted for Nexe 0.8.

    Maintains:
    - A single loaded model (singleton)
    - MLXPromptCacheManager for prefix matching (trie-based)
    - Reuses KV states from the prefix (system + history)
    - Only processes new tokens per turn

    Class Attributes:
        _model: Singleton MLX model
        _tokenizer: Singleton tokenizer
        _lock: Lock for thread safety
        _config: Active configuration
    """

    _model: Optional[Any] = None
    _tokenizer: Optional[Any] = None
    _lock: threading.Lock = threading.Lock()
    _config: Optional[MLXConfig] = None

    def __init__(self, config: Optional[MLXConfig] = None):
        """
        Initialize the MLX node.

        Args:
            config: MLX configuration (or load from .env if None)
        """
        self.config = config or MLXConfig.from_env()

        # Update singleton config if it changes
        if (MLXChatNode._config is None or
                MLXChatNode._config.model_path != self.config.model_path):
            MLXChatNode._config = self.config
            MLXChatNode._model = None  # Force reload

    def _get_model(self) -> tuple:
        """
        Get model and tokenizer (lazy singleton load).

        Returns:
            tuple: (model, tokenizer)
        """
        if MLXChatNode._model is None:
            # Lazy import to avoid loading mlx if unused
            from mlx_lm import load

            logger.info(
                _t_log(
                    "chatnode_loading_model",
                    "MLXChatNode: loading model {model} (max_kv_size={max_kv_size})",
                    model=self.config.model_path[-50:] if self.config.model_path else "(empty)",
                    max_kv_size=self.config.max_kv_size,
                )
            )

            MLXChatNode._model, MLXChatNode._tokenizer = load(
                self.config.model_path
            )

            logger.info(
                _t_log(
                    "chatnode_model_loaded",
                    "MLXChatNode: model loaded successfully"
                )
            )

        return MLXChatNode._model, MLXChatNode._tokenizer

    # NOTE: Legacy cache methods (_get_or_create_cache, _touch_lru, _destroy_cache)
    # have been removed. We now use MLXPromptCacheManager for real prefix matching.


    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run generation with MLX.

        Args:
            inputs: Dict with system, messages, messages_for_cache, session_id, stream_callback

        Returns:
            Dict with response, tokens, metrics, etc.
        """
        start_time = time.time()

        system = inputs.get("system", "")
        messages = inputs.get("messages", [])
        # OPTION D: messages_for_cache to store cache without memory
        messages_for_cache = inputs.get("messages_for_cache", messages)
        session_id = inputs.get("session_id", "default")
        stream_callback = inputs.get("stream_callback")

        # Log for debugging
        logger.info(
            _t_log(
                "chatnode_session",
                "MLXChatNode: session={session}, msgs={count}",
                session=session_id[:8] if session_id else "none",
                count=len(messages),
            )
        )

        # Capture event loop for thread-safe streaming
        loop = asyncio.get_running_loop()

        def threadsafe_callback(text: str) -> None:
            if stream_callback and callable(stream_callback):
                loop.call_soon_threadsafe(stream_callback, text)

        try:
            # Run generation in a thread (MLX is blocking)
            # With PREFIX MATCHING via MLXPromptCacheManager
            # OPTION D: Pass messages (for generation) and messages_for_cache (for storage)
            result = await asyncio.to_thread(
                self._generate_blocking,
                system,
                messages,
                messages_for_cache,  # NEW: Store clean cache (Option D)
                threadsafe_callback if stream_callback else None,
                session_id  # Separate caches per session
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            context_used = result["prompt_tokens"] + result["tokens"]
            system_tokens = len(system) // 4  # Estimate
            prompt_tps = result.get("prompt_tps", 0)

            # Use prefix_reused from cache manager (based on real tokens)
            prefix_reuse = result.get("prefix_reused", False)
            cached_tokens = result.get("cached_tokens", 0)
            actual_prefill = result.get("actual_prefill_tokens", result["prompt_tokens"])

            # Compute real speedup
            if cached_tokens > 0:
                reuse_ratio = (cached_tokens + actual_prefill) / max(actual_prefill, 1)
            else:
                reuse_ratio = 1.0

            # Compute per-phase timings (ms)
            generation_tps = result["tokens_per_second"]
            prefill_ms = int((actual_prefill / prompt_tps * 1000) if prompt_tps > 0 else 0)
            generation_ms = int((result["tokens"] / generation_tps * 1000) if generation_tps > 0 else 0)
            overhead_ms = elapsed_ms - prefill_ms - generation_ms

            logger.info(
                _t_log(
                    "chatnode_prefix_stats",
                    "MLXChatNode: prefix={prefix} (cached={cached}, new={new}), prefill={prompt_tps:.1f} tok/s, gen={gen_tps:.1f} tok/s, {elapsed_ms}ms (p:{prefill_ms} g:{generation_ms}), {peak_memory_mb:.0f} MB",
                    prefix="REUSED" if prefix_reuse else "FULL",
                    cached=cached_tokens,
                    new=actual_prefill,
                    prompt_tps=prompt_tps,
                    gen_tps=generation_tps,
                    elapsed_ms=elapsed_ms,
                    prefill_ms=prefill_ms,
                    generation_ms=generation_ms,
                    peak_memory_mb=result.get("peak_memory_mb", 0),
                )
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
                "cache_active": result.get("cache_active", False),  # Compatibility
                "prefix_reuse": prefix_reuse,  # True = prefix matching worked
                "reuse_ratio": round(reuse_ratio, 2),  # Cached/new token ratio
                "cached_tokens": cached_tokens,  # Tokens reused from cache
                "actual_prefill_tokens": actual_prefill,  # Tokens actually processed
                "identity_hash": result.get("identity_hash", ""),  # System hash
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
                _t_log(
                    "chatnode_error",
                    "MLXChatNode error after {elapsed_ms}ms: {error}",
                    elapsed_ms=elapsed_ms,
                    error=str(e),
                )
            )
            raise

    def _generate_blocking(
        self,
        system: str,
        messages: List[Dict],
        messages_for_cache: List[Dict],
        stream_callback: Optional[Callable[[str], None]],
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Blocking generation with MLX and PREFIX MATCHING (runs in a thread).

        Refactored 2026-01-01 (Lesson 10): from ~295 to ~45 lines.
        Helpers in generate_helpers.py.
        """
        from mlx_lm.sample_utils import make_sampler
        from .prompt_cache_manager import get_prompt_cache_manager

        model, tokenizer = self._get_model()
        cache_manager = get_prompt_cache_manager(max_size=8)

        # Model key for cache (path + identity_hash + session_id)
        identity_hash = compute_system_hash(system)
        session_key = session_id[:8] if session_id else "default"
        model_key = f"{self.config.model_path}:{identity_hash}:{session_key}"

        # 1. Prepare tokens (tokenization + sanitization)
        full_tokens, cache_lookup_tokens, all_messages, all_cache_messages = prepare_tokens(
            system, messages, messages_for_cache, tokenizer
        )
        total_tokens = len(full_tokens)

        # 2. Lookup prefix cache
        cached_kv, cached_token_count, prefix_reused = lookup_prefix_cache(
            cache_manager, model_key, cache_lookup_tokens, model, self.config.max_kv_size
        )

        # Visible log for debug
        print(f"\n{'='*60}")
        print(
            _t_log(
                "prefix_cache_header",
                "MLX PREFIX CACHE: prefix_reuse={reuse}",
                reuse="YES" if prefix_reused else "NO",
            )
        )
        print(
            _t_log(
                "prefix_cache_stats",
                "  cached_tokens={cached}, new_tokens={new}",
                cached=cached_token_count,
                new=total_tokens - cached_token_count,
            )
        )
        print(f"{'='*60}\n")
        logger.info(
            _t_log(
                "chatnode_identity",
                "MLXChatNode: identity={identity}, full={full}, cached={cached}, new={new}, prefix_reuse={reuse}",
                identity=identity_hash[:8],
                full=total_tokens,
                cached=cached_token_count,
                new=total_tokens - cached_token_count,
                reuse="YES" if prefix_reused else "NO",
            )
        )

        # 3. Determine tokens to process
        tokens_to_process, new_tokens = determine_tokens_to_process(
            full_tokens, cached_token_count, prefix_reused
        )

        # 4. Create sampler
        sampler = make_sampler(temp=self.config.temperature, top_p=self.config.top_p)

        # 5. Run streaming generation
        text, last_response, _ = run_streaming_generation(
            model, tokenizer, tokens_to_process, self.config.max_tokens,
            sampler, cached_kv, stream_callback,
            cache_manager, model_key, cache_lookup_tokens
        )

        # 6. Store post-generation cache (OPTION D: clean messages)
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
        """Destroy model, tokenizer, and all caches."""
        with cls._lock:
            # Clear cache manager (prefix matching)
            try:
                from .prompt_cache_manager import get_prompt_cache_manager
                cache_manager = get_prompt_cache_manager()
                cache_manager.clear()
            except Exception as e:
                logger.warning(
                    _t_log(
                        "cache_manager_clear_failed",
                        "MLXChatNode: error clearing cache manager: {error}",
                        error=str(e),
                    )
                )

            # Destroy model
            if cls._model is not None:
                del cls._model
                cls._model = None

            if cls._tokenizer is not None:
                del cls._tokenizer
                cls._tokenizer = None

            cls._config = None

            # Free memory
            try:
                import mlx.core as mx
                mx.clear_cache()  # Replaces mx.metal.clear_cache (deprecated)
            except Exception as e:
                logger.warning(
                    _t_log(
                        "cache_clear_failed",
                        "MLXChatNode: error clearing cache: {error}",
                        error=str(e),
                    )
                )

            gc.collect()
            logger.info(
                _t_log(
                    "model_reset",
                    "MLXChatNode: model and all caches reset"
                )
            )

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
            logger.debug(
                _t_log(
                    "stats_collection_failed",
                    "MLX stats collection failed: {error}",
                    error=str(e),
                )
            )  # nosec B110 - Optional stats

        return {
            "model_loaded": cls._model is not None,
            "model_path": cls._config.model_path if cls._config else None,
            "max_kv_size": cls._config.max_kv_size if cls._config else 0,
            "cache_manager": cache_manager_stats,
        }
