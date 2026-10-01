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
from core.turn.reasoning import finish_split, wrap_for_split

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


def split_resumed_answer(messages: List[Dict], continue_final: bool) -> tuple:
    """(messages before the cut answer, its raw text).

    A resume that is not sitting on an assistant message refuses: generating
    from scratch here would glue a new answer onto the cut one. No resume
    returns the messages unchanged and ``None``.
    """
    if not continue_final:
        return messages, None
    if not messages or messages[-1].get("role") != "assistant":
        raise RuntimeError("continue on llama.cpp needs the cut assistant message")
    return messages[:-1], messages[-1].get("content") or ""


def _resume_formatters() -> Dict[str, Any]:
    """The library formatters the config's names actually render with.

    ``Llama.create_chat_completion`` has no continue flag: every stock
    formatter closes the last message and then opens a fresh assistant turn.
    A resume renders the messages *without* the cut answer (that already
    opens the turn) and appends the raw text. Names are the config's, which
    are not always the library's (``mistral`` is ``mistral-instruct``).
    ``phi-3`` is absent on purpose: the installed library has no formatter
    under that name, and guessing chatml would resume against a different
    template than the one that cut the answer.
    """
    from llama_cpp.llama_chat_format import (
        format_alpaca,
        format_chatml,
        format_gemma,
        format_llama2,
        format_llama3,
        format_mistral_instruct,
    )

    return {
        "chatml": format_chatml,
        "llama-2": format_llama2,
        "llama-3": format_llama3,
        "gemma": format_gemma,
        "alpaca": format_alpaca,
        "mistral": format_mistral_instruct,
    }


def render_resume_prompt(chat_format: str, messages: List[Dict], partial: str) -> str:
    """Prompt that ends on ``partial``, with the assistant turn still open."""
    formatter = _resume_formatters().get(chat_format)
    if formatter is None:
        raise RuntimeError(
            f"continue is not supported for llama.cpp chat_format {chat_format!r}"
        )
    return formatter(messages=messages).prompt + partial


def _chat_chunk_text(choice: Dict) -> str:
    delta = choice.get("delta") or {}
    return delta.get("content") or ""


def _completion_chunk_text(choice: Dict) -> str:
    return choice.get("text") or ""


def _chunk_choice(chunk: Dict) -> Dict:
    choices = chunk.get("choices") or [{}]
    return choices[0] or {}


def _note_usage(chunk: Dict, prompt_tokens: int, completion_tokens: int) -> tuple:
    usage = chunk.get("usage") or {}
    if not usage:
        return prompt_tokens, completion_tokens
    return (
        usage.get("prompt_tokens", prompt_tokens),
        usage.get("completion_tokens", completion_tokens),
    )


def _split_timing(start: float, first: Optional[float], end: float) -> tuple:
    if not first:
        return 0, int((end - start) * 1000)
    return int((first - start) * 1000), int((end - first) * 1000)


