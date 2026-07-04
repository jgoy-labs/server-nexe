# -*- coding: utf-8 -*-
"""
LlamaCppChatNode - llama-cpp-python node with cache.

Uses ModelPool for session management with LRU.
llama.cpp has automatic prefix caching when the prefix is identical.

"""
import asyncio
import atexit
import base64
import functools
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .config import LlamaCppConfig
from .model_pool import ModelPool
from core.utils import compute_system_hash
from plugins._shared.chat_node import make_threadsafe_callback, base_chat_result

logger = logging.getLogger(__name__)

# B190/MC-011: llama-cpp-python is NOT thread-safe — concurrent
# create_chat_completion() on the same Llama instance corrupts the native KV
# cache. asyncio.to_thread() dispatches to the default multi-worker pool, so two
# concurrent /chat requests on the shared "default" session generated on the
# same context at once. Pin all generation to a single dedicated worker thread
# (the same fix MLX uses via _MLX_EXECUTOR): with max_workers=1 generations
# serialise on one thread instead of racing.
_LLAMA_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llama-worker")

# Tear the worker down even if a generation is mid-flight (Stop button race,
# sidecar SIGTERM) so the interpreter doesn't hang at exit draining it.
atexit.register(_LLAMA_EXECUTOR.shutdown, wait=False, cancel_futures=True)


