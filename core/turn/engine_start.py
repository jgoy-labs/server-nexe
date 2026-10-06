"""
------------------------------------
Server Nexe
Location: core/turn/engine_start.py
Description: The one function that starts an engine's generation and returns
             its `chat_result`, whatever the engine's shape (Ollama-style, the
             in-process MLX / llama.cpp queue, generic). C4.8-a: moved here
             verbatim from plugins/web_ui_module/api/engine_call.py, with no
             change of behaviour; the cascade (C4.8-b/c) will call it from the
             core. The wire format (SSE, sentinels) stays at each door.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


def start_engine_call(
    engine, engine_name: str, sig, model_name, system_prompt: str, messages: list, *,
    stream: bool, image_b64, thinking_enabled: bool, cancel_event, sampling_kwargs: dict,
    session_id: str, _continue: bool,
):
    """Start the engine's generation and return its `chat_result` (a dict, a
    coroutine or an async generator, depending on the engine's shape).

    Three shapes: Ollama-style `chat(model, messages, stream=…)`, the in-process
    engines (MLX, llama.cpp) driven through a queue + background task, and the
    generic `chat(messages, system=…)`. Extracted verbatim out of the old engine
    handler on 2026-09-06 (ADR-007 C1.3); moved verbatim from the web door's
    `engine_call.py` into the core on 2026-10-06 (C4.8-a), where the turn
    adapters call it. `_continue` is the turn's `resume` (FD-S6). The `engine` step
    already drops a module that does not declare `can_continue`; both in-process
    engines that reach this branch (MLX and llama.cpp) honour `continue_final`.
    """
    # Ollama/MLX/LlamaCpp expect base64 strings, not bytes
    _images_arg = [image_b64] if image_b64 else None

    # cancel_event covers the in-process engines (MLX and
    # llama.cpp): both run a synchronous generation loop in a
    # worker thread that won't notice an HTTP disconnect on its
    # own, so the handler sets the event and the loop breaks
    # early instead of running to max_tokens (orphan worker
    # blocking the model — MC-011). Ollama cancels naturally via
    # its httpx async transport when the asyncio task is
    # cancelled, so it doesn't need the event.
    cancel_kwargs = (
        {"cancel_event": cancel_event}
        if engine_name in ("mlx", "llama_cpp")
        else {}
    )

    if 'model' in sig.parameters:
        # Ollama-style: chat(model, messages, stream=...)
        # We inject system prompt as first message for Ollama.
        # C4.6-a2: resume only when the engine declares `continue_final`.
        # One that does not would ignore the flag and start a new answer.
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        continue_kwargs = (
            {"continue_final": True}
            if _continue and "continue_final" in sig.parameters
            else {}
        )
        chat_result = engine.chat(model=model_name, messages=full_messages, stream=stream,
                                  images=_images_arg,
                                  thinking_enabled=thinking_enabled,
                                  **continue_kwargs, **cancel_kwargs, **sampling_kwargs)
    else:
        # MLX/LlamaCpp-style: chat(messages, system=...)
        if engine_name in ("mlx", "llama_cpp"):
            # MLX module requires a callback for streaming
            queue: asyncio.Queue = asyncio.Queue()

            _stream_chunk_count = [0]

            # B023: `stream_cb` and `queue_generator` below outlive the
            # iteration that built them — the engine task keeps
            # running while the cascade may already be on the next
            # engine, and a free name would then read THAT engine's
            # queue. The defaults pin each closure to the objects of
            # its own turn; the bodies are untouched on purpose (hot
            # streaming path).
            def stream_cb(token, *, _stream_chunk_count=_stream_chunk_count, queue=queue):
                # MLXChatNode already marshals this to the main loop, so we can just put in queue
                _stream_chunk_count[0] += 1
                if _stream_chunk_count[0] <= 3 or _stream_chunk_count[0] % 50 == 0:
                    logger.debug("stream_cb: chunk #%d (%d chars)", _stream_chunk_count[0], len(token))
                queue.put_nowait(token)

            # #1107: llama.cpp honours continue_final the same way MLX does.
            # An engine that arrived here without that support would ignore
            # the flag and start a new answer, so the raise stays for anyone
            # else that joins this branch.
            _continue_kwargs = {}
            if _continue:
                if engine_name not in ("mlx", "llama_cpp"):
                    raise ValueError(
                        "continue is only supported on the MLX and llama.cpp engines"
                    )
                _continue_kwargs = {"continue_final": True}
            # Launch chat in background task
            # B007 (1b): session_id scopes the prefix-cache key —
            # without it every conversation shares ":default".
            ml_task = asyncio.create_task(engine.chat(
                messages=messages, system=system_prompt, stream_callback=stream_cb,
                session_id=session_id,
                images=_images_arg, thinking_enabled=thinking_enabled,
                **_continue_kwargs, **cancel_kwargs, **sampling_kwargs,
            ))

            # Async generator that yields from queue until task is done
            async def queue_generator(*, queue=queue, ml_task=ml_task):
                while True:
                    # Check if queue has items first
                    if not queue.empty():
                        yield await queue.get()
                        continue

                    # If queue is empty, check if task is done
                    if ml_task.done():
                        # If task failed, re-raise exception
                        _exc = ml_task.exception()
                        if _exc is not None:
                            raise _exc
                        # FD-S5: the engine's result dict was
                        # discarded here — finish_reason died
                        # with it. Surface the truncation as
                        # an in-band sentinel. Defensive
                        # isinstance: llama_cpp shares this
                        # branch with its own result shape.
                        _res = ml_task.result()
                        if (
                            isinstance(_res, dict)
                            and _res.get("finish_reason") == "length"
                        ):
                            yield {
                                "__nexe_trunc__": True,
                                "continuable": bool(_res.get("continuable")),
                            }
                        break

                    # Wait for new tokens with short timeout
                    try:
                        token = await asyncio.wait_for(queue.get(), timeout=0.05)
                        yield token
                    except asyncio.TimeoutError:
                        continue

            chat_result = queue_generator()

        else:
            # Generic engine: only pass session_id if accepted.
            _sid_kwargs = (
                {"session_id": session_id}
                if "session_id" in sig.parameters else {}
            )
            chat_result = engine.chat(messages=messages, system=system_prompt,
                                      images=_images_arg,
                                      thinking_enabled=thinking_enabled,
                                      **_sid_kwargs,
                                      **cancel_kwargs, **sampling_kwargs)

    return chat_result
