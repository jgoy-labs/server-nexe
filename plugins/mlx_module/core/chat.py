# -*- coding: utf-8 -*-
"""
MLXChatNode - Node LLM basat en mlx-lm per Apple Silicon.

PREFIX MATCHING via MLXPromptCacheManager.

Característiques:
- Model singleton (carregat una vegada, reutilitzat)
- MLXPromptCacheManager: trie-based cache amb prefix matching
- Reutilitza KV states del prefix (system + historial)
- Només processa tokens nous a cada torn → speedup 5-10x

Requereix:
- Apple Silicon (M1/M2/M3/M4)
- mlx-lm >= 0.30.0
- Model MLX format (safetensors)

"""
import asyncio
import gc
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import MLXConfig
from .generate_helpers import (
    prepare_tokens,
    lookup_prefix_cache,
    determine_tokens_to_process,
    run_streaming_generation,
    save_cache_post_generation,
    extract_metrics,
)
from core.utils import compute_system_hash

logger = logging.getLogger(__name__)


# Arquitectures VLM conegudes (config.json → architectures[])
_VLM_ARCHITECTURES = {
    "Qwen2VLForConditionalGeneration",
    "LlavaNextForConditionalGeneration",
    "LlavaForConditionalGeneration",
    "PaliGemmaForConditionalGeneration",
    "Gemma3ForConditionalGeneration",
    "InternVLChatModel",
}


def _detect_vlm_capability(model_path: str) -> bool:
    """Llegeix config.json del model per detectar si és VLM (text + visió)."""
    if not model_path:
        return False
    config_path = Path(model_path) / "config.json"
    if not config_path.exists():
        return False
    try:
        config = json.loads(config_path.read_text())
        archs = set(config.get("architectures", []))
        return bool(_VLM_ARCHITECTURES & archs)
    except Exception:
        return False


