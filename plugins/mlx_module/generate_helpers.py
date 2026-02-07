# -*- coding: utf-8 -*-
"""
MLX Generation Helper Functions.

Split 2026-01-01: Extracted from chat.py to keep _generate_blocking() < 50 lines.
Helper functions for MLX generation with prefix caching.
"""
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"mlx_module.logs.{key}", fallback, **kwargs)

USER_PLACEHOLDER = t_modular(
    "mlx_module.generate.user_placeholder",
    "(continue)"
)
ASSISTANT_PLACEHOLDER = t_modular(
    "mlx_module.generate.assistant_placeholder",
    "(understood)"
)

def sanitize_messages_for_alternation(messages: List[Dict]) -> List[Dict]:
    """
    Sanitize messages to ensure strict user/assistant alternation.

    Some models (Gemma, etc.) require strictly alternating roles.
    This function:
    - Merges consecutive messages with the same role
    - Ensures it starts with "user" (adds placeholder if needed)
    - Ensures user/assistant/user/assistant/... alternation

    Args:
        messages: List of messages [{role, content}, ...]

    Returns:
        Sanitized list with alternating roles
    """
    if not messages:
        return []

    # Filter system messages (already added separately)
    filtered = [m for m in messages if m.get("role") != "system"]

    if not filtered:
        return []

    # Merge consecutive messages with the same role
    merged = []
    for msg in filtered:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if merged and merged[-1]["role"] == role:
            # Merge with previous
            merged[-1]["content"] += "\n\n" + content
        else:
            merged.append({"role": role, "content": content})

    # Ensure it starts with "user"
    if merged and merged[0]["role"] != "user":
        # If it starts with assistant, add a user placeholder
        merged.insert(0, {"role": "user", "content": USER_PLACEHOLDER})

    # Verify alternation and fix if needed
    sanitized = []
    expected_role = "user"

    for msg in merged:
        if msg["role"] == expected_role:
            sanitized.append(msg)
            expected_role = "assistant" if expected_role == "user" else "user"
        elif msg["role"] == "assistant" and expected_role == "user":
            # Missing user, insert placeholder
            sanitized.append({"role": "user", "content": USER_PLACEHOLDER})
            sanitized.append(msg)
            expected_role = "user"
        elif msg["role"] == "user" and expected_role == "assistant":
            # Missing assistant, insert placeholder
            sanitized.append({"role": "assistant", "content": ASSISTANT_PLACEHOLDER})
            sanitized.append(msg)
            expected_role = "assistant"

    return sanitized


def prepare_tokens(
    system: str,
    messages: List[Dict],
    messages_for_cache: List[Dict],
    tokenizer: Any,
) -> Tuple[List[int], List[int], List[Dict], List[Dict]]:
    """
    Prepare and tokenize messages for generation and cache.

    Args:
        system: System prompt
        messages: Messages for generation (with memory)
        messages_for_cache: Clean messages for cache (without memory)
        tokenizer: Tokenizer MLX

    Returns:
        Tuple: (full_tokens, cache_lookup_tokens, all_messages, all_cache_messages)
    """
    # Sanitize messages for strict alternation (Gemma, etc.)
    sanitized_messages = sanitize_messages_for_alternation(messages)
    sanitized_cache_messages = sanitize_messages_for_alternation(messages_for_cache)

    # Build OpenAI-format messages
    all_messages = [{"role": "system", "content": system}] + sanitized_messages
    all_cache_messages = [{"role": "system", "content": system}] + sanitized_cache_messages

    # Tokenize for generation (with memory)
    prompt_text = tokenizer.apply_chat_template(
        all_messages,
        add_generation_prompt=True,
        tokenize=False
    )
    if isinstance(prompt_text, str):
        full_tokens = tokenizer.encode(prompt_text)
    else:
        full_tokens = list(prompt_text)

    # Tokenize for cache lookup (clean, without memory)
    cache_prompt_text = tokenizer.apply_chat_template(
        all_cache_messages,
        add_generation_prompt=True,
        tokenize=False
    )
    if isinstance(cache_prompt_text, str):
        cache_lookup_tokens = tokenizer.encode(cache_prompt_text)
    else:
        cache_lookup_tokens = list(cache_prompt_text)

    return full_tokens, cache_lookup_tokens, all_messages, all_cache_messages


