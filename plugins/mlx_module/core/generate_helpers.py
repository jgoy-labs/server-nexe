# -*- coding: utf-8 -*-
"""
MLX Generation Helper Functions.

Helper functions for MLX generation with prefix caching.
"""
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _merge_same_role(filtered: List[Dict]) -> List[Dict]:
    """Merge consecutive messages that share the same role."""
    merged: list = []
    for msg in filtered:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if merged and merged[-1]["role"] == role:
            merged[-1]["content"] += "\n\n" + content
        else:
            merged.append({"role": role, "content": content})
    return merged


def _ensure_starts_with_user(merged: List[Dict]) -> List[Dict]:
    """Prepend a user placeholder if the list starts with an assistant turn."""
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "(continua)"})
    return merged


def _enforce_alternation(merged: List[Dict]) -> List[Dict]:
    """Ensure strict user/assistant alternation, inserting placeholders where needed."""
    sanitized = []
    expected_role = "user"
    for msg in merged:
        if msg["role"] == expected_role:
            sanitized.append(msg)
            expected_role = "assistant" if expected_role == "user" else "user"
        elif msg["role"] == "assistant" and expected_role == "user":
            sanitized.append({"role": "user", "content": "(continua)"})
            sanitized.append(msg)
            expected_role = "user"
        elif msg["role"] == "user" and expected_role == "assistant":
            sanitized.append({"role": "assistant", "content": "(understood)"})
            sanitized.append(msg)
            expected_role = "assistant"
    return sanitized


def sanitize_messages_for_alternation(messages: List[Dict]) -> List[Dict]:
    """
    Sanitizes messages to ensure strict user/assistant alternation.

    Some models (Gemma, etc.) require strictly alternating roles.
    This function:
    - Merges consecutive messages from the same role
    - Ensures it starts with "user" (adds placeholder if needed)
    - Ensures user/assistant/user/assistant/... alternation

    Args:
        messages: List of messages [{role, content}, ...]

    Returns:
        Sanitized list with alternating roles
    """
    if not messages:
        return []

    filtered = [m for m in messages if m.get("role") != "system"]
    if not filtered:
        return []

    merged = _merge_same_role(filtered)
    merged = _ensure_starts_with_user(merged)
    return _enforce_alternation(merged)


def _apply_template(tokenizer: Any, messages: List[Dict], thinking_enabled: bool) -> str:
    """Apply chat template with optional thinking control (Qwen3 enable_thinking)."""
    kwargs: dict = {"add_generation_prompt": True, "tokenize": False}
    # Qwen3/Qwen3.5 supports enable_thinking=False to suppress <think> blocks.
    # Pass defensively — tokenizers that don't know the kwarg will raise TypeError.
    if not thinking_enabled:
        try:
            return tokenizer.apply_chat_template(messages, enable_thinking=False, **kwargs)
        except TypeError:
            pass  # tokenizer does not support enable_thinking — fall through
    return tokenizer.apply_chat_template(messages, **kwargs)


