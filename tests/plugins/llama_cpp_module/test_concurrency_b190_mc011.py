"""
Concurrency hardening of llama_cpp_module — regression tests.

B190: generation on the shared Llama instance must be serialised on a single
      worker thread (llama-cpp-python is NOT thread-safe). MLX already does this
      via _MLX_EXECUTOR(max_workers=1); llama_cpp used asyncio.to_thread (default
      multi-worker pool) → two concurrent /chat on session 'default' raced.

MC-011: streaming generation must honour cancel_event (set by the route handler
        when the HTTP client disconnects) and break early instead of running to
        max_tokens, leaving an orphan worker that blocks the instance. MLX checks
        cancel_event in its loop; llama_cpp did not even accept the parameter.
"""
import asyncio
import threading
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
from plugins.llama_cpp_module.module import LlamaCppModule


@pytest.fixture(autouse=True)
def reset_pool():
    LlamaCppChatNode._pool = None
    LlamaCppChatNode._config = None
    yield
    LlamaCppChatNode._pool = None
    LlamaCppChatNode._config = None


def _make_config():
    config = MagicMock()
    config.model_path = "/fake/model.gguf"
    config.mmproj_path = None
    config.max_sessions = 1
    return config


def _chunk(text):
    return {"choices": [{"delta": {"content": text}}], "usage": {}}


class TestCancelEventStreaming:
    """MC-011: cancel_event must break the streaming generation loop."""

    def test_cancel_event_breaks_text_streaming(self):
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = _make_config()

        consumed = {"n": 0}

        def many_chunks(*a, **k):
            for _ in range(5000):  # bounded so a broken fix fails instead of hanging
                consumed["n"] += 1
                yield _chunk("x")

        model = MagicMock()
        model.create_chat_completion.side_effect = many_chunks

        ev = threading.Event()
        ev.set()  # already cancelled before generation starts

        node._generate_streaming(
            model, "sys", [{"role": "user", "content": "hi"}],
            lambda p: None, None, None, ev,
        )
        assert consumed["n"] <= 1, f"loop ignored cancel_event (consumed {consumed['n']})"

    def test_cancel_event_breaks_vlm_streaming(self):
        config = _make_config()
        config.mmproj_path = "/fake/mmproj.gguf"
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        consumed = {"n": 0}

        def many_chunks(*a, **k):
            for _ in range(5000):
                consumed["n"] += 1
                yield _chunk("x")

        model = MagicMock()
        model.create_chat_completion.side_effect = many_chunks

        ev = threading.Event()
        ev.set()

        node._generate_vlm_streaming(
            model, "sys", [{"role": "user", "content": "hi"}], [b"\x89PNGfake"],
            lambda p: None, None, None, ev,
        )
        assert consumed["n"] <= 1, f"VLM loop ignored cancel_event (consumed {consumed['n']})"

    def test_no_cancel_event_generates_fully(self):
        """Back-compat: without cancel_event (None) the loop runs normally."""
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = _make_config()

        model = MagicMock()
        model.create_chat_completion.return_value = iter([_chunk("a"), _chunk("b"), _chunk("c")])

        result = node._generate_streaming(
            model, "sys", [{"role": "user", "content": "hi"}],
            lambda p: None, None, None, None,
        )
        assert result["text"] == "abc"


class TestSerializedGeneration:
    """B190: concurrent execute() must not overlap generation (single worker)."""

    @pytest.mark.asyncio
    async def test_generation_serialised_on_single_worker(self):
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config

        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), False)

        state = {"concurrent": 0, "max": 0}
        lock = threading.Lock()

        def fake_generate(model, system, messages, *a, **k):
            with lock:
                state["concurrent"] += 1
                state["max"] = max(state["max"], state["concurrent"])
            time.sleep(0.05)
            with lock:
                state["concurrent"] -= 1
            return {"text": "x", "tokens": 1, "prompt_tokens": 1, "timing": {}}

        with patch.object(LlamaCppChatNode, "_pool", mock_pool), \
             patch.object(LlamaCppChatNode, "_config", config), \
             patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="h"), \
             patch.object(node, "_generate", side_effect=fake_generate):
            await asyncio.gather(
                node.execute({"system": "s", "messages": [], "session_id": "default"}),
                node.execute({"system": "s", "messages": [], "session_id": "default"}),
            )

        assert state["max"] == 1, (
            f"generation overlapped (max concurrent={state['max']}) — not serialised "
            "on a single worker thread"
        )

    def test_dedicated_executor_is_single_worker(self):
        from plugins.llama_cpp_module.core import chat as chat_mod
        assert chat_mod._LLAMA_EXECUTOR._max_workers == 1


