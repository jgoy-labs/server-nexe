# -*- coding: utf-8 -*-
"""
MLX Generation Helper Functions.

Funcions auxiliars per la generació MLX amb prefix caching.
"""
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def sanitize_messages_for_alternation(messages: List[Dict]) -> List[Dict]:
    """
    Sanititza missatges per assegurar alternança estricta user/assistant.

    Alguns models (Gemma, etc.) requereixen rols estrictament alternats.
    Aquesta funció:
    - Fusiona missatges consecutius del mateix rol
    - Assegura que comença amb "user" (afegeix placeholder si cal)
    - Assegura alternança user/assistant/user/assistant/...

    Args:
        messages: Llista de missatges [{role, content}, ...]

    Returns:
        Llista sanititzada amb rols alternats
    """
    if not messages:
        return []

    # Filtrar system messages (ja s'afegeix separat)
    filtered = [m for m in messages if m.get("role") != "system"]

    if not filtered:
        return []

    # Fusionar missatges consecutius del mateix rol
    merged = []
    for msg in filtered:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if merged and merged[-1]["role"] == role:
            # Fusionar amb l'anterior
            merged[-1]["content"] += "\n\n" + content
        else:
            merged.append({"role": role, "content": content})

    # Assegurar que comença amb "user"
    if merged and merged[0]["role"] != "user":
        # Si comença amb assistant, afegir un user placeholder
        merged.insert(0, {"role": "user", "content": "(continua)"})

    # Verificar alternança i corregir si cal
    sanitized = []
    expected_role = "user"

    for msg in merged:
        if msg["role"] == expected_role:
            sanitized.append(msg)
            expected_role = "assistant" if expected_role == "user" else "user"
        elif msg["role"] == "assistant" and expected_role == "user":
            # Falta un user, inserir placeholder
            sanitized.append({"role": "user", "content": "(continua)"})
            sanitized.append(msg)
            expected_role = "user"
        elif msg["role"] == "user" and expected_role == "assistant":
            # Falta un assistant, inserir placeholder
            sanitized.append({"role": "assistant", "content": "(entès)"})
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
    Prepara i tokenitza els missatges per generació i cache.

    Args:
        system: System prompt
        messages: Missatges per generació (amb memòria)
        messages_for_cache: Missatges nets per cache (sense memòria)
        tokenizer: Tokenizer MLX

    Returns:
        Tuple: (full_tokens, cache_lookup_tokens, all_messages, all_cache_messages)
    """
    # Sanititzar missatges per alternança estricta (Gemma, etc.)
    sanitized_messages = sanitize_messages_for_alternation(messages)
    sanitized_cache_messages = sanitize_messages_for_alternation(messages_for_cache)

    # Construir missatges format OpenAI
    all_messages = [{"role": "system", "content": system}] + sanitized_messages
    all_cache_messages = [{"role": "system", "content": system}] + sanitized_cache_messages

    # Tokenitzar per generació (amb memòria)
    prompt_text = tokenizer.apply_chat_template(
        all_messages,
        add_generation_prompt=True,
        tokenize=False
    )
    if isinstance(prompt_text, str):
        full_tokens = tokenizer.encode(prompt_text)
    else:
        full_tokens = list(prompt_text)

    # Tokenitzar per cache lookup (nets, sense memòria)
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
    Busca al cache el prefix més llarg que coincideix.

    Args:
        cache_manager: MLXPromptCacheManager
        model_key: Clau del model (path + hash + session)
        cache_lookup_tokens: Tokens nets per lookup
        model: Model MLX
        max_kv_size: Mida màxima KV cache

    Returns:
        Tuple: (cached_kv, cached_token_count, prefix_reused)
    """
    from mlx_lm.models.cache import make_prompt_cache

    cached_kv, remaining_tokens = cache_manager.fetch_nearest_cache(
        model_key, cache_lookup_tokens
    )

    # Si no hi ha cache, crear-ne un de nou
    if cached_kv is None:
        cached_kv = make_prompt_cache(model, max_kv_size=max_kv_size)

    # Calcular quants tokens del prefix estan cached
    cached_token_count = len(cache_lookup_tokens) - len(remaining_tokens)
    prefix_reused = cached_token_count > 0

    return cached_kv, cached_token_count, prefix_reused