def prepare_tokens(
    system: str,
    messages: List[Dict],
    messages_for_cache: List[Dict],
    tokenizer: Any,
    thinking_enabled: bool = True,
    model_type: str = "",
) -> Tuple[List[int], List[int], List[Dict], List[Dict]]:
    """
    Prepares and tokenizes messages for generation and cache.

    Args:
        system: System prompt
        messages: Messages for generation (with memory)
        messages_for_cache: Clean messages for cache (without memory)
        tokenizer: MLX tokenizer
        thinking_enabled: If False, suppress thinking tokens (Qwen3 enable_thinking=False)
        model_type: ``config.json.model_type`` of the loaded model. Used to
            decide whether to inject the Qwen3.5 thinking-force directive
            (see ``chat._qwen35_needs_thinking_directive``).

    Returns:
        Tuple: (full_tokens, cache_lookup_tokens, all_messages, all_cache_messages)
    """
    # Sanitize messages for strict role alternation (Gemma, etc.)
    sanitized_messages = sanitize_messages_for_alternation(messages)
    sanitized_cache_messages = sanitize_messages_for_alternation(messages_for_cache)

    # Build OpenAI-format messages
    all_messages = [{"role": "system", "content": system}] + sanitized_messages
    all_cache_messages = [{"role": "system", "content": system}] + sanitized_cache_messages

    # Qwen3.5-only: when Raonament=ON, reinforce thinking in the system prompt.
    # Imported lazily to avoid a circular import (chat → generate_helpers).
    from .chat import (
        _qwen35_needs_thinking_directive,
        _inject_thinking_directive_into_messages,
        QWEN35_THINKING_DIRECTIVE,
    )
    if _qwen35_needs_thinking_directive(model_type, thinking_enabled):
        all_messages = _inject_thinking_directive_into_messages(
            all_messages, QWEN35_THINKING_DIRECTIVE
        )
        all_cache_messages = _inject_thinking_directive_into_messages(
            all_cache_messages, QWEN35_THINKING_DIRECTIVE
        )

    # Tokenize for generation (with memory context)
    prompt_text = _apply_template(tokenizer, all_messages, thinking_enabled)
    if isinstance(prompt_text, str):
        full_tokens = tokenizer.encode(prompt_text)
    else:
        full_tokens = list(prompt_text)

    # Tokenize for cache lookup (clean, without memory context)
    cache_prompt_text = _apply_template(tokenizer, all_cache_messages, thinking_enabled)
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
    Searches the cache for the longest matching prefix.

    Args:
        cache_manager: MLXPromptCacheManager
        model_key: Model key (path + hash + session)
        cache_lookup_tokens: Clean tokens for lookup
        model: MLX model
        max_kv_size: Maximum KV cache size

    Returns:
        Tuple: (cached_kv, cached_token_count, prefix_reused)
    """
    from mlx_lm.models.cache import make_prompt_cache

    cached_kv, remaining_tokens = cache_manager.fetch_nearest_cache(
        model_key, cache_lookup_tokens
    )

    # If there is no cache, create a new one
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
    Determines which tokens to process based on the cache.

    Args:
        full_tokens: All tokens (with memory)
        cached_token_count: Tokens already cached
        prefix_reused: Whether a prefix was reused

    Returns:
        Tuple: (tokens_to_process_mx, new_tokens_list)
    """
    import mlx.core as mx

    new_tokens = full_tokens[cached_token_count:] if cached_token_count > 0 else full_tokens

    if prefix_reused and len(new_tokens) == 0:
        # Exact match (rare): process at least 1 token for stability
        tokens_to_process = mx.array([full_tokens[0]])
        logger.debug("MLXChatNode: exact match, processing BOS token (~10ms overhead)")
    elif prefix_reused:
        # Prefix match: process only new tokens (WITH memory context)
        tokens_to_process = mx.array(new_tokens)
        logger.debug(
            "MLXChatNode: prefix match, processing %d new tokens (with memory)",
            len(new_tokens)
        )
    else:
        # No match: process everything
        tokens_to_process = mx.array(full_tokens)

    return tokens_to_process, new_tokens


def _get_stop_sequences(model_path: str) -> List[str]:
    """Return appropriate stop sequences for the given model path."""
    if "gpt-oss" in model_path.lower():
        return ["<|endoftext|>"]
    return [
        "<|end|>", "<|endoftext|>",  # Phi-3.5, GPT
        "</s>",                       # Llama 2
        "<|eot_id|>",                 # Llama 3.x
        "<end_of_turn>",              # Gemma
        "<|im_end|>",                 # ChatML format
    ]


def _apply_stop_sequences(text: str, stop_sequences: List[str]) -> Tuple[str, bool]:
    """Truncate text at the first stop sequence found. Returns (text, stop_detected)."""
    for stop_seq in stop_sequences:
        if stop_seq in text:
            return text.split(stop_seq)[0], True
    return text, False


