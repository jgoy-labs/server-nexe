"""El camí VLM (visió) de l'MLX, extret de `chat.py` a #966 — Tros A.

Els 9 mètodes i els 3 helpers d'aquest fitxer venen de `MLXChatNode` amb el **cos
verbatim**: no s'ha reescrit ni una línia. `MLXChatNode` els conserva com a delegadors
amb el MATEIX nom, de manera que les ~81 crides que la suite ja hi feia segueixen
funcionant i fan de golden master del moviment.

`MLXVisionRunner` llegeix `config` **en viu** del node (propietat, no còpia): `apply_config`
reemplaça l'objecte de configuració en canviar de model, i una còpia hauria quedat rància
— la mateixa família de bug que els comentaris sobre `_is_vlm` ja adverteixen.
"""
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .generate_helpers import (
    sanitize_messages_for_alternation,
    truncate_messages_to_budget,
)
from .model_json import _load_json_safe
from .qwen35_directive import (
    QWEN35_THINKING_DIRECTIVE,
    _inject_thinking_directive_into_messages,
    _qwen35_needs_thinking_directive,
)
from core.utils import compute_system_hash

logger = logging.getLogger(__name__)


def _prompt_has_open_think_prefix(formatted_prompt: str) -> bool:
    """Detect chat templates that inject ``<think>`` *into the prompt*.

    Empirical incident 2026-05-13: Qwen3 / Qwen3.5 / Gemma-4 chat templates
    pre-open the reasoning block when ``enable_thinking`` is true (default
    or explicit). Their tail looks like::

        <|im_start|>assistant\\n<think>\\n

    The model then generates ``[reasoning]</think>\\n[answer]`` — note the
    *missing* opening ``<think>`` in the model's own output. Downstream
    parsers (``_process_content_think_tags`` in routes_chat.py) only switch
    into "thinking" mode when they see ``<think>`` *in the stream*, so they
    miss the prefix and dump the entire reasoning verbatim into the visible
    body of the response, while the trailing ``</think>`` and final answer
    look like noise.

    This helper is the engine-side detector: if the prompt already contains
    the opener, the engine MUST emit a synthetic ``<think>\\n`` as the very
    first chunk of the stream so downstream parsers see the canonical
    ``<think>...</think>`` pattern and split correctly.

    The check is structural (looks at the prompt tail), not family-based
    (no Qwen/Gemma allowlist). gpt-oss uses a different convention with
    ``<|channel|>analysis<|message|>`` tags emitted *by the model*, so its
    prompt does NOT end in ``<think>`` and this helper returns False — its
    existing pipeline keeps working unchanged.

    Models that don't open the reasoning block in the prompt (e.g.
    thinking_enabled=False which produces the ``<think>\\n\\n</think>\\n\\n``
    tail, or models with no reasoning at all) also return False.
    """
    if not formatted_prompt:
        return False
    tail = formatted_prompt.rstrip()
    return tail.endswith("<think>")


def _chunked_prefill_is_broken(model_path: str) -> bool:
    """True for architectures where mlx_vlm's chunked prefill crashes.

    Reproduced on mlx_vlm 0.4.4 with Qwen3-VL (``Qwen3VLForConditionalGeneration``)
    and a text-only prompt: as soon as the prompt exceeds the chunk size,
    ``models/qwen3_vl/language.py`` does ``visual_pos_masks[:, n_to_process:]``
    with ``visual_pos_masks`` still None and raises TypeError. Verified at
    645/4.2k/8.8k tokens against step sizes 2048/512/128 — every chunked
    combination fails, only disabling chunking survives.

    No catalog model uses this architecture, so this is not a shipped bug; the
    check exists so that lowering the chunk size does not make a user-supplied
    Qwen3-VL model fail *earlier* (at 512 tokens instead of 2048) than it does
    today. Their behaviour is left exactly as it was.
    """
    if not model_path:
        return False
    config = _load_json_safe(Path(model_path) / "config.json")
    if not config:
        return False
    architectures = config.get("architectures") or []
    if isinstance(architectures, str):
        architectures = [architectures]
    blob = " ".join(str(a) for a in architectures) + " " + str(config.get("model_type", ""))
    return "qwen3vl" in blob.lower().replace("_", "").replace("-", "")


