"""
------------------------------------
Server Nexe
Author: Jordi Goy
Location: tests/core/endpoints/test_stream_common.py
Description: Unit tests for shared streaming infrastructure (_streaming.py).

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, patch

MODULE = "core.endpoints.chat_engines._streaming"


class TestTokenBridge_BasicFlow:

    @pytest.mark.asyncio
    async def test_on_token_enqueues_and_records(self):
        from core.endpoints.chat_engines._streaming import TokenBridge

        bridge = TokenBridge()
        bridge.on_token("hello")
        await asyncio.sleep(0)  # let event loop process call_soon_threadsafe
        token = bridge.queue.get_nowait()
        assert token == "hello"
        assert bridge.get_response_text() == "hello"

    @pytest.mark.asyncio
    async def test_multiple_tokens_accumulate(self):
        from core.endpoints.chat_engines._streaming import TokenBridge

        bridge = TokenBridge()
        bridge.on_token("one")
        bridge.on_token("two")
        bridge.on_token("three")
        assert bridge.get_response_text() == "onetwothree"


class TestTokenBridge_QueueFull:

    @pytest.mark.asyncio
    async def test_queue_full_does_not_crash(self):
        from core.endpoints.chat_engines._streaming import TokenBridge

        bridge = TokenBridge(maxsize=1)
        bridge.on_token("first")
        await asyncio.sleep(0)
        # Queue has 1 item, maxsize=1 → next put_nowait should fail silently
        bridge.on_token("second")
        await asyncio.sleep(0)
        # Should not raise, token still recorded in response parts
        assert bridge.get_response_text() == "firstsecond"


class TestTokenBridge_DoneSignal:

    @pytest.mark.asyncio
    async def test_done_event_is_set(self):
        from core.endpoints.chat_engines._streaming import TokenBridge

        bridge = TokenBridge()
        assert not bridge.done.is_set()
        bridge.set_done(result={"tokens": 5})
        await asyncio.sleep(0)
        assert bridge.done.is_set()
        assert bridge.result == {"tokens": 5}

    @pytest.mark.asyncio
    async def test_done_with_error(self):
        from core.endpoints.chat_engines._streaming import TokenBridge

        bridge = TokenBridge()
        bridge.set_done(error="boom")
        await asyncio.sleep(0)
        assert bridge.done.is_set()
        assert bridge.error == "boom"


class TestSSEFormat_TokenChunk:

    def test_format_sse_chunk_structure(self):
        from core.endpoints.chat_engines._streaming import format_sse_chunk

        result = format_sse_chunk("hello", "test-model", "mlx")
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        data = json.loads(result[6:].strip())
        assert data["object"] == "chat.completion.chunk"
        assert data["model"] == "test-model"
        assert data["choices"][0]["delta"]["content"] == "hello"
        assert data["choices"][0]["finish_reason"] is None
        assert data["id"].startswith("mlx-stream-")


class TestSSEFormat_FinalChunk:

    def test_format_sse_done_structure(self):
        from core.endpoints.chat_engines._streaming import format_sse_done

        result = format_sse_done("test-model", "llamacpp")
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        data = json.loads(result[6:].strip())
        assert data["choices"][0]["finish_reason"] == "stop"
        assert data["choices"][0]["delta"] == {}
        assert data["id"].startswith("llamacpp-stream-")


class TestBackgroundMemorySaver_Success:

    @pytest.mark.asyncio
    async def test_save_ok_no_error(self):
        from core.endpoints.chat_engines._streaming import background_memory_save

        with patch(f"{MODULE}._save_conversation_to_memory", new_callable=AsyncMock) as mock_save:
            await background_memory_save(object(), "user msg", "response text")
            mock_save.assert_called_once()


class TestBackgroundMemorySaver_RetryOnce:

    @pytest.mark.asyncio
    async def test_first_failure_retries_then_succeeds(self):
        from core.endpoints.chat_engines._streaming import background_memory_save

        call_count = 0

        async def flaky_save(*_a, **_kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")

        with patch(f"{MODULE}._save_conversation_to_memory", side_effect=flaky_save):
            await background_memory_save(object(), "user msg", "response text")
            assert call_count == 2


class TestBackgroundMemorySaver_GiveUp:

    @pytest.mark.asyncio
    async def test_two_failures_logs_error(self):
        from core.endpoints.chat_engines._streaming import background_memory_save

        with patch(f"{MODULE}._save_conversation_to_memory", side_effect=RuntimeError("permanent")):
            with patch(f"{MODULE}.logger") as mock_logger:
                await background_memory_save(object(), "user msg", "response text")
                mock_logger.error.assert_called_once()


class TestBackgroundMemorySaver_Skip:

    @pytest.mark.asyncio
    async def test_empty_response_skips(self):
        from core.endpoints.chat_engines._streaming import background_memory_save

        with patch(f"{MODULE}._save_conversation_to_memory", new_callable=AsyncMock) as mock_save:
            await background_memory_save(object(), "user msg", "   ")
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_app_state_skips(self):
        from core.endpoints.chat_engines._streaming import background_memory_save

        with patch(f"{MODULE}._save_conversation_to_memory", new_callable=AsyncMock) as mock_save:
            await background_memory_save(None, "user msg", "response")
            mock_save.assert_not_called()