def _emit_token(
    response: Any,
    stop_sequences: List[str],
    full_response: List[str],
    generated_tokens: List[int],
    stream_callback: Optional[Callable[[str], None]],
) -> bool:
    """Process one generator response; return True if a stop sequence was detected."""
    stop_detected = False
    if response.text:
        current_text, stop_detected = _apply_stop_sequences(response.text, stop_sequences)
        if current_text:
            full_response.append(current_text)
            if stream_callback:
                stream_callback(current_text)
    if hasattr(response, 'token'):
        generated_tokens.append(response.token)
    return stop_detected


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
    model_path: str = "",
    cancel_event: Any = None,
) -> Tuple[str, Any, List[int]]:
    """
    Executes generation with streaming.

    Args:
        model: MLX model
        tokenizer: Tokenizer
        tokens_to_process: Tokens to process (mx.array)
        max_tokens: Maximum tokens to generate
        sampler: Sampler for generation
        cached_kv: KV cache
        stream_callback: Callback for streaming
        cache_manager: Cache manager for saving post-prefill
        model_key: Model key
        cache_lookup_tokens: Tokens to store in cache

    Returns:
        Tuple: (text, last_response, generated_tokens)
    """
    from mlx_lm import stream_generate

    stop_sequences = _get_stop_sequences(model_path)
    full_response: List[str] = []
    last_response = None
    generated_tokens: List[int] = []

    # MLX relies on tokenizer.eos_token_ids for stopping
    generator = stream_generate(
        model, tokenizer, tokens_to_process,
        max_tokens=max_tokens, sampler=sampler, prompt_cache=cached_kv
    )

    # First iteration: prefill + first token
    stop_detected = False
    try:
        first_response = next(generator)
        stop_detected = _emit_token(first_response, stop_sequences, full_response,
                                    generated_tokens, stream_callback)
        last_response = first_response

        # SAVE CACHE POST-PREFILL (before the rest times out!)
        cache_manager.insert_cache(model_key, cache_lookup_tokens, cached_kv)
        logger.info(  # nosemgrep: python-logger-credential-disclosure
            "MLXChatNode: cache saved post-prefill (%d tokens, key=%s)",
            len(cache_lookup_tokens), model_key[:30]
        )
    except StopIteration:
        logger.warning("MLXChatNode: generator empty, no prefill cache saved")

    # Continue with the rest of generation
    if not stop_detected:
        for response in generator:
            # Client cancellation (Bug C handoff): if the HTTP client closed
            # the connection, the route handler sets cancel_event so we exit
            # the loop here instead of running to max_tokens. Without this
            # check the worker thread would keep generating ~100s after the
            # user clicked Stop, blocking the single-worker MLX executor for
            # every subsequent request.
            if cancel_event is not None and cancel_event.is_set():
                logger.info("MLXChatNode: cancel_event set — breaking stream loop")
                break
            stop_detected = _emit_token(response, stop_sequences, full_response,
                                        generated_tokens, stream_callback)
            last_response = response
            if stop_detected:
                break

    return "".join(full_response), last_response, generated_tokens


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
    Saves the cache after generation (clean messages, without memory context).

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

    # Clean GPT-OSS special tags (<|channel|>, ◁...▷) before caching
    text = re.sub(r'<\|[^|]+\|>', '', text)
    text = re.sub(r'[◁◀][^▷▶]*[▷▶]', '', text)

    try:
        # Check if it already ends with assistant (for placeholders)
        if all_cache_messages and all_cache_messages[-1].get("role") == "assistant":
            # Merge with the last assistant message
            cache_messages_with_response = all_cache_messages[:-1] + [{
                "role": "assistant",
                "content": all_cache_messages[-1]["content"] + "\n\n" + text
            }]
            logger.debug("MLXChatNode: merged response with last assistant (cache)")
        else:
            # Add normally
            cache_messages_with_response = all_cache_messages + [{"role": "assistant", "content": text}]

        # Tokenize WITHOUT generation_prompt (the next turn will have it)
        cache_text = tokenizer.apply_chat_template(
            cache_messages_with_response,
            add_generation_prompt=False,
            tokenize=False
        )
        cache_tokens = tokenizer.encode(cache_text) if isinstance(cache_text, str) else list(cache_text)

        cache_manager.insert_cache(model_key, cache_tokens, cached_kv)
        logger.debug(
            "MLXChatNode: saved cache (clean messages, %d tokens → %d with response)",
            full_tokens_count, len(cache_tokens)
        )
    except Exception as e:
        # If the cache fails, do not block the response
        logger.warning(
            "MLXChatNode: cache save failed (non-blocking): %s",
            str(e)[:100]
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
    Extracts metrics from the generation response.

    Args:
        last_response: Last response from the generator
        text: Generated text
        prefix_reused: Whether a prefix was reused
        cached_token_count: Cached tokens
        total_tokens: Total prompt tokens
        new_tokens: New tokens processed
        identity_hash: System prompt hash

    Returns:
        Dict with metrics
    """
    if last_response:
        # actual_prefill = tokens actually processed (not cached)
        if prefix_reused and len(new_tokens) == 0:
            actual_prefill_tokens = 1  # Exact match: BOS token only
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
            "cache_active": prefix_reused,  # Alias for compatibility
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
