"""The MLX TEXT path, extracted from `chat.py` in #966 — slice C.

Symmetric with `vlm_runner`: with vision and loading already out, `MLXChatNode` still held
the text path inside out of pure inertia. The two methods come with the original body; the
only modifications are mechanical, uniform substitutions.

**The pipeline helpers are called THROUGH THE MODULE** (`generate_helpers.prepare_tokens(...)`),
not by importing their names. That is the lesson of slice B: with a single resolution site, patching
the definition site covers every consumer and one `patch` cannot intercept one call and miss another.
"""
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import utils as core_utils

from . import generate_helpers

logger = logging.getLogger(__name__)


class MLXTextRunner:
    """The text path of `MLXChatNode`. The bodies are the originals."""

    def __init__(self, node):
        self._node = node

    @property
    def config(self):
        """Live from the node: `apply_config` replaces the config object."""
        return self._node.config

    def _get_model(self) -> tuple:
        """Resolved at call time, not in `__init__`: the suite patches
        `MLXChatNode._get_model` after the node is built."""
        return self._node._get_model()

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
        with type(self._node)._lock:
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
        identity_hash = core_utils.compute_system_hash(system)
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

        # 1. Prepare tokens (tokenization + sanitization + budget truncation, #845)
        full_tokens, cache_lookup_tokens, all_messages, all_cache_messages = generate_helpers.prepare_tokens(
            system, messages, messages_for_cache, tokenizer,
            thinking_enabled=thinking_enabled,
            model_type=model_type,
            continue_final=continue_final,
            max_kv_size=self.config.max_kv_size,
            max_tokens=max_tokens if max_tokens is not None else self.config.max_tokens,
        )
        total_tokens = len(full_tokens)

        # 2. Lookup prefix cache
        cached_kv, cached_token_count, prefix_reused = generate_helpers.lookup_prefix_cache(
            cache_manager, model_key, cache_lookup_tokens, model, self.config.max_kv_size
        )

        logger.info(
            "MLXChatNode: identity=%s, full=%d, cached=%d, new=%d, prefix_reuse=%s",
            identity_hash[:8], total_tokens, cached_token_count,
            total_tokens - cached_token_count, "YES" if prefix_reused else "NO"
        )

        # 3. Determine tokens to process
        tokens_to_process, new_tokens = generate_helpers.determine_tokens_to_process(
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
        text, last_response, _ = generate_helpers.run_streaming_generation(
            model, tokenizer, tokens_to_process, max_tokens if max_tokens is not None else self.config.max_tokens,
            sampler, cached_kv, stream_callback,
            cache_manager, model_key, cache_lookup_tokens,
            model_path=self.config.model_path,
            cancel_event=cancel_event,
        )

        # 6. Save cache post-generation (clean messages, without memory context)
        generate_helpers.save_cache_post_generation(
            cache_manager, model_key, all_cache_messages,
            text, tokenizer, cached_kv, len(full_tokens),
            continue_final=continue_final,
        )

        # 7. Extract and return metrics
        return generate_helpers.extract_metrics(
            last_response, text, prefix_reused, cached_token_count,
            total_tokens, new_tokens, identity_hash
        )