def continuable_answer(
    finish_reason: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
    *,
    n_ctx: int,
    reply_ceiling: int,
) -> bool:
    """Length, and room for another reply before the context window fills.

    Same headroom MLX uses against its KV window (``max_tokens + 512``): a
    Continue chain must not cross the window. ``reply_ceiling`` is the
    config's ceiling, the size of the *next* continue, not the call that
    just hit the limit.
    """
    if finish_reason != "length":
        return False
    used = prompt_tokens + completion_tokens
    return used + reply_ceiling + 512 < n_ctx


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
        # Only an explicit True. A MagicMock grows a truthy `.resume` / flag
        # and must not be treated as a continue.
        continue_final = inputs.get("continue_final", False) is True

        # #1107: the vision handler renders inside create_chat_completion and
        # always closes the assistant turn. A string completion would keep
        # the cut text and lose the picture. Refuse, and do it as a plain
        # runtime error so the cascade can offer the turn to an engine that
        # can continue an image (MLX). A ValueError would end the turn for
        # every engine.
        if continue_final and images:
            raise RuntimeError("continue with images is not supported by llama.cpp")

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

        # ADR-010: a model served here writes its reasoning INTO the text
        # (<think> tags, or gpt-oss harmony); this plugin splits it and hands
        # the caller {thinking, content} chunks. There is no switch to turn a
        # model's reasoning off from here: `thinking_enabled` is not honoured,
        # and what the model writes is split, not hidden.
        split = {"starts_inside": False, "harmony": "gpt-oss" in str(self.config.model_path).lower()}
        to_bridge, structured_cb = wrap_for_split(stream_callback, split)
        threadsafe_callback = make_threadsafe_callback(loop, to_bridge)

        try:
            # Get model from pool (handles cache/reset automatically)
            model, cache_hit = self._get_model(session_id, system_hash)

            # Execute with create_chat_completion — VLM/text branch.
            # Pin to the dedicated single-worker executor so generations on the
            # shared instance serialise (B190) instead of racing on the default
            # multi-worker pool.
            result = await self._run_generation(
                loop, model, system, messages, images, stream_callback,
                threadsafe_callback, max_tokens_override, temperature_override,
                top_p_override, cancel_event, continue_final,
            )

            reasoning_text, response_text = finish_split(structured_cb, split, result["text"])

            elapsed_ms = int((time.time() - start_time) * 1000)

            tokens_per_second = 0.0
            if elapsed_ms > 0 and result["tokens"] > 0:
                tokens_per_second = result["tokens"] / (elapsed_ms / 1000)

            context_used = result["prompt_tokens"] + result["tokens"]
            system_tokens = len(system) // 4  # Estimate
            finish_reason, can_resume = self._answer_flags(result, images)

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
                    response=response_text,
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
                "thinking": reasoning_text,  # ADR-010: apart from the answer
                "cache_hit": cache_hit,  # Restored for compatibility
                "timing": timing,
                "finish_reason": finish_reason,
                "continuable": can_resume,
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error("LlamaCppChatNode error after %dms: %s", elapsed_ms, str(e))
            raise

    async def _run_generation(
        self, loop, model, system, messages, images, stream_callback,
        threadsafe_callback, max_tokens, temperature, top_p, cancel_event,
        continue_final,
    ):
        """One generation on the single worker thread. Vision when the clip
        model is loaded; a resume only on the text path."""
        if images and self.config.mmproj_path:
            if stream_callback:
                work = functools.partial(
                    self._generate_vlm_streaming,
                    model, system, messages, images, threadsafe_callback,
                    max_tokens, temperature, cancel_event, top_p=top_p,
                )
            else:
                work = functools.partial(
                    self._generate_vlm,
                    model, system, messages, images,
                    max_tokens, temperature, top_p=top_p,
                )
        elif stream_callback:
            work = functools.partial(
                self._generate_streaming,
                model, system, messages, threadsafe_callback,
                max_tokens, temperature, cancel_event,
                top_p=top_p, continue_final=continue_final,
            )
        else:
            work = functools.partial(
                self._generate,
                model, system, messages,
                max_tokens, temperature, top_p=top_p, continue_final=continue_final,
            )
        return await loop.run_in_executor(_LLAMA_EXECUTOR, work)

    def _answer_flags(self, result: Dict[str, Any], images) -> tuple:
        """(finish_reason, continuable) for the web button and the /v1 client.

        A disconnect is not a ceiling cut. A vision answer reports the cut
        and leaves the button off: resuming it would drop the picture.
        """
        finish_reason = result.get("finish_reason")
        if result.get("cancelled"):
            finish_reason = None
        if images and self.config.mmproj_path:
            return finish_reason, False
        prompt_tokens = result.get("prompt_tokens") or 0
        completion_tokens = result.get("tokens") or 0
        return finish_reason, continuable_answer(
            finish_reason,
            prompt_tokens,
            completion_tokens,
            n_ctx=self.config.n_ctx,
            reply_ceiling=self.config.max_tokens,
        )

    def _sampling(self, max_tokens, temperature, top_p) -> Dict[str, Any]:
        return {
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "temperature": temperature if temperature is not None else 0.7,
            "top_p": top_p if top_p is not None else 0.9,
            "stop": self._STOP_SEQUENCES,
        }

    def _generate(
        self,
        model: Any,
        system: str,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        continue_final: bool = False,
    ) -> Dict[str, Any]:
        """Generate a response without streaming."""
        prefix, partial = split_resumed_answer(messages, continue_final)
        if partial is not None:
            return self._generate_resume(
                model, system, prefix, partial, max_tokens, temperature, top_p,
            )
        all_messages = [{"role": "system", "content": system}] + messages

        start_time = time.time()
        response = model.create_chat_completion(
            messages=all_messages,
            **self._sampling(max_tokens, temperature, top_p),
        )
        end_time = time.time()

        # Without streaming we cannot distinguish prefill from generation
        total_ms = int((end_time - start_time) * 1000)
        choice = response["choices"][0]

        return {
            "text": choice["message"]["content"],
            "tokens": response["usage"]["completion_tokens"],
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "finish_reason": choice.get("finish_reason"),
            "cancelled": False,
            "timing": {
                "prefill_ms": 0,  # Not measurable without streaming
                "generation_ms": total_ms,
                "overhead_ms": 0,
                "prefill_available": False,  # TTFT not measurable without streaming
            },
        }

    def _generate_resume(
        self,
        model: Any,
        system: str,
        messages: List[Dict],
        partial: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Continue ``partial``. The prompt ends on that text; only the tail comes back."""
        prompt = render_resume_prompt(
            self.config.chat_format,
            [{"role": "system", "content": system}] + messages,
            partial,
        )
        start_time = time.time()
        response = model.create_completion(
            prompt=prompt,
            echo=False,
            **self._sampling(max_tokens, temperature, top_p),
        )
        total_ms = int((time.time() - start_time) * 1000)
        choice = response["choices"][0]
        return {
            "text": choice.get("text") or "",
            "tokens": response["usage"]["completion_tokens"],
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "finish_reason": choice.get("finish_reason"),
            "cancelled": False,
            "timing": {
                "prefill_ms": 0,
                "generation_ms": total_ms,
                "overhead_ms": 0,
                "prefill_available": False,
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
        continue_final: bool = False,
    ) -> Dict[str, Any]:
        """Generate a response with streaming."""
        prefix, partial = split_resumed_answer(messages, continue_final)
        if partial is not None:
            return self._generate_resume_streaming(
                model, system, prefix, partial, stream_callback,
                max_tokens, temperature, cancel_event, top_p,
            )
        all_messages = [{"role": "system", "content": system}] + messages
        return self._consume_stream(
            model.create_chat_completion(
                messages=all_messages,
                stream=True,
                **self._sampling(max_tokens, temperature, top_p),
            ),
            stream_callback,
            cancel_event,
            text_of=_chat_chunk_text,
        )

    def _generate_resume_streaming(
        self,
        model: Any,
        system: str,
        messages: List[Dict],
        partial: str,
        stream_callback: Any,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        cancel_event: Any = None,
        top_p: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Stream the tail. ``echo`` stays off, so the cut text is not re-sent."""
        prompt = render_resume_prompt(
            self.config.chat_format,
            [{"role": "system", "content": system}] + messages,
            partial,
        )
        return self._consume_stream(
            model.create_completion(
                prompt=prompt,
                echo=False,
                stream=True,
                **self._sampling(max_tokens, temperature, top_p),
            ),
            stream_callback,
            cancel_event,
            text_of=_completion_chunk_text,
        )

    def _consume_stream(
        self,
        chunks: Any,
        stream_callback: Any,
        cancel_event: Any,
        text_of: Any,
    ) -> Dict[str, Any]:
        """Drain a llama.cpp stream into the result dict both doors read."""
        full_response = []
        prompt_tokens = 0
        completion_tokens = 0
        finish_reason = None
        cancelled = False
        start_time = time.time()
        first_token_time = None

        for chunk in chunks:
            # MC-011: the route handler sets cancel_event when the HTTP client
            # disconnects; exit early instead of generating to max_tokens.
            if cancel_event is not None and cancel_event.is_set():
                logger.info("LlamaCppChatNode: cancel_event set — breaking stream loop")
                cancelled = True
                break

            choice = _chunk_choice(chunk)
            reason = choice.get("finish_reason")
            if reason:
                finish_reason = reason
            content = text_of(choice)

            if content:
                if first_token_time is None:
                    first_token_time = time.time()
                full_response.append(content)
                if callable(stream_callback):
                    stream_callback(content)

            prompt_tokens, completion_tokens = _note_usage(
                chunk, prompt_tokens, completion_tokens,
            )

        end_time = time.time()
        text = "".join(full_response)
        if completion_tokens == 0:
            completion_tokens = len(text) // 4
        prefill_ms, generation_ms = _split_timing(start_time, first_token_time, end_time)
        return {
            "text": text,
            "tokens": completion_tokens,
            "prompt_tokens": prompt_tokens,
            "finish_reason": None if cancelled else finish_reason,
            "cancelled": cancelled,
            "timing": {
                "prefill_ms": prefill_ms,
                "prefill_available": True,
                "generation_ms": generation_ms,
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
            **self._sampling(max_tokens, temperature, top_p),
        )
        end_time = time.time()
        total_ms = int((end_time - start_time) * 1000)
        choice = response["choices"][0]

        return {
            "text": choice["message"]["content"],
            "tokens": response["usage"]["completion_tokens"],
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "finish_reason": choice.get("finish_reason"),
            "cancelled": False,
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
        return self._consume_stream(
            model.create_chat_completion(
                messages=all_messages,
                stream=True,
                **self._sampling(max_tokens, temperature, top_p),
            ),
            stream_callback,
            cancel_event,
            text_of=_chat_chunk_text,
        )

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