def determine_tokens_to_process(
    full_tokens: List[int],
    cached_token_count: int,
    prefix_reused: bool,
) -> Tuple[Any, List[int]]:
    """
    Determina quins tokens processar basant-se en el cache.

    Args:
        full_tokens: Tots els tokens (amb memòria)
        cached_token_count: Tokens ja cached
        prefix_reused: Si s'ha reutilitzat prefix

    Returns:
        Tuple: (tokens_to_process_mx, new_tokens_list)
    """
    import mlx.core as mx

    new_tokens = full_tokens[cached_token_count:] if cached_token_count > 0 else full_tokens

    if prefix_reused and len(new_tokens) == 0:
        # Exact match (rar): processar mínim 1 token per estabilitat
        tokens_to_process = mx.array([full_tokens[0]])
        logger.debug("MLXChatNode: exact match, processing BOS token (~10ms overhead)")
    elif prefix_reused:
        # Prefix match: processar només tokens nous (AMB memòria)
        tokens_to_process = mx.array(new_tokens)
        logger.debug(
            "MLXChatNode: prefix match, processing %d new tokens (with memory)",
            len(new_tokens)
        )
    else:
        # No match: processar tot
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
    model_path: str = "",
) -> Tuple[str, Any, List[int]]:
    """
    Executa la generació amb streaming.

    Args:
        model: Model MLX
        tokenizer: Tokenizer
        tokens_to_process: Tokens a processar (mx.array)
        max_tokens: Màxim tokens a generar
        sampler: Sampler per generació
        cached_kv: Cache KV
        stream_callback: Callback per streaming
        cache_manager: Cache manager per guardar post-prefill
        model_key: Clau del model
        cache_lookup_tokens: Tokens per guardar al cache

    Returns:
        Tuple: (text, last_response, generated_tokens)
    """
    from mlx_lm import stream_generate

    full_response = []
    last_response = None
    generated_tokens = []

    # Stop tokens comuns per diferents models
    # Post-processarem la resposta per tallar quan apareguin
    _is_gpt_oss = "gpt-oss" in model_path.lower()
    if _is_gpt_oss:
        # GPT-OSS: només EOS real — els tags <|...|> són canals interns
        STOP_SEQUENCES = ["<|endoftext|>"]
    else:
        STOP_SEQUENCES = [
            "<|end|>", "<|endoftext|>",  # Phi-3.5, GPT
            "</s>",  # Llama 2
            "<|eot_id|>",  # Llama 3.x
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

    # Primera iteració: prefill + primer token
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

        # GUARDAR CACHE POST-PREFILL (abans que la resta faci timeout!)
        cache_manager.insert_cache(model_key, cache_lookup_tokens, cached_kv)
        logger.info(
            "MLXChatNode: cache saved post-prefill (%d tokens, key=%s)",
            len(cache_lookup_tokens), model_key[:30]
        )
    except StopIteration:
        logger.warning("MLXChatNode: generator empty, no prefill cache saved")

    # Continuar amb la resta de la generació
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
    Guarda el cache després de la generació (messages nets, sense context de memòria).

    Args:
        cache_manager: Cache manager
        model_key: Clau del model
        all_cache_messages: Missatges nets (sense memòria)
        text: Text generat
        tokenizer: Tokenizer
        cached_kv: Cache KV
        full_tokens_count: Nombre de tokens del prompt complet
    """
    if not text.strip():
        return

    # Netejar tags especials de GPT-OSS (<|channel|>, ◁...▷) abans de cache
    text = re.sub(r'<\|[^|]+\|>', '', text)
    text = re.sub(r'[◁◀][^▷▶]*[▷▶]', '', text)

    try:
        # Verificar si ja acaba amb assistant (pels placeholders)
        if all_cache_messages and all_cache_messages[-1].get("role") == "assistant":
            # Fusionar amb l'últim assistant
            cache_messages_with_response = all_cache_messages[:-1] + [{
                "role": "assistant",
                "content": all_cache_messages[-1]["content"] + "\n\n" + text
            }]
            logger.debug("MLXChatNode: merged response with last assistant (cache)")
        else:
            # Afegir normalment
            cache_messages_with_response = all_cache_messages + [{"role": "assistant", "content": text}]

        # Tokenitzar SENSE generation_prompt (el proper torn el tindrà)
        cache_text = tokenizer.apply_chat_template(
            cache_messages_with_response,
            add_generation_prompt=False,
            tokenize=False
        )
        cache_tokens = tokenizer.encode(cache_text) if isinstance(cache_text, str) else list(cache_text)

        cache_manager.insert_cache(model_key, cache_tokens, cached_kv)
        logger.debug(
            "MLXChatNode: saved cache (messages nets, %d tokens → %d with response)",
            full_tokens_count, len(cache_tokens)
        )
    except Exception as e:
        # Si falla el cache, no bloquegem la resposta
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
    Extreu mètriques de la resposta de generació.

    Args:
        last_response: Última resposta del generador
        text: Text generat
        prefix_reused: Si s'ha reutilitzat prefix
        cached_token_count: Tokens cached
        total_tokens: Total tokens del prompt
        new_tokens: Tokens nous processats
        identity_hash: Hash del system prompt

    Returns:
        Dict amb mètriques
    """
    if last_response:
        # actual_prefill = tokens realment processats (no cached)
        if prefix_reused and len(new_tokens) == 0:
            actual_prefill_tokens = 1  # Exact match: només BOS token
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