def _prefill_step_kwargs(model_path: str = "") -> Dict[str, int]:
    """Chunk size for the VLM prefill, as kwargs to splat into mlx_vlm calls.

    mlx_vlm's default is 2048 (``generate.py:DEFAULT_PREFILL_STEP_SIZE``), which
    on a low-RAM machine costs more peak memory than it needs to. Measured on
    Qwen3.5-4B-MLX-4bit (M4 Max, peak via ``mx.get_peak_memory()``):

        prompt ~8.0k tokens: 2048 -> 5.15 GB / 5.22 s
                              512 -> 4.06 GB / 5.27 s   <- default here
                              128 -> 3.66 GB / 6.07 s
                             None -> 12.43 GB / 6.51 s  (chunking disabled)

    512 takes the memory win at no measurable latency cost; 128 buys another
    0.4 GB for ~16% more time, so it is opt-in rather than the default. Note
    that ``None`` disables chunking entirely and is catastrophic on long
    prompts — ``NEXE_MLX_PREFILL_STEP=default`` therefore means "leave the
    library default alone", not "disable".
    """
    import os as _os_pf  # noqa: PLC0415
    raw = _os_pf.environ.get("NEXE_MLX_PREFILL_STEP", "").strip().lower()
    if raw == "default":
        return {}
    if _chunked_prefill_is_broken(model_path):
        # Leave this model exactly as it was: a smaller chunk would only move
        # the upstream crash to a shorter prompt. See _chunked_prefill_is_broken.
        logger.warning(
            "MLX: chunked prefill is broken upstream for this architecture (%s) — "
            "leaving mlx_vlm's default untouched", model_path,
        )
        return {}
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return {"prefill_step_size": value}
        except ValueError:
            pass
        logger.warning(
            "NEXE_MLX_PREFILL_STEP=%r is not a positive integer or 'default' — using 512", raw
        )
    return {"prefill_step_size": 512}