def lookup_prefix_cache(
    cache_manager: Any,
    model_key: str,
    cache_lookup_tokens: List[int],
    model: Any,
    max_kv_size: int,
) -> Tuple[Any, int, bool]:
    """
    Look up the longest matching prefix in the cache.

    Args:
        cache_manager: MLXPromptCacheManager
        model_key: Model key (path + hash + session)
        cache_lookup_tokens: Clean tokens for lookup
        model: Model MLX
        max_kv_size: Max KV cache size

    Returns:
        Tuple: (cached_kv, cached_token_count, prefix_reused)
    """
    from mlx_lm.models.cache import make_prompt_cache

    cached_kv, remaining_tokens = cache_manager.fetch_nearest_cache(
        model_key, cache_lookup_tokens
    )

    # If no cache exists, create a new one
    if cached_kv is None:
        cached_kv = make_prompt_cache(model, max_kv_size=max_kv_size)

    # Calculate how many prefix tokens are cached
    cached_token_count = len(cache_lookup_tokens) - len(remaining_tokens)
    prefix_reused = cached_token_count > 0

    return cached_kv, cached_token_count, prefix_reused


def determine_tokens_to_process(
    full_tokens: List[int],
    cached_token_count: int,
    prefix_reused: bool,
) -> Tuple[Any, List[int]]:
    """
    Determine which tokens to process based on the cache.

    Args:
        full_tokens: All tokens (with memory)
        cached_token_count: Tokens already cached
        prefix_reused: Whether the prefix was reused

    Returns:
        Tuple: (tokens_to_process_mx, new_tokens_list)
    """
    import mlx.core as mx

    new_tokens = full_tokens[cached_token_count:] if cached_token_count > 0 else full_tokens

    if prefix_reused and len(new_tokens) == 0:
        # Exact match (rare): process at least 1 token for stability
        tokens_to_process = mx.array([full_tokens[0]])
        logger.debug(
            _t_log(
                "exact_match_processing_bos",
                "MLXChatNode: exact match, processing BOS token (~10ms overhead)"
            )
        )
    elif prefix_reused:
        # Prefix match: process only new tokens (WITH memory)
        tokens_to_process = mx.array(new_tokens)
        logger.debug(
            _t_log(
                "prefix_match_processing",
                "MLXChatNode: prefix match, processing {count} new tokens (with memory)",
                count=len(new_tokens),
            )
        )
    else:
        # No match: process everything
        tokens_to_process = mx.array(full_tokens)

    return tokens_to_process, new_tokens


def run_streaming_generation(
    model: Any,
    tokenizer: Any,
    tokens_to_process: Any,
    max_tokens: int,
    sampler: Any,
    cached_kv: Any,
    stream_callback: Optional[Callable[[str], None]],
    cache_manager: Any,
    model_key: str,
    cache_lookup_tokens: List[int],
) -> Tuple[str, Any, List[int]]:
    """
    Run generation with streaming.

    Args:
        model: MLX model
        tokenizer: Tokenizer
        tokens_to_process: Tokens to process (mx.array)
        max_tokens: Max tokens to generate
        sampler: Sampler for generation
        cached_kv: KV cache
        stream_callback: Streaming callback
        cache_manager: Cache manager for post-prefill saving
        model_key: Model key
        cache_lookup_tokens: Tokens to store in cache

    Returns:
        Tuple: (text, last_response, generated_tokens)
    """
    from mlx_lm import stream_generate

    full_response = []
    last_response = None
    generated_tokens = []

    # Common stop tokens for different models
    # We post-process the response to cut at these sequences
    STOP_SEQUENCES = [
        "<|end|>", "<|endoftext|>", "<|assistant|>",  # Phi-3.5, GPT
        "</s>",  # Llama
        "<end_of_turn>",  # Gemma
        "<|im_end|>",  # ChatML format
    ]

    # MLX relies on tokenizer.eos_token_ids for stopping
    # No need for explicit stop_words parameter
    generator = stream_generate(
        model,
        tokenizer,
        tokens_to_process,
        max_tokens=max_tokens,
        sampler=sampler,
        prompt_cache=cached_kv
    )

    # First iteration: prefill + first token
    stop_detected = False
    try:
        first_response = next(generator)
        if first_response.text:
            # Check for stop sequences
            current_text = first_response.text
            for stop_seq in STOP_SEQUENCES:
                if stop_seq in current_text:
                    # Truncate at stop sequence
                    current_text = current_text.split(stop_seq)[0]
                    stop_detected = True
                    break

            if current_text:
                full_response.append(current_text)
                if stream_callback:
                    stream_callback(current_text)

        if hasattr(first_response, 'token'):
            generated_tokens.append(first_response.token)
        last_response = first_response

        # SAVE CACHE POST-PREFILL (before the rest times out!)
        cache_manager.insert_cache(model_key, cache_lookup_tokens, cached_kv)
        logger.info(
            _t_log(
                "cache_saved_prefill",
                "MLXChatNode: cache saved post-prefill ({tokens} tokens, key={key})",
                tokens=len(cache_lookup_tokens),
                key=model_key[:30],
            )
        )
    except StopIteration:
        logger.warning(
            _t_log(
                "generator_empty",
                "MLXChatNode: generator empty, no prefill cache saved"
            )
        )

    # Continue with the rest of generation
    if not stop_detected:
        for response in generator:
            if response.text:
                # Check for stop sequences
                current_text = response.text
                for stop_seq in STOP_SEQUENCES:
                    if stop_seq in current_text:
                        # Truncate at stop sequence
                        current_text = current_text.split(stop_seq)[0]
                        stop_detected = True
                        break

                if current_text:
                    full_response.append(current_text)
                    if stream_callback:
                        stream_callback(current_text)

            if hasattr(response, 'token'):
                generated_tokens.append(response.token)
            last_response = response

            # Exit loop if stop detected
            if stop_detected:
                break

    text = "".join(full_response)
    return text, last_response, generated_tokens


