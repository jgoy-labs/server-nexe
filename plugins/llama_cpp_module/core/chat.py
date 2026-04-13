# -*- coding: utf-8 -*-
"""
LlamaCppChatNode - Node llama-cpp-python amb cache.

Usa ModelPool per gestió de sessions amb LRU.
llama.cpp té prefix caching automàtic quan el prefix és idèntic.

"""
import asyncio
import base64
import time
import logging
from typing import Any, Dict, List, Optional

from .config import LlamaCppConfig
from .model_pool import ModelPool
from core.utils import compute_system_hash

logger = logging.getLogger(__name__)


class LlamaCppChatNode:
    """
    Motor d'inferència per a Llama.cpp adaptat per a Nexe 0.9.

    Usa ModelPool per gestionar instàncies Llama amb LRU eviction.
    Cada sessió pot tenir la seva pròpia instància (si max_sessions > 1).
    El prefix caching de llama.cpp s'aprofita quan system_hash és idèntic.
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

    def _get_model(self, session_id: str, system_hash: str) -> tuple[Any, bool]:
        """
        Obtenir model del pool per aquesta sessió.

        Args:
            session_id: ID de sessió (usa "default" si buit)
            system_hash: Hash del system prompt (normalitzat)

        Returns:
            Tuple (instància Llama, cache_hit: bool)
        """
        if not session_id:
            session_id = "default"

        return LlamaCppChatNode._pool.get_or_create(session_id, system_hash)


    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        system = inputs.get("system", "")
        messages = inputs.get("messages", [])
        system_hash = inputs.get("system_hash", "")
        session_id = inputs.get("session_id", "default") or "default"
        stream_callback = inputs.get("stream_callback")
        max_tokens_override = inputs.get("max_tokens")
        temperature_override = inputs.get("temperature")
        images = inputs.get("images")  # Optional[List[bytes]] — VLM support

        # Graceful fallback: si hi ha imatge però no mmproj, advertim i ignoriem imatge
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

        # Capturar event loop per streaming thread-safe
        loop = asyncio.get_running_loop()

        def threadsafe_callback(piece: str):
            if stream_callback and callable(stream_callback):
                loop.call_soon_threadsafe(stream_callback, piece)

        try:
            # Get model from pool (handles cache/reset automatically)
            model, cache_hit = self._get_model(session_id, system_hash)

            # Executar amb create_chat_completion — bifurcació VLM/text
            if images and self.config.mmproj_path:
                # VLM path: imatges + clip model configurat
                if stream_callback:
                    result = await asyncio.to_thread(
                        self._generate_vlm_streaming,
                        model, system, messages, images, threadsafe_callback,
                        max_tokens_override, temperature_override,
                    )
                else:
                    result = await asyncio.to_thread(
                        self._generate_vlm,
                        model, system, messages, images,
                        max_tokens_override, temperature_override,
                    )
            elif stream_callback:
                result = await asyncio.to_thread(
                    self._generate_streaming,
                    model, system, messages, threadsafe_callback,
                    max_tokens_override, temperature_override,
                )
            else:
                result = await asyncio.to_thread(
                    self._generate,
                    model, system, messages,
                    max_tokens_override, temperature_override,
                )

            elapsed_ms = int((time.time() - start_time) * 1000)

            tokens_per_second = 0.0
            if elapsed_ms > 0 and result["tokens"] > 0:
                tokens_per_second = result["tokens"] / (elapsed_ms / 1000)

            context_used = result["prompt_tokens"] + result["tokens"]
            system_tokens = len(system) // 4  # Estimate

            # Obtenir timing del resultat
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
                "response": result["text"],
                "model_used": self.config.model_path,
                "elapsed_ms": elapsed_ms,
                "tokens": result["tokens"],
                "tokens_per_second": round(tokens_per_second, 1),
                "prompt_tokens": result["prompt_tokens"],
                "context_used": context_used,
                "system_tokens": system_tokens,
                "system_prompt": system,
                "session_id": session_id,
                "cache_hit": cache_hit,  # Restaurat per compatibilitat
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
    ) -> Dict[str, Any]:
        """Generate a response without streaming."""
        all_messages = [{"role": "system", "content": system}] + messages

        start_time = time.time()
        response = model.create_chat_completion(
            messages=all_messages,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            temperature=temperature if temperature is not None else 0.7,
            top_p=0.9,
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
                "prefill_ms": 0,  # No mesurable sense streaming
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
            top_p=0.9,
            stream=True,
            stop=self._STOP_SEQUENCES,
        ):
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")

            if content:
                # Marcar TTFT (Time To First Token)
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

        # Calcular timing breakdown
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
                all_messages.append({"role": "user", "content": content_parts})
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
    ) -> Dict[str, Any]:
        """Generate a VLM response without streaming (images + clip model)."""
        all_messages = self._build_vlm_messages(system, messages, images)

        start_time = time.time()
        response = model.create_chat_completion(
            messages=all_messages,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            temperature=temperature if temperature is not None else 0.7,
            top_p=0.9,
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
            top_p=0.9,
            stream=True,
            stop=self._STOP_SEQUENCES,
        ):
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