class MLXVisionRunner:
    """El camí VLM de `MLXChatNode`. Els cossos són els originals, sense tocar."""

    def __init__(self, node):
        self._node = node

    @property
    def config(self):
        """En viu des del node: `apply_config` reemplaça l'objecte de config."""
        return self._node.config

    def _get_model(self) -> tuple:
        """Delegació al node: es resol a la crida, perquè els tests patxegen
        `MLXChatNode._get_model` DESPRÉS de construir el node."""
        return self._node._get_model()

    def _normalize_image_input(self, raw) -> bytes:
        if isinstance(raw, str):
            import base64
            if raw.startswith("data:"):
                try:
                    raw = raw.split(",", 1)[1]
                except IndexError:
                    pass
            try:
                raw = base64.b64decode(raw, validate=False)
            except Exception as exc:
                raise ValueError(
                    f"VLM image[0] is str but not valid base64: {exc}"
                ) from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError(
                f"VLM image[0] must be bytes or base64 str, got {type(raw).__name__}"
            )
        return bytes(raw)

    def _prepare_vlm_prompt(
        self,
        messages: List[Dict],
        system: str,
        processor,
        has_image: bool,
        thinking_enabled: bool = True,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Build the VLM prompt with thinking control.

        Empirically detected 2026-05-13 (Qwen3.5-27B-4bit on MLX): the VLM
        branch was ignoring the user's Raonament toggle entirely. Root cause:
        ``execute()`` did not forward ``thinking_enabled`` to ``_generate_vlm``,
        and ``_prepare_vlm_prompt`` did not pass ``enable_thinking`` down to
        ``mlx_vlm.prompt_utils.apply_chat_template``. The Qwen3/Qwen3.5
        ``chat_template.jinja`` reads the ``enable_thinking`` Jinja variable to
        decide whether to inject ``<think>\\n\\n</think>\\n\\n`` (suppressed)
        or ``<think>\\n`` (force-thinking). With the kwarg missing the template
        defaulted to the second branch and the model thought every time.

        Fix: forward ``enable_thinking=False`` through ``apply_chat_template``
        (mlx_vlm forwards kwargs to ``processor.apply_chat_template`` which in
        turn passes them to the Jinja template). When ``thinking_enabled`` is
        True we pass nothing — preserving the model's native default
        behaviour (which for Qwen3.5 happens to be "always think").

        Tokenizer/processor combinations that don't recognise ``enable_thinking``
        will raise ``TypeError``; we fall back to the no-kwarg call so older or
        non-Qwen processors keep working.
        """
        import os
        from mlx_vlm.prompt_utils import apply_chat_template

        try:
            with open(
                os.path.join(self.config.model_path, "config.json")
            ) as _cf:
                mdl_config = json.load(_cf)
        except Exception:
            mdl_config = {"model_type": ""}

        # #860: sanitize before templating, like the text path does at
        # generate_helpers.py:226. Without this the two branches built
        # different prompts from the same history — the text one merging
        # consecutive same-role turns, this one emitting them back to back,
        # which is malformed for every VL model in the catalog. /ui/chat
        # cannot produce that history (SessionManager collapses adjacent
        # roles first), but /v1/chat/completions does not sanitize at all and
        # the OpenAI wire format lets a client send it.
        # System is prepended AFTER: sanitize drops system messages by design.
        sanitized = sanitize_messages_for_alternation(messages)

        # #845: the same prompt-level ceiling the text path got in 47efa879.
        # It has to be here and not at the caller because the order is load
        # bearing (generate_helpers.py:231): alternation must hold for the
        # messages actually KEPT, so sanitize first, measure second.
        #
        # A VLM processor is NOT a tokenizer — Qwen3VLProcessor has no
        # .encode(), it exposes .tokenizer. Passing the processor straight in
        # would raise AttributeError on every VLM turn, which with the default
        # model means every turn.
        #
        # With an image attached the estimate undercounts: image tokens never
        # pass through the text tokenizer. That is accepted — this is a net
        # against unbounded growth, not an exact accountant (same caveat the
        # cache accounting already carries below).
        if self.config.max_kv_size is not None:
            budget_tokenizer = getattr(processor, "tokenizer", None)
            if budget_tokenizer is None and hasattr(processor, "encode"):
                budget_tokenizer = processor
            if budget_tokenizer is None:
                logger.warning(
                    "VLM context budget skipped: processor %s exposes neither "
                    "a tokenizer nor encode(), so the prompt cannot be measured "
                    "(#845). The conversation grows unbounded.",
                    type(processor).__name__,
                )
            else:
                sanitized = truncate_messages_to_budget(
                    system,
                    sanitized,
                    budget_tokenizer,
                    self.config.max_kv_size,
                    max_tokens if max_tokens is not None else self.config.max_tokens,
                )

        all_messages: List[Dict[str, Any]] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        if sanitized:
            all_messages.extend(sanitized)

        # Qwen3.5-only: when Raonament=ON, reinforce thinking in the system
        # prompt because the chat template alone is not enough (model mimics
        # historial turns and skips reasoning in multi-turn conversations).
        # See _qwen35_needs_thinking_directive docstring for the rationale.
        if _qwen35_needs_thinking_directive(
            str(mdl_config.get("model_type", "")), thinking_enabled
        ):
            all_messages = _inject_thinking_directive_into_messages(
                all_messages, QWEN35_THINKING_DIRECTIVE
            )

        prompt_arg = all_messages if all_messages else ""
        num_images = 1 if has_image else 0

        if not thinking_enabled:
            try:
                return apply_chat_template(
                    processor=processor,
                    config=mdl_config,
                    prompt=prompt_arg,
                    num_images=num_images,
                    enable_thinking=False,
                )
            except TypeError:
                pass  # processor template does not support enable_thinking — fall through

        return apply_chat_template(
            processor=processor,
            config=mdl_config,
            prompt=prompt_arg,
            num_images=num_images,
        )

    @staticmethod
    def _reset_rotated_vlm_state(prompt_cache_state) -> bool:
        """Review #826 (major): mai reutilitzar un RotatingKVCache ja rotat.

        Amb max_kv_size, mlx_vlm crea RotatingKVCache al 1r torn; el camí de
        reuse (generate.py) trima amb semàntica de KVCache PLA
        (`keys[:, :, :prefix_len]` + offset) — un cop el buffer ha rotat,
        aquest trim conserva brossa entrellaçada com a "prefix" de la
        conversa. Si detectem rotació, resetegem l'estat: es perd el reuse
        d'AQUEST torn (re-prefill) però mai es corromp el context. Retorna
        True si s'ha resetejat.
        """
        cache = getattr(prompt_cache_state, "cache", None)
        if not cache:
            return False
        try:
            rotated = any(
                type(c).__name__ == "RotatingKVCache"
                and getattr(c, "offset", 0) >= (getattr(c, "max_size", None) or float("inf"))
                for c in cache
            )
        except TypeError:  # fakes no iterables als tests
            return False
        if rotated:
            prompt_cache_state.cache = None
            prompt_cache_state.token_ids = None
            logger.info(
                "MLX VLM cache: RotatingKVCache rotated — state reset "
                "(fresh bounded cache this turn; prefix reuse skipped, #826)"
            )
        return rotated

    @staticmethod
    def _reset_untrimmable_vlm_state(prompt_cache_state, new_token_ids) -> bool:
        """#849 (P1): mai reutilitzar un cache que mlx_vlm no pot retallar.

        Germà del guard del #826, però mirant el que realment decideix la
        corrupció: **si les capes es poden retallar**, no si han rotat.

        A ``mlx_vlm/generate.py`` (0.4.4) el camí de reuse retalla els
        ``input_ids`` al prefix comú de forma INCONDICIONAL, mentre que el
        retall del KV va dins ``if hasattr(c, "keys") and c.keys is not None``.
        Per a un model híbrid això no és tot-o-res: mesurat amb
        ``Qwen3.5-4B-4bit`` i el cache POBLAT, ``make_cache()`` dóna **8
        KVCache + 24 ArraysCache** (``layer_types`` = 8 full_attention + 24
        linear_attention) → **8 capes es retallen al prefix i 24 es queden amb
        el torn anterior sencer**. No és "context sobrer": és desalineament
        ENTRE capes, i el model genera amb dues històries alhora.

        Tampoc es pot arreglar retallant per l'altra banda: ``ArraysCache`` és
        estat recurrent (linear attention), ``is_trimmable()`` és False i
        ``mlx_lm.trim_prompt_cache`` el refusa. Un estat comprimit no es pot
        tallar en un token arbitrari — no és un bug d'implementació.
        Upstream ho tracta a mlx-vlm 0.6.x amb un mode ``exact`` (snapshot de
        prefix sencer per a layouts mixtos); nosaltres estem pinnats a 0.4.4
        (mlx-lm/transformers) i el forat és conegut i OBERT a mlx-lm #980.

        Mesurada també l'alternativa barata al reset (reusar només quan el
        prefix cobreix TOT el cache, sense retall): en un xat de 3 torns els
        tokens sobrants són **122 a cada torn** i són el bloc ``<think>`` —
        la cadena de raonament es desa al cache i el prompt següent no la
        re-serialitza. O sigui que el cas "no cal retallar" **no arriba mai**
        amb thinking actiu, i el reuse condicional equivaldria a aquest reset
        amb més codi. La condició hi és igualment perquè quan SÍ es dóna
        (prefix exacte) el reuse és correcte i val la pena conservar-lo.

        Cost assumit: per als models híbrids es torna al ``cached=0`` i el
        prefill puja. Es perd velocitat produint text bo, en comptes de
        guanyar-ne produint-ne de dolent.

        Returns:
            True si s'ha resetejat l'estat (aquest torn re-prefilla sencer).
        """
        cache = getattr(prompt_cache_state, "cache", None)
        token_ids = getattr(prompt_cache_state, "token_ids", None)
        if not cache or not token_ids:
            return False
        try:
            all_trimmable = all(
                hasattr(c, "keys") and getattr(c, "keys", None) is not None for c in cache
            )
        except TypeError:  # fakes no iterables als tests
            return False
        # Totes retallables (KV pur) → el trim de mlx_vlm és correcte i el
        # prefill 4× es conserva. Aquest guard no hi té res a dir.
        if all_trimmable:
            return False
        # Hi ha capes no retallables. L'ÚNIC cas en què el reuse segueix sent
        # segur és que el cache sigui prefix EXACTE del prompt nou (cap retall
        # pendent). Si no podem comprovar-ho — sense ids, o el tokenitzador
        # peta — el guard falla TANCAT: una mètrica pot fallar oberta, una
        # guarda de correcció no. (Ho va caçar el test de wiring: amb un
        # processor sense `.encode` la versió anterior deixava passar el cache
        # desalineat justament pel camí que havia de protegir.)
        if new_token_ids is None:
            prefix_len = -1
        else:
            try:
                prefix_len = prompt_cache_state.find_prefix_length(new_token_ids)
            except Exception:  # nosec B110: fakes als tests / tokenitzador rar
                prefix_len = -1
        if prefix_len >= len(token_ids):
            return False
        prompt_cache_state.cache = None
        prompt_cache_state.token_ids = None
        logger.info(
            "MLX VLM cache: untrimmable layers (hybrid model), prefix %s < cached %d "
            "— state reset; this turn re-prefills instead of reusing a misaligned "
            "context (#849)",
            prefix_len if prefix_len >= 0 else "unknown",
            len(token_ids),
        )
        return True

    def _log_vlm_kv_request(self, model, prompt_cache_state=None) -> None:
        """#826/#845 instrumentation, VLM twin of "MLX cache created:" (text path).

        Records whether the requested max_kv_size can actually be enforced:
        mlx_vlm delegates to language_model.make_cache() when the model
        defines it (Qwen3.5/gemma…), IGNORING the limit — FD-S7 needs this
        verdict in the field logs to (re)attribute degeneration.
        """
        lang_model = getattr(model, "language_model", None)
        owned = hasattr(lang_model, "make_cache")
        # Review #826: INFO només quan mlx_vlm CREARÀ el cache (com el twin
        # "MLX cache created:" del camí text); en reuse (torns 2+) el veredicte
        # és el mateix fet per-sessió → DEBUG per no inundar el log.
        creating = prompt_cache_state is None or getattr(prompt_cache_state, "cache", None) is None
        logger.log(
            logging.INFO if creating else logging.DEBUG,
            "MLX VLM cache request: max_kv_size=%d %s",
            self.config.max_kv_size,
            "(model-owned make_cache — NOT enforced inside mlx_vlm, #845)"
            if owned else "(enforced via mlx_vlm prompt cache)",
        )

    def _run_vlm_streaming(
        self,
        model,
        processor,
        formatted_prompt: str,
        tmp_path: Optional[str],
        max_tokens: Optional[int],
        stream_callback: Callable[[str], None],
        cancel_event: Any = None,
        prompt_cache_state: Any = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ):
        from mlx_vlm import stream_generate as vlm_stream

        # See _prompt_has_open_think_prefix docstring: when the chat template
        # injects <think> into the prompt (Qwen3, Qwen3.5, Gemma-4 with
        # thinking on), the model's stream omits the opening tag, breaking
        # downstream split. Re-emit the missing opener as the first chunk so
        # the canonical <think>...</think> pattern reaches the client.
        prepend_think = _prompt_has_open_think_prefix(formatted_prompt)

        full_text = ""
        last = None
        emitted_prefix = False
        # prompt_cache_state (mlx_vlm >= 0.4): reuse the KV cache from previous
        # turns — mlx_vlm finds the common prefix and prefills only new tokens,
        # then updates the state. Passed only when present so an older mlx_vlm
        # that doesn't accept this kwarg keeps working unchanged (no reuse).
        cache_kwargs = {}
        if prompt_cache_state is not None:
            # Review #826: un RotatingKVCache rotat no es pot reutilitzar (el
            # trim de mlx_vlm assumeix KVCache pla) — reset abans de passar-lo.
            self._reset_rotated_vlm_state(prompt_cache_state)
            cache_kwargs["prompt_cache_state"] = prompt_cache_state
        # #826: cap the KV on the VLM path too (the text path already does via
        # make_prompt_cache). mlx_vlm honours max_kv_size when it CREATES the
        # prompt_cache; with a reused prompt_cache_state (turns 2+) the
        # existing cache is passed through unchanged. Models whose
        # language_model defines make_cache() (Qwen3.5 & co.) ignore the limit
        # inside mlx_vlm (#845, FD-S7) — the log below records the verdict.
        cache_kwargs["max_kv_size"] = self.config.max_kv_size
        self._log_vlm_kv_request(model, prompt_cache_state)
        # Sampling params: mlx_vlm >= 0.4 accepts temperature/top_p via **kwargs.
        # Passed only when set so unset values (and older mlx_vlm) keep prior
        # behavior. This also fixes temperature being dropped on the VLM path.
        sampling_kwargs = {}
        if temperature is not None:
            sampling_kwargs["temperature"] = temperature
        if top_p is not None:
            sampling_kwargs["top_p"] = top_p
        for chunk in vlm_stream(
            model=model,
            processor=processor,
            image=tmp_path,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.config.max_tokens,
            **cache_kwargs,
            **sampling_kwargs,
            **_prefill_step_kwargs(self.config.model_path),
        ):
            # Honour client-side cancel: when the HTTP client disconnects,
            # the route handler sets cancel_event so we exit early instead of
            # running to max_tokens (~100s of useless generation that blocks
            # the single-worker MLX executor for subsequent requests).
            if cancel_event is not None and cancel_event.is_set():
                logger.info("MLXChatNode: cancel_event set — breaking VLM stream loop")
                break
            delta = getattr(chunk, "text", "") or ""
            if delta:
                if prepend_think and not emitted_prefix:
                    stream_callback("<think>\n")
                    full_text += "<think>\n"
                    emitted_prefix = True
                stream_callback(delta)
                full_text += delta
            last = chunk
        return full_text, last

    def _run_vlm_oneshot(
        self,
        model,
        processor,
        formatted_prompt: str,
        tmp_path: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
    ):
        from mlx_vlm import generate as vlm_generate

        # Sampling params passed only when set (see _run_vlm_streaming).
        sampling_kwargs = {}
        if temperature is not None:
            sampling_kwargs["temperature"] = temperature
        if top_p is not None:
            sampling_kwargs["top_p"] = top_p
        self._log_vlm_kv_request(model)
        one = vlm_generate(
            model=model,
            processor=processor,
            image=tmp_path,
            prompt=formatted_prompt,
            max_tokens=max_tokens or self.config.max_tokens,
            verbose=False,
            max_kv_size=self.config.max_kv_size,  # #826 — see _run_vlm_streaming
            **sampling_kwargs,
            **_prefill_step_kwargs(self.config.model_path),
        )
        text = one.text if hasattr(one, "text") else str(one)
        if _prompt_has_open_think_prefix(formatted_prompt):
            # Same fix as the streaming path: re-emit the synthetic <think>\n
            # opener so downstream parsers recognise the reasoning block.
            text = "<think>\n" + text
        return text, one

    def _extract_vlm_metrics(
        self,
        result_obj,
        result_text: str,
        elapsed_ms: int,
        prefix_reused: bool = False,
        cached_tokens: int = 0,
        identity_hash: str = "",
        max_tokens_used: "Optional[int]" = None,
    ) -> Dict[str, Any]:
        prompt_tokens = getattr(result_obj, "prompt_tokens", 0)
        gen_tokens = getattr(result_obj, "generation_tokens", len(result_text.split()))
        prompt_tps = getattr(result_obj, "prompt_tps", 0) or 0
        gen_tps = getattr(result_obj, "generation_tps", 0) or 0
        peak_memory = getattr(result_obj, "peak_memory", 0) or 0

        return {
            "text": result_text,
            "tokens": gen_tokens,
            "tokens_per_second": round(gen_tps, 1) if gen_tps else round(
                gen_tokens / max(elapsed_ms / 1000, 0.001), 1
            ),
            "prompt_tokens": prompt_tokens,
            "prefix_reused": prefix_reused,
            "cached_tokens": cached_tokens,
            "actual_prefill_tokens": max(prompt_tokens - cached_tokens, 0),
            "prompt_tps": round(prompt_tps, 1),
            "peak_memory_mb": round(peak_memory, 1),
            "identity_hash": identity_hash,
            "vlm": True,
            # FD-S5: mlx_vlm's GenerationResult has NO finish_reason —
            # heuristic: hitting the ceiling exactly. False positive when EOS
            # lands on the limit; acceptable because the VLM marker is
            # informative-only (never continuable).
            "finish_reason": (
                "length"
                if (max_tokens_used and gen_tokens >= max_tokens_used)
                else None
            ),
        }

    def _generate_vlm(
        self,
        system: str,
        messages: List[Dict],
        images: List[bytes],
        stream_callback: Optional[Callable[[str], None]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        thinking_enabled: bool = True,
        cancel_event: Any = None,
        session_id: str = "default",
        top_p: Optional[float] = None,
    ) -> Dict[str, Any]:
        """VLM generation with mlx_vlm (text + image). Uses mlx_vlm.generate().

        API mlx-vlm >= 0.4: `image` is a path (str) or list of paths, and `generate()`
        returns a `GenerationResult` with .text + real metrics (not a bare string).

        thinking_enabled forwarded to _prepare_vlm_prompt so the chat template
        sees the Raonament toggle (fix 2026-05-13 — see _prepare_vlm_prompt
        docstring for the upstream root cause).
        """
        import os
        import tempfile

        model, processor = self._get_model()
        has_image = bool(images)
        formatted_prompt = self._prepare_vlm_prompt(
            messages, system, processor, has_image, thinking_enabled=thinking_enabled,
            max_tokens=max_tokens,
        )

        # Prefix-cache for the VLM path (mlx_vlm native PromptCacheState), keyed
        # per session like the text path (_generate_blocking). Without this the
        # VLM path re-prefilled the whole context every turn (the historical
        # cached=0): MLXPromptCacheManager was only wired into the text path, so
        # any VLM model (e.g. the Qwen3.5 family — VL at every tier) never
        # reused its KV cache. get_or_create returns None on older mlx_vlm with
        # no PromptCacheState → no reuse, identical to the previous behaviour.
        from .vlm_cache_manager import get_vlm_cache_manager
        identity_hash = compute_system_hash(system)
        session_key = session_id[:8] if session_id else "default"
        model_key = f"{self.config.model_path}:{identity_hash}:{session_key}"
        cache_state = get_vlm_cache_manager(
            self.config.max_vlm_session_caches
        ).get_or_create(model_key)
        had_cache = cache_state is not None and getattr(cache_state, "cache", None) is not None
        # Best-effort reuse count for the log/metrics (text-only prompts tokenize
        # cleanly; with images the count is approximate). The real saving is
        # always visible in the prefill time regardless of this number.
        cached_tokens = 0
        if had_cache:
            try:
                _tok = getattr(processor, "tokenizer", processor)
                _new_ids = _tok.encode(formatted_prompt)
            except Exception:  # nosec B110: metric estimate only — never blocks generation
                _new_ids = None
            # #849: el guard va ABANS de comptar i es crida SEMPRE (també amb
            # _new_ids None: allà decideix pel tipus de capa i falla tancat).
            # Quan dispara, les mètriques han de dir la veritat
            # (prefix_reused=False, cached=0) — si no, el log torna a prometre
            # un reuse que no hi ha hagut, que és el que va fer illegible el #843.
            if self._reset_untrimmable_vlm_state(cache_state, _new_ids):
                had_cache = False
            elif _new_ids is not None:
                try:
                    cached_tokens = cache_state.find_prefix_length(_new_ids)
                except Exception:  # nosec B110: metric estimate only
                    cached_tokens = 0

        tmp_path = None
        try:
            if has_image:
                raw = self._normalize_image_input(images[0])
                tmp = tempfile.NamedTemporaryFile(
                    prefix="nexe_vlm_", suffix=".img", delete=False
                )
                tmp.write(raw)
                tmp.flush()
                tmp.close()
                tmp_path = tmp.name

            start_time = time.time()
            if stream_callback:
                result_text, result_obj = self._run_vlm_streaming(
                    model, processor, formatted_prompt, tmp_path,
                    max_tokens, stream_callback, cancel_event,
                    prompt_cache_state=cache_state,
                    temperature=temperature, top_p=top_p,
                )
            else:
                result_text, result_obj = self._run_vlm_oneshot(
                    model, processor, formatted_prompt, tmp_path, max_tokens,
                    temperature=temperature, top_p=top_p,
                )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        elapsed_ms = int((time.time() - start_time) * 1000)
        return self._extract_vlm_metrics(
            result_obj, result_text, elapsed_ms,
            prefix_reused=had_cache, cached_tokens=cached_tokens,
            identity_hash=identity_hash,
            max_tokens_used=max_tokens or self.config.max_tokens,
        )