class TestCancelEventPropagation:
    """MC-011: cancel_event must reach the node's execute() inputs via module.chat()."""

    @pytest.mark.asyncio
    async def test_module_chat_forwards_cancel_event_to_execute(self):
        module = LlamaCppModule.__new__(LlamaCppModule)
        module._initialized = True
        module._node = MagicMock()
        module._node.execute = AsyncMock(return_value={"response": "ok"})

        ev = threading.Event()
        await module.chat(
            messages=[{"role": "user", "content": "hi"}],
            system="s",
            cancel_event=ev,
        )

        inputs = module._node.execute.call_args[0][0]
        assert inputs["cancel_event"] is ev


class TestExecuteBindsCancelEvent:
    """GAP2: execute() must thread cancel_event into the *streaming* partials
    (mirror of the MLX execute→partial guard). A refactor dropping cancel_event
    from the functools.partial would otherwise pass silently."""

    def _cap_loop(self, captured):
        real_loop = asyncio.get_event_loop()

        class _CapLoop:
            def run_in_executor(self, executor, fn):
                captured["fn"] = fn
                fut = real_loop.create_future()
                fut.set_result({"text": "x", "tokens": 1, "prompt_tokens": 1, "timing": {}})
                return fut

            def call_soon_threadsafe(self, *a, **k):
                pass

        return _CapLoop()

    @pytest.mark.asyncio
    async def test_text_streaming_partial_receives_cancel_event(self):
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = _make_config()
        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), False)
        captured = {}
        ev = threading.Event()

        with patch.object(LlamaCppChatNode, "_pool", mock_pool), \
             patch.object(LlamaCppChatNode, "_config", node.config), \
             patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="h"), \
             patch("plugins.llama_cpp_module.core.chat.asyncio.get_running_loop",
                   return_value=self._cap_loop(captured)):
            await node.execute({
                "system": "s", "messages": [],
                "stream_callback": lambda p: None, "cancel_event": ev,
            })

        fn = captured["fn"]
        assert fn.func.__name__ == "_generate_streaming"
        assert fn.args[-1] is ev, "execute() did not bind cancel_event to the streaming partial"

    @pytest.mark.asyncio
    async def test_vlm_streaming_partial_receives_cancel_event(self):
        config = _make_config()
        config.mmproj_path = "/fake/mmproj.gguf"
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config
        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), False)
        captured = {}
        ev = threading.Event()

        with patch.object(LlamaCppChatNode, "_pool", mock_pool), \
             patch.object(LlamaCppChatNode, "_config", config), \
             patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="h"), \
             patch("plugins.llama_cpp_module.core.chat.asyncio.get_running_loop",
                   return_value=self._cap_loop(captured)):
            await node.execute({
                "system": "s", "messages": [], "images": [b"\x89PNGfake"],
                "stream_callback": lambda p: None, "cancel_event": ev,
            })

        fn = captured["fn"]
        assert fn.func.__name__ == "_generate_vlm_streaming"
        assert fn.args[-1] is ev, "execute() did not bind cancel_event to the VLM streaming partial"


class TestStreamingSerialised:
    """GAP3: serialisation (B190) must hold on the STREAMING path that production
    actually uses (stream_callback present → _generate_streaming), not only the
    no-streaming path."""

    @pytest.mark.asyncio
    async def test_streaming_generation_serialised_on_single_worker(self):
        config = _make_config()
        node = LlamaCppChatNode.__new__(LlamaCppChatNode)
        node.config = config
        mock_pool = MagicMock()
        mock_pool.get_or_create.return_value = (MagicMock(), False)

        state = {"concurrent": 0, "max": 0}
        lock = threading.Lock()

        def fake_streaming(model, system, messages, cb, *a, **k):
            with lock:
                state["concurrent"] += 1
                state["max"] = max(state["max"], state["concurrent"])
            time.sleep(0.05)
            with lock:
                state["concurrent"] -= 1
            return {"text": "x", "tokens": 1, "prompt_tokens": 1, "timing": {}}

        with patch.object(LlamaCppChatNode, "_pool", mock_pool), \
             patch.object(LlamaCppChatNode, "_config", config), \
             patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="h"), \
             patch.object(node, "_generate_streaming", side_effect=fake_streaming):
            await asyncio.gather(
                node.execute({"system": "s", "messages": [], "session_id": "default",
                              "stream_callback": lambda p: None}),
                node.execute({"system": "s", "messages": [], "session_id": "default",
                              "stream_callback": lambda p: None}),
            )

        assert state["max"] == 1, (
            f"streaming generation overlapped (max concurrent={state['max']}) — "
            "not serialised on the single worker"
        )
