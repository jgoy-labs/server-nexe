"""FD-S5 — a max_tokens cut must reach the client as an in-band marker.

Field measurement (8 GB M1, 2026-07-23): three turns ended at 2048 tokens
exactly (~103 s of generation) and the answer just stopped mid-sentence —
no signal anywhere. mlx-lm DOES emit ``finish_reason='length'`` on its final
yield; it died at TWO points on our side: ``extract_metrics`` dropped the
field and ``queue_generator`` discarded the engine's whole result dict.

Contract: ``\\x00[GEN_TRUNCATED:{1|0}]\\x00`` emitted as its OWN yield after
the last text chunk (1 = resumable by FD-S6's Continue, 0 = informative).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugins.mlx_module.core.generate_helpers import extract_metrics


def _metrics(finish_reason):
    last = SimpleNamespace(
        generation_tokens=10, prompt_tokens=5, generation_tps=20.0,
        prompt_tps=100.0, peak_memory=0, finish_reason=finish_reason,
    )
    return extract_metrics(last, "text", False, 0, 5, [1, 2], "hash")


class TestDetectionText:
    def test_extract_metrics_propagates_length(self):
        """Mutation control: dropping the finish_reason line goes RED here."""
        assert _metrics("length")["finish_reason"] == "length"

    def test_extract_metrics_propagates_stop(self):
        assert _metrics("stop")["finish_reason"] == "stop"

    def test_no_response_yields_none(self):
        m = extract_metrics(None, "t", False, 0, 0, [], "h")
        assert m["finish_reason"] is None


class TestContinuableGate:
    """chat.execute()'s continuable: text-only + KV headroom (B004 corner)."""

    def _node(self, max_kv=16384, max_tokens=2048):
        from plugins.mlx_module.core.chat import MLXChatNode
        node = MLXChatNode.__new__(MLXChatNode)  # no __init__: config only
        node.config = MagicMock()
        node.config.max_kv_size = max_kv
        node.config.max_tokens = max_tokens
        return node

    def test_length_text_with_headroom_is_continuable(self):
        node = self._node()
        result = {"finish_reason": "length", "prompt_tokens": 3000, "tokens": 2048}
        assert node._compute_continuable(result, is_vlm=False) is True

    def test_vlm_never_continuable(self):
        node = self._node()
        result = {"finish_reason": "length", "prompt_tokens": 100, "tokens": 100}
        assert node._compute_continuable(result, is_vlm=True) is False

    def test_stop_not_continuable(self):
        node = self._node()
        result = {"finish_reason": "stop", "prompt_tokens": 100, "tokens": 100}
        assert node._compute_continuable(result, is_vlm=False) is False

    def test_kv_window_gate_blocks_the_chain(self):
        """Near the rotating window a Continue would evict the system prompt
        and degenerate mid-chain (B004) — the gate cuts the chain."""
        node = self._node(max_kv=4096)
        result = {"finish_reason": "length", "prompt_tokens": 1500, "tokens": 500}
        # 1500+500+2048+512 = 4560 > 4096 → not continuable
        assert node._compute_continuable(result, is_vlm=False) is False


class TestEosAtTheLimit:
    """Anti-'simplification': EOS exactly at max_tokens is 'stop', never a
    marker — mlx-lm checks EOS BEFORE the ceiling. Protects against someone
    replacing the text path's finish_reason with a token-count heuristic."""

    def test_stop_with_full_count_is_not_length(self):
        m = _metrics("stop")
        assert m["finish_reason"] == "stop"
        assert m["tokens"] == 10  # count alone would have said "length"


@pytest.mark.asyncio
class TestStreamEmission:
    async def _drive(self, chunks, trunc_result=None):
        """Minimal harness over _generate_streaming_response's chunk loop
        contract: feed an async generator, collect the yields."""
        from plugins.web_ui_module.api import routes_chat as rc

        async def _gen():
            for c in chunks:
                yield c
            if trunc_result is not None:
                yield trunc_result

        ctx = MagicMock()
        ctx.chat_result = _gen()
        ctx.model_name = "test-model"
        ctx.rag_count = 0
        ctx.rag_items = []
        ctx.compacted = False
        ctx.doc_truncated_pct = 0
        ctx.session.compaction_count = 0
        ctx.session._pending_partial_delete = None
        ctx.engine = MagicMock()
        ctx.engine_name = "mlx_module"
        ctx.message = "hola"
        ctx.lang = "ca"
        ctx.thinking_enabled = False
        ctx.rag_collections = None
        _mon = MagicMock()
        _mon.done.return_value = True
        ctx.disconnect_monitor_task = _mon
        ctx.memory_helper = AsyncMock()
        ctx.session_mgr = MagicMock()
        out = []
        async for tok in rc._generate_streaming_response(ctx):
            out.append(tok if isinstance(tok, str) else str(tok))
        return "".join(out), out

    async def test_marker_emitted_after_text_on_length(self):
        body, yields = await self._drive(
            ["Hola ", "món"],
            trunc_result={"__nexe_trunc__": True, "continuable": True},
        )
        assert "\x00[GEN_TRUNCATED:1]\x00" in body
        # own yield, never mixed with text
        marker_yields = [y for y in yields if "GEN_TRUNCATED" in y]
        assert marker_yields == ["\x00[GEN_TRUNCATED:1]\x00"]
        # after the last text chunk
        assert body.index("món") < body.index("GEN_TRUNCATED")

    async def test_not_continuable_marks_zero(self):
        body, _ = await self._drive(
            ["text"],
            trunc_result={"__nexe_trunc__": True, "continuable": False},
        )
        assert "\x00[GEN_TRUNCATED:0]\x00" in body

    async def test_no_marker_without_truncation(self):
        body, _ = await self._drive(["Hola ", "món"])
        assert "GEN_TRUNCATED" not in body

    async def test_ollama_done_reason_length_marks_zero(self):
        body, _ = await self._drive(
            [{"message": {"content": "hola"}}, {"done": True, "done_reason": "length"}],
        )
        assert "\x00[GEN_TRUNCATED:0]\x00" in body

    async def test_think_only_degrades_to_zero(self):
        """A turn whose visible text cleans to EMPTY has nothing resumable —
        the marker must degrade to :0 even when the engine said continuable.
        (Real case: the cut landed inside the reasoning; _clean_full_response
        strips the think block and leaves no answer text.)"""
        body, _ = await self._drive(
            ["<think>reasoning, then the cut</think>"],
            trunc_result={"__nexe_trunc__": True, "continuable": True},
        )
        assert "\x00[GEN_TRUNCATED:0]\x00" in body
        assert "GEN_TRUNCATED:1" not in body