class LlamaCppChatNode:
    """
    Inference engine for Llama.cpp adapted for server-nexe.

    Uses ModelPool to manage Llama instances with LRU eviction.
    Each session can have its own instance (if max_sessions > 1).
    llama.cpp prefix caching is leveraged when system_hash is identical.
    """

    # Singleton pool shared across all node instances
    _pool: Optional[ModelPool] = None
    _config: Optional[LlamaCppConfig] = None

    def __init__(self, config: Optional[LlamaCppConfig] = None):
        self.config = config or LlamaCppConfig.from_env()

        # Initialize singleton pool (lazy)
        if (LlamaCppChatNode._pool is None or
                LlamaCppChatNode._config != self.config):
            LlamaCppChatNode._config = self.config
            LlamaCppChatNode._pool = ModelPool(self.config)
            logger.info(
                "LlamaCppChatNode: initialized ModelPool (max_sessions=%d)",
                self.config.max_sessions
            )

    def apply_config(self, new_config: "LlamaCppConfig") -> None:
        """Hot-swap the active model config and rebuild the shared ModelPool.

        Mirrors __init__'s pool setup: tears down the old pool's sessions,
        swaps _config and replaces _pool with one bound to the new config.
        Public entry point so web_ui calls LlamaCppModule.switch_model()
        instead of poking these class-level privates directly (B073).
        """
        if LlamaCppChatNode._pool is not None:
            LlamaCppChatNode._pool.destroy_all()
        self.config = new_config
        LlamaCppChatNode._config = new_config
        LlamaCppChatNode._pool = ModelPool(new_config)

    def _get_model(self, session_id: str, system_hash: str) -> tuple[Any, bool]:
        """
        Get model from the pool for this session.

        Args:
            session_id: Session ID (uses "default" if empty)
            system_hash: Hash of the system prompt (normalised)

        Returns:
            Tuple (Llama instance, cache_hit: bool)
        """
        if not session_id:
            session_id = "default"

        return LlamaCppChatNode._pool.get_or_create(session_id, system_hash)  # type: ignore[union-attr]  # invariant: __init__ L42 always initialises _pool = ModelPool(config)


    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        system = inputs.get("system", "")
        messages = inputs.get("messages", [])
        system_hash = inputs.get("system_hash", "")
        session_id = inputs.get("session_id", "default") or "default"
        stream_callback = inputs.get("stream_callback")
        max_tokens_override = inputs.get("max_tokens")
        temperature_override = inputs.get("temperature")
        top_p_override = inputs.get("top_p")  # opt-in nucleus sampling; None → 0.9 default
        images = inputs.get("images")  # Optional[List[bytes]] — VLM support
        # cancel_event: threading.Event-like; the route handler sets it when the
        # HTTP client disconnects so the streaming loop can break early instead
        # of running to max_tokens (orphan worker blocking the instance). None
        # disables cancellation (back-compat).
        cancel_event = inputs.get("cancel_event")

        # Graceful fallback: if there is an image but no mmproj, warn and ignore the image
        if images and not self.config.mmproj_path:
            logger.warning(
                "LlamaCppChatNode: images provided but LLAMA_MMPROJ_PATH not set. "
                "Ignoring images and falling back to text-only. "
                "Set LLAMA_MMPROJ_PATH to enable VLM support."
            )
            images = None

        if not system_hash:
            system_hash = compute_system_hash(system)

        logger.info(
            "LlamaCppChatNode: session=%s, hash=%s, messages=%d",
            session_id[:8],
            system_hash[:8],
            len(messages)
        )

        # Capture event loop for thread-safe streaming
        loop = asyncio.get_running_loop()

        threadsafe_callback = make_threadsafe_callback(loop, stream_callback)

        try:
            # Get model from pool (handles cache/reset automatically)
            model, cache_hit = self._get_model(session_id, system_hash)

            # Execute with create_chat_completion — VLM/text branch.
            # Pin to the dedicated single-worker executor so generations on the
            # shared instance serialise (B190) instead of racing on the default
            # multi-worker pool.
            if images and self.config.mmproj_path:
                # VLM path: images + clip model configured
                if stream_callback:
                    result = await loop.run_in_executor(
                        _LLAMA_EXECUTOR,
                        functools.partial(
                            self._generate_vlm_streaming,
                            model, system, messages, images, threadsafe_callback,
                            max_tokens_override, temperature_override, cancel_event,
                            top_p=top_p_override,
                        ),
                    )
                else:
                    result = await loop.run_in_executor(
                        _LLAMA_EXECUTOR,
                        functools.partial(
                            self._generate_vlm,
                            model, system, messages, images,
                            max_tokens_override, temperature_override,
                            top_p=top_p_override,
                        ),
                    )
            elif stream_callback:
                result = await loop.run_in_executor(
                    _LLAMA_EXECUTOR,
                    functools.partial(
                        self._generate_streaming,
                        model, system, messages, threadsafe_callback,
                        max_tokens_override, temperature_override, cancel_event,
                        top_p=top_p_override,
                    ),
                )
            else:
                result = await loop.run_in_executor(
                    _LLAMA_EXECUTOR,
                    functools.partial(
                        self._generate,
                        model, system, messages,
                        max_tokens_override, temperature_override,
                        top_p=top_p_override,
                    ),
                )

            elapsed_ms = int((time.time() - start_time) * 1000)

            tokens_per_second = 0.0
            if elapsed_ms > 0 and result["tokens"] > 0:
                tokens_per_second = result["tokens"] / (elapsed_ms / 1000)

            context_used = result["prompt_tokens"] + result["tokens"]
            system_tokens = len(system) // 4  # Estimate

            # Get timing from the result
            timing = result.get("timing", {})

            logger.info(
                "LlamaCppChatNode: %s in %dms (p:%d g:%d), %.1f tok/s, prompt=%d, gen=%d",
                "HIT" if cache_hit else "MISS",
                elapsed_ms,
                timing.get("prefill_ms", 0),
                timing.get("generation_ms", 0),
                tokens_per_second,
                result["prompt_tokens"],
                result["tokens"]
            )

            return {
                **base_chat_result(
                    response=result["text"],
                    model_used=self.config.model_path,
                    elapsed_ms=elapsed_ms,
                    tokens=result["tokens"],
                    tokens_per_second=tokens_per_second,
                    prompt_tokens=result["prompt_tokens"],
                    context_used=context_used,
                    system_tokens=system_tokens,
                    system_prompt=system,
                ),
                "session_id": session_id,
                "cache_hit": cache_hit,  # Restored for compatibility
                "timing": timing,
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error("LlamaCppChatNode error after %dms: %s", elapsed_ms, str(e))
            raise

    def _generate(
        self,
        model: Any,
        system: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate a response without streaming."""
        all_messages = [{"role": "system", "content": system}] + messages

        start_time = time.time()
        response = model.create_chat_completion(
            messages=all_messages,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            temperature=temperature if temperature is not None else 0.7,
            top_p=top_p if top_p is not None else 0.9,
            stop=self._STOP_SEQUENCES,
        )
        end_time = time.time()

        # Without streaming we cannot distinguish prefill from generation
        total_ms = int((end_time - start_time) * 1000)

        return {
            "text": response["choices"][0]["message"]["content"],
            "tokens": response["usage"]["completion_tokens"],
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "timing": {
                "prefill_ms": 0,  # Not measurable without streaming
                "generation_ms": total_ms,
                "overhead_ms": 0,
                "prefill_available": False,  # TTFT not measurable without streaming
            },
        }

    def _generate_streaming(
        self,
        model: Any,
        system: str,
        messages: List[Dict],
        stream_callback: Any,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        cancel_event: Any = None,
        top_p: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate a response with streaming."""
        all_messages = [{"role": "system", "content": system}] + messages

        full_response = []
        prompt_tokens = 0
        completion_tokens = 0

        # Timing breakdown
        start_time = time.time()
        first_token_time = None

        for chunk in model.create_chat_completion(
            messages=all_messages,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            temperature=temperature if temperature is not None else 0.7,
            top_p=top_p if top_p is not None else 0.9,
            stream=True,
            stop=self._STOP_SEQUENCES,
        ):
            # MC-011: the route handler sets cancel_event when the HTTP client
            # disconnects; exit early instead of generating to max_tokens.
            if cancel_event is not None and cancel_event.is_set():
                logger.info("LlamaCppChatNode: cancel_event set — breaking stream loop")
                break

            delta = chunk.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")

            if content:
                # Mark TTFT (Time To First Token)
                if first_token_time is None:
                    first_token_time = time.time()

                full_response.append(content)
                if callable(stream_callback):
                    stream_callback(content)

            usage = chunk.get("usage", {})
            if usage:
                prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                completion_tokens = usage.get("completion_tokens", completion_tokens)

        end_time = time.time()
        text = "".join(full_response)
        if completion_tokens == 0:
            completion_tokens = len(text) // 4

        # Calculate timing breakdown
        if first_token_time:
            prefill_ms = int((first_token_time - start_time) * 1000)
            generation_ms = int((end_time - first_token_time) * 1000)
        else:
            prefill_ms = 0
            generation_ms = int((end_time - start_time) * 1000)

        return {
            "text": text,
            "tokens": completion_tokens,
            "prompt_tokens": prompt_tokens,
            "timing": {
                "prefill_ms": prefill_ms,      # TTFT - Time To First Token
                "prefill_available": True,     # TTFT available via streaming
                "generation_ms": generation_ms, # Generation time
                "overhead_ms": 0,
            },
        }

    @staticmethod
    def _build_vlm_messages(
        system: str,
        messages: List[Dict],
        images: List[bytes],
    ) -> List[Dict]:
        """Build multimodal messages with base64 image data URIs for llama-cpp-python VLM."""
        all_messages = [{"role": "system", "content": system}]

        has_user_msg = any(m.get("role") == "user" for m in messages)
        if images and not has_user_msg:
            logger.warning(
                "LlamaCppChatNode: images provided but no user message found. "
                "Images will be ignored."
            )
            images = []

        for msg in messages:
            if msg["role"] == "user" and images:
                # Format OpenAI-compatible: content as list with text + image_url
                content_parts: List[Dict[str, Any]] = [
                    {"type": "text", "text": msg.get("content", "")},
                ]
                for img_bytes in images:
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    })
                all_messages.append({"role": "user", "content": content_parts})  # type: ignore[dict-item]  # VLM: content_parts is list[dict], all_messages expects list[str] but accepts VLM format
                # Only inject images into the first user message
                images = []
            else:
                all_messages.append(msg)

        return all_messages

    # Stop sequences shared across all generation methods
    _STOP_SEQUENCES = [
        "<|end|>", "<|endoftext|>",  # Phi-3.5, GPT
        "</s>",  # Llama 2
        "<|eot_id|>",  # Llama 3.x
        "<end_of_turn>",  # Gemma
        "<|im_end|>",  # ChatML format
    ]

    def _generate_vlm(
        self,
        model: Any,
        system: str,
        messages: List[Dict],
        images: List[bytes],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate a VLM response without streaming (images + clip model)."""
        all_messages = self._build_vlm_messages(system, messages, images)

        start_time = time.time()
        response = model.create_chat_completion(
            messages=all_messages,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            temperature=temperature if temperature is not None else 0.7,
            top_p=top_p if top_p is not None else 0.9,
            stop=self._STOP_SEQUENCES,
        )
        end_time = time.time()
        total_ms = int((end_time - start_time) * 1000)

        return {
            "text": response["choices"][0]["message"]["content"],
            "tokens": response["usage"]["completion_tokens"],
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "timing": {
                "prefill_ms": 0,
                "generation_ms": total_ms,
                "overhead_ms": 0,
                "prefill_available": False,
            },
        }

    def _generate_vlm_streaming(
        self,
        model: Any,
        system: str,
        messages: List[Dict],
        images: List[bytes],
        stream_callback: Any,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        cancel_event: Any = None,
        top_p: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate a VLM response with streaming (images + clip model)."""
        all_messages = self._build_vlm_messages(system, messages, images)

        full_response = []
        prompt_tokens = 0
        completion_tokens = 0

        start_time = time.time()
        first_token_time = None

        for chunk in model.create_chat_completion(
            messages=all_messages,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            temperature=temperature if temperature is not None else 0.7,
            top_p=top_p if top_p is not None else 0.9,
            stream=True,
            stop=self._STOP_SEQUENCES,
        ):
            # MC-011: break early when the route handler cancels (HTTP disconnect).
            if cancel_event is not None and cancel_event.is_set():
                logger.info("LlamaCppChatNode: cancel_event set — breaking VLM stream loop")
                break

            delta = chunk.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")

            if content:
                if first_token_time is None:
                    first_token_time = time.time()
                full_response.append(content)
                if callable(stream_callback):
                    stream_callback(content)

            usage = chunk.get("usage", {})
            if usage:
                prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                completion_tokens = usage.get("completion_tokens", completion_tokens)

        end_time = time.time()
        text = "".join(full_response)
        if completion_tokens == 0:
            completion_tokens = len(text) // 4

        if first_token_time:
            prefill_ms = int((first_token_time - start_time) * 1000)
            generation_ms = int((end_time - first_token_time) * 1000)
        else:
            prefill_ms = 0
            generation_ms = int((end_time - start_time) * 1000)

        return {
            "text": text,
            "tokens": completion_tokens,
            "prompt_tokens": prompt_tokens,
            "timing": {
                "prefill_ms": prefill_ms,
                "prefill_available": True,
                "generation_ms": generation_ms,
                "overhead_ms": 0,
            },
        }

    @classmethod
    def reset_model(cls) -> None:
        """Destroy all pool sessions and free memory."""
        if cls._pool is not None:
            cls._pool.destroy_all()
            logger.info("LlamaCppChatNode: all sessions destroyed via pool")

    @classmethod
    def get_pool_stats(cls) -> Optional[Dict]:
        """Return model pool statistics."""
        if cls._pool is None:
            return {
                "pool_initialized": False,
                "active_sessions": 0,
                "max_sessions": 0,
            }
        stats = cls._pool.get_stats()
        stats["pool_initialized"] = True
        return stats