def save_cache_post_generation(
    cache_manager: Any,
    model_key: str,
    all_cache_messages: List[Dict],
    text: str,
    tokenizer: Any,
    cached_kv: Any,
    full_tokens_count: int,
) -> None:
    """
    Save cache after generation (OPTION D: clean messages).

    Args:
        cache_manager: Cache manager
        model_key: Model key
        all_cache_messages: Clean messages (without memory)
        text: Generated text
        tokenizer: Tokenizer
        cached_kv: KV cache
        full_tokens_count: Number of tokens in the full prompt
    """
    if not text.strip():
        return

    try:
        # Check if it already ends with assistant (for placeholders)
        if all_cache_messages and all_cache_messages[-1].get("role") == "assistant":
            # Merge with the last assistant
            cache_messages_with_response = all_cache_messages[:-1] + [{
                "role": "assistant",
                "content": all_cache_messages[-1]["content"] + "\n\n" + text
            }]
            logger.debug(
                _t_log(
                    "merged_response_with_cache",
                    "MLXChatNode: merged response with last assistant (cache)"
                )
            )
        else:
            # Append normally
            cache_messages_with_response = all_cache_messages + [{"role": "assistant", "content": text}]

        # Tokenize WITHOUT generation_prompt (next turn will add it)
        cache_text = tokenizer.apply_chat_template(
            cache_messages_with_response,
            add_generation_prompt=False,
            tokenize=False
        )
        cache_tokens = tokenizer.encode(cache_text) if isinstance(cache_text, str) else list(cache_text)

        cache_manager.insert_cache(model_key, cache_tokens, cached_kv)
        logger.debug(
            t_modular(
                "mlx_module.generate.cache_saved",
                "MLXChatNode: Option D saved clean cache ({prompt_tokens} tokens → {total_tokens} with response)",
                prompt_tokens=full_tokens_count,
                total_tokens=len(cache_tokens)
            )
        )
    except Exception as e:
        # If cache saving fails, do not block the response
        logger.warning(
            _t_log(
                "cache_save_failed",
                "MLXChatNode: cache save failed (non-blocking): {error}",
                error=str(e)[:100],
            )
        )


def extract_metrics(
    last_response: Any,
    text: str,
    prefix_reused: bool,
    cached_token_count: int,
    total_tokens: int,
    new_tokens: List[int],
    identity_hash: str,
) -> Dict[str, Any]:
    """
    Extract metrics from the generation response.

    Args:
        last_response: Last generator response
        text: Generated text
        prefix_reused: Whether the prefix was reused
        cached_token_count: Cached tokens
        total_tokens: Total prompt tokens
        new_tokens: Newly processed tokens
        identity_hash: System prompt hash

    Returns:
        Dict with metrics
    """
    if last_response:
        # actual_prefill = actually processed tokens (not cached)
        if prefix_reused and len(new_tokens) == 0:
            actual_prefill_tokens = 1  # Exact match: only BOS token
        elif prefix_reused:
            actual_prefill_tokens = len(new_tokens)
        else:
            actual_prefill_tokens = total_tokens

        return {
            "text": text,
            "tokens": last_response.generation_tokens,
            "prompt_tokens": last_response.prompt_tokens,
            "tokens_per_second": last_response.generation_tps,
            "prompt_tps": last_response.prompt_tps,
            "peak_memory_mb": (last_response.peak_memory / (1024 * 1024))
                              if last_response.peak_memory else 0,
            "prefix_reused": prefix_reused,
            "cache_active": prefix_reused,  # Alias per compatibilitat
            "cached_tokens": cached_token_count,
            "actual_prefill_tokens": actual_prefill_tokens,
            "identity_hash": identity_hash,
        }
    else:
        return {
            "text": text,
            "tokens": len(text) // 4,
            "prompt_tokens": 0,
            "tokens_per_second": 0,
            "prompt_tps": 0,
            "peak_memory_mb": 0,
            "prefix_reused": False,
            "cache_active": False,
            "cached_tokens": 0,
            "actual_prefill_tokens": 0,
            "identity_hash": identity_hash,
        }


__all__ = [
    "sanitize_messages_for_alternation",
    "prepare_tokens",
    "lookup_prefix_cache",
    "determine_tokens_to_process",
    "run_streaming_generation",
    "save_cache_post_generation",
    "extract_metrics",
]