class MLXChatNode:
    """
    Motor d'inferència per a MLX adaptat per a Nexe 0.9.

    Manté:
    - Un sol model carregat (singleton)
    - MLXPromptCacheManager per prefix matching (trie-based)
    - Reutilitza KV states del prefix (system + historial)
    - Només processa tokens nous a cada torn

    Class Attributes:
        _model: Model MLX singleton
        _tokenizer: Tokenizer singleton
        _lock: Lock per thread-safety
        _config: Configuració activa
    """

    _model: Optional[Any] = None
    _tokenizer: Optional[Any] = None  # tokenizer (text) o processor (VLM)
    _lock: threading.RLock = threading.RLock()  # RLock: safe against accidental re-entrant calls
    _config: Optional[MLXConfig] = None
    _is_vlm: bool = False  # True si el model carregat és VLM

    def __init__(self, config: Optional[MLXConfig] = None):
        """
        Inicialitza el node MLX.

        Args:
            config: Configuració MLX (o carrega de .env si None)
        """
        self.config = config or MLXConfig.from_env()

        # Actualitzar config singleton si canvia
        if (MLXChatNode._config is None or
                MLXChatNode._config.model_path != self.config.model_path):
            MLXChatNode._config = self.config
            MLXChatNode._model = None  # Force reload

    def _get_model(self) -> tuple:
        """
        Obtenir model i tokenizer/processor (lazy load singleton).
        Bifurca automàticament entre mlx_lm (text) i mlx_vlm (VLM) segons config.json.

        Returns:
            tuple: (model, tokenizer_or_processor)
        """
        if MLXChatNode._model is None:
            is_vlm = _detect_vlm_capability(self.config.model_path)
            MLXChatNode._is_vlm = is_vlm

            logger.info(
                "MLXChatNode: loading %s model %s (max_kv_size=%d)",
                "VLM" if is_vlm else "text",
                self.config.model_path[-50:] if self.config.model_path else "(empty)",
                self.config.max_kv_size
            )

            if is_vlm:
                from mlx_vlm import load
                MLXChatNode._model, MLXChatNode._tokenizer = load(self.config.model_path)
            else:
                from mlx_lm import load
                MLXChatNode._model, MLXChatNode._tokenizer = load(self.config.model_path)

            logger.info("MLXChatNode: model loaded successfully (vlm=%s)", is_vlm)

        return MLXChatNode._model, MLXChatNode._tokenizer

    # NOTE: Legacy cache methods (_get_or_create_cache, _touch_lru, _destroy_cache)
    # han estat eliminats. Ara usem MLXPromptCacheManager per prefix matching real.


    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executa generació amb MLX.

        Args:
            inputs: Dict amb system, messages, messages_for_cache, session_id, stream_callback

        Returns:
            Dict amb response, tokens, metrics, etc.
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
        images = inputs.get("images")  # Optional[List[bytes]] — VLM support

        # Log per debugging
        logger.info(
            "MLXChatNode: session=%s, msgs=%d",
            session_id[:8] if session_id else "none",
            len(messages)
        )

        # Capturar event loop per streaming thread-safe
        loop = asyncio.get_running_loop()

        def threadsafe_callback(text: str) -> None:
            if stream_callback and callable(stream_callback):
                loop.call_soon_threadsafe(stream_callback, text)

        try:
            # VLM path: si hi ha imatges i el model és VLM, usa mlx_vlm directament
            if images and MLXChatNode._is_vlm:
                result = await asyncio.to_thread(
                    self._generate_vlm,
                    system, messages, images,
                    threadsafe_callback if stream_callback else None,
                    max_tokens_override, temperature_override,
                )
            else:
                # Run generation in thread (MLX is blocking)
                # With PREFIX MATCHING via MLXPromptCacheManager
                # Pass messages (for generation) and messages_for_cache (to store clean cache)
                result = await asyncio.to_thread(
                    self._generate_blocking,
                    system,
                    messages,
                    messages_for_cache,  # To store clean cache (without memory context)
                    threadsafe_callback if stream_callback else None,
                    session_id,  # To separate caches per session
                    max_tokens_override,
                    temperature_override,
                )

            elapsed_ms = int((time.time() - start_time) * 1000)

            context_used = result["prompt_tokens"] + result["tokens"]
            system_tokens = len(system) // 4  # Estimate
            prompt_tps = result.get("prompt_tps", 0)

            # Utilitzar prefix_reused del cache manager (basat en tokens reals)
            prefix_reuse = result.get("prefix_reused", False)
            cached_tokens = result.get("cached_tokens", 0)
            actual_prefill = result.get("actual_prefill_tokens", result["prompt_tokens"])

            # Calcular speedup real
            if cached_tokens > 0:
                reuse_ratio = (cached_tokens + actual_prefill) / max(actual_prefill, 1)
            else:
                reuse_ratio = 1.0

            # Calcular temps per fase (ms)
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
                "response": result["text"],
                "model_used": self.config.model_path,
                "elapsed_ms": elapsed_ms,
                "tokens": result["tokens"],
                "tokens_per_second": round(generation_tps, 1),
                "prompt_tokens": result["prompt_tokens"],
                "context_used": context_used,
                "system_tokens": system_tokens,
                "system_prompt": system,
                "cache_active": result.get("cache_active", False),  # Compatibility alias
                "prefix_reuse": prefix_reuse,  # True = prefix matching succeeded
                "reuse_ratio": round(reuse_ratio, 2),  # Cached/new tokens ratio
                "cached_tokens": cached_tokens,  # Tokens reused from cache
                "actual_prefill_tokens": actual_prefill,  # Tokens actually processed
                "identity_hash": result.get("identity_hash", ""),  # System prompt hash
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

    def _generate_vlm(
        self,
        system: str,
        messages: List[Dict],
        images: List[bytes],
        stream_callback: Optional[Callable[[str], None]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generació VLM amb mlx_vlm (text + imatge). Usa mlx_vlm.generate()."""
        import io
        from mlx_vlm import generate as vlm_generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from PIL import Image

        model, processor = self._get_model()

        # Prepara el prompt via chat template del processor
        formatted_prompt = apply_chat_template(
            processor=processor,
            config=processor.config if hasattr(processor, "config") else {},
            prompt=messages[-1]["content"] if messages else "",
            num_images=1,
        )

        # Prepara la imatge (primera del array)
        pil_image = Image.open(io.BytesIO(images[0]))

        start_time = time.time()
        text = vlm_generate(
            model=model,
            processor=processor,
            image=pil_image,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.config.max_tokens,
            verbose=False,
        )

        if stream_callback:
            stream_callback(text)

        elapsed_ms = int((time.time() - start_time) * 1000)
        tokens = len(text.split())  # Estimació

        return {
            "text": text,           # Format consistent amb extract_metrics()
            "tokens": tokens,
            "tokens_per_second": round(tokens / max(elapsed_ms / 1000, 0.001), 1),
            "prompt_tokens": 0,
            "prefix_reused": False,
            "cached_tokens": 0,
            "actual_prefill_tokens": 0,
            "prompt_tps": 0,
            "peak_memory_mb": 0,
            "identity_hash": "",
            "vlm": True,            # Flag extra per indicar mode VLM
        }

    def _generate_blocking(
        self,
        system: str,
        messages: List[Dict],
        messages_for_cache: List[Dict],
        stream_callback: Optional[Callable[[str], None]],
        session_id: str = "default",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Generació blocking amb MLX i PREFIX MATCHING (executat en thread).

        Helpers a generate_helpers.py.
        """
        with MLXChatNode._lock:
            return self._generate_blocking_inner(
                system, messages, messages_for_cache,
                stream_callback, session_id, max_tokens, temperature,
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
    ) -> Dict[str, Any]:
        """Inner generation logic, called under lock."""
        from mlx_lm.sample_utils import make_sampler
        from .prompt_cache_manager import get_prompt_cache_manager

        model, tokenizer = self._get_model()
        cache_manager = get_prompt_cache_manager(max_size=8)

        # Model key per cache (path + identity_hash + session_id)
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

        logger.info(
            "MLXChatNode: identity=%s, full=%d, cached=%d, new=%d, prefix_reuse=%s",
            identity_hash[:8], total_tokens, cached_token_count,
            total_tokens - cached_token_count, "YES" if prefix_reused else "NO"
        )

        # 3. Determinar tokens a processar
        tokens_to_process, new_tokens = determine_tokens_to_process(
            full_tokens, cached_token_count, prefix_reused
        )

        # 4. Crear sampler
        sampler = make_sampler(temp=temperature if temperature is not None else self.config.temperature, top_p=self.config.top_p)

        # 5. Run generation with streaming
        text, last_response, _ = run_streaming_generation(
            model, tokenizer, tokens_to_process, max_tokens if max_tokens is not None else self.config.max_tokens,
            sampler, cached_kv, stream_callback,
            cache_manager, model_key, cache_lookup_tokens,
            model_path=self.config.model_path
        )

        # 6. Save cache post-generation (clean messages, without memory context)
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
        """Destruir model, tokenizer i tots els caches."""
        with cls._lock:
            # Netejar cache manager (prefix matching)
            try:
                from .prompt_cache_manager import get_prompt_cache_manager
                cache_manager = get_prompt_cache_manager()
                cache_manager.clear()
            except Exception as e:
                logger.warning("MLXChatNode: error clearing cache manager: %s", e)

            # Destruir model
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
                mx.clear_cache()  # Substitueix mx.metal.clear_cache (deprecated)
            except Exception as e:
                logger.warning("MLXChatNode: error clearing cache: %s", e)

            gc.collect()
            logger.info("MLXChatNode: model and all caches reset")

    @classmethod
    def get_pool_stats(cls) -> Dict[str, Any]:
        """Return cache statistics."""
        # Obtenir stats del cache manager
        cache_manager_stats = {}
        try:
            from .prompt_cache_manager import get_prompt_cache_manager
            cache_manager = get_prompt_cache_manager()
            cache_manager_stats = cache_manager.get_stats()
        except Exception as e:
            logger.debug("MLX stats collection failed: %s", e)  # nosec B110 - Stats opcionals

        return {
            "model_loaded": cls._model is not None,
            "model_path": cls._config.model_path if cls._config else None,
            "max_kv_size": cls._config.max_kv_size if cls._config else 0,
            "cache_manager": cache_manager_stats,
        }
