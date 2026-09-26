"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/llama_cpp_module/test_adr010_llama_splits_reasoning.py
Description: ADR-010 — the llama.cpp plugin returns its model's reasoning
             apart from the answer, as {thinking, content} chunks.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import MagicMock, patch

import pytest

from core.turn.text.chunks import parse_chunk
from plugins.llama_cpp_module.core.chat import LlamaCppChatNode

TOKENS = ["<think>raona", "ment</th", "ink>\n", "Hola."]


@pytest.mark.asyncio
async def test_inline_reasoning_leaves_the_plugin_split():
    config = MagicMock()
    config.model_path = "/fake/qwen3.gguf"
    config.max_sessions = 1
    config.mmproj_path = None
    node = LlamaCppChatNode.__new__(LlamaCppChatNode)
    node.config = config
    pool = MagicMock()
    pool.get_or_create.return_value = (MagicMock(), True)

    def _gen(model, system, messages, callback, *a, **k):
        for t in TOKENS:
            callback(t)
        return {"text": "".join(TOKENS), "tokens": 4, "prompt_tokens": 3, "timing": {}}

    got = []
    with patch.object(LlamaCppChatNode, "_pool", pool), \
         patch.object(LlamaCppChatNode, "_config", config), \
         patch("plugins.llama_cpp_module.core.chat.compute_system_hash", return_value="h"), \
         patch.object(node, "_generate_streaming", side_effect=_gen):
        result = await node.execute({"system": "", "messages": [], "stream_callback": got.append})

    parts = [parse_chunk(c) for c in got]
    assert "".join(t for _, t in parts) == "raonament"
    assert "".join(c for c, _ in parts) == "Hola."
    assert (result["thinking"], result["response"]) == ("raonament", "Hola.")
