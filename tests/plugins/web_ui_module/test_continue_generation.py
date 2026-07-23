"""FD-S6 — the Continue button: resume a ceiling-cut answer.

The three traps this design dodges (adversarial verification, 2026-07-23):

1. TEMPLATE: the naive flow (add_generation_prompt=True) closes the partial
   with ``<|im_end|>`` and opens a FRESH assistant block — the model REPEATS
   instead of continuing. ``continue_final_message=True`` renders the prompt
   ending exactly at the partial text. Validated against the real Qwen3.5
   tokenizer when available (skip otherwise).
2. PERSIST: the tail must MERGE in-place into the truncated assistant message.
   ``get_context_messages`` dedupes consecutive roles keeping only the LATEST
   — an ``add_message("assistant", tail)`` would erase the first half.
3. LATENCY: with thinking ON the persisted content is CLEAN; its re-render
   diverges token-wise from the KV cache. ``gen_raw`` (the raw generation)
   keeps the continue prompt an exact token prefix of the cache entry.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core.generate_helpers import (
    _apply_template,
    save_cache_post_generation,
)

# Any locally available Qwen3.5 works — same chat template across the family.
_QWEN_CANDIDATES = [
    Path.home() / "models" / "Qwen3.5-4B-4bit",
    Path.home() / "models" / "Qwen3.5-4B-MLX-4bit",
    Path.home() / "models" / "Qwen3.5-2B-4bit",
]


def _load_qwen_tokenizer():
    path = next(
        (p for p in _QWEN_CANDIDATES if (p / "tokenizer_config.json").exists()),
        None,
    )
    if path is None:
        pytest.skip("no Qwen3.5 tokenizer on disk")
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(str(path))


@pytest.mark.slow
class TestContinueTemplate:
    """The exigent test: the continue prompt must END at the partial text."""

    def test_continue_prompt_ends_at_partial(self):
        tok = _load_qwen_tokenizer()
        partial = "The three laws of robotics are: 1. A robot may not"
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Tell me about the three laws."},
            {"role": "assistant", "content": partial},
        ]
        prompt = _apply_template(tok, msgs, thinking_enabled=True, continue_final=True)
        assert prompt.endswith(partial), (
            "the continue prompt must end exactly at the partial text"
        )
        assert prompt.count("<|im_start|>assistant") == 1, (
            "a NEW assistant block means the model will repeat, not continue"
        )
        tail = prompt[prompt.index(partial):]
        assert "<|im_end|>" not in tail, "the partial got closed — repeat bug"

    def test_normal_flow_would_repeat(self):
        """RED-baseline: proves the naive flow produces the repeat shape —
        i.e. that continue_final is load-bearing, not decoration."""
        tok = _load_qwen_tokenizer()
        partial = "The answer is: first,"
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": partial},
        ]
        prompt = _apply_template(tok, msgs, thinking_enabled=True, continue_final=False)
        assert prompt.count("<|im_start|>assistant") == 2, (
            "expected the naive flow to open a fresh assistant block"
        )

    def test_continue_with_thinking_off(self):
        tok = _load_qwen_tokenizer()
        partial = "Resposta parcial que es va tallar"
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "pregunta"},
            {"role": "assistant", "content": partial},
        ]
        prompt = _apply_template(tok, msgs, thinking_enabled=False, continue_final=True)
        assert prompt.endswith(partial)


class TestCachePostGenerationMerge:
    """On continue, the cache entry merges WITHOUT the \\n\\n separator."""

    def _mgr(self):
        mgr = MagicMock()
        return mgr

    def test_continue_merge_has_no_separator(self):
        mgr = self._mgr()
        tok = MagicMock()
        tok.apply_chat_template.return_value = [1, 2, 3]
        msgs = [{"role": "user", "content": "q"},
                {"role": "assistant", "content": "first half"}]
        save_cache_post_generation(
            mgr, "key", msgs, " second half", tok, MagicMock(), 10,
            continue_final=True,
        )
        merged = tok.apply_chat_template.call_args[0][0]
        assert merged[-1]["content"] == "first half second half", (
            "a separator at the seam corrupts the resumed sentence"
        )

    def test_legacy_merge_keeps_separator(self):
        """Mutation control: dropping the flag would break the legacy path."""
        mgr = self._mgr()
        tok = MagicMock()
        tok.apply_chat_template.return_value = [1, 2, 3]
        msgs = [{"role": "user", "content": "q"},
                {"role": "assistant", "content": "placeholder"}]
        save_cache_post_generation(
            mgr, "key", msgs, "text", tok, MagicMock(), 10,
        )
        merged = tok.apply_chat_template.call_args[0][0]
        assert merged[-1]["content"] == "placeholder\n\ntext"


class TestVlmGate:
    async def test_vlm_continue_raises(self, tmp_path):
        """D-C: phase 1 is text-only — the VLM path must refuse loudly."""
        from plugins.mlx_module.core.chat import MLXChatNode

        model_dir = tmp_path / "vlm"
        model_dir.mkdir()
        (model_dir / "config.json").write_text(json.dumps({
            "model_type": "qwen3_vl",
            "architectures": ["Qwen3VLForConditionalGeneration"],
        }))
        config = MagicMock()
        config.model_path = str(model_dir)
        node = MLXChatNode.__new__(MLXChatNode)
        node.config = config
        with pytest.raises(ValueError, match="VLM"):
            await node.execute({
                "system": "s", "messages": [{"role": "user", "content": "q"}],
                "continue_final": True,
            })


class TestContinueHandler:
    """The routes-level guards, driven through a real FastAPI app."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limiter(self):
        """slowapi's per-client bucket is shared across the whole test run —
        20 req/min from 'testclient' trips 429 when other route tests ran
        first (same pattern as test_chat_inner_behavior)."""
        from core.dependencies import limiter
        original = limiter.enabled
        limiter.enabled = False
        yield
        limiter.enabled = original

    def _client(self, session=None):
        from fastapi import FastAPI, APIRouter
        from fastapi.testclient import TestClient
        from plugins.web_ui_module.api import routes_chat as rc

        session_mgr = MagicMock()
        session_mgr.is_valid_session_id.return_value = True
        if session is not None:
            session_mgr.get_or_create_session.return_value = session
        router = APIRouter()
        rc.register_chat_routes(
            router, session_mgr=session_mgr, require_ui_auth=lambda: None
        )
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_400_without_session_id(self):
        client = self._client()
        r = client.post("/chat", json={"continue": True})
        assert r.status_code == 400
        assert "session_id" in r.json()["detail"]

    def test_400_when_last_message_is_not_assistant(self):
        session = MagicMock()
        session.messages = [{"role": "user", "content": "pregunta"}]
        session.id = "s1"
        client = self._client(session)
        r = client.post("/chat", json={"continue": True, "session_id": "s1"})
        assert r.status_code == 400
        assert "assistant" in r.json()["detail"]

    def test_400_on_empty_session(self):
        session = MagicMock()
        session.messages = []
        session.id = "s1"
        client = self._client(session)
        r = client.post("/chat", json={"continue": True, "session_id": "s1"})
        assert r.status_code == 400


class TestPersistMerge:
    """The dedupe trap: merging in-place vs add_message."""

    def test_merge_survives_get_context_messages(self):
        """Simulates the session contract: two consecutive assistant
        messages collapse to the LAST one — the merged single message
        survives. Mutation control for the in-place merge decision."""
        from plugins.web_ui_module.core.session_manager import ChatSession

        session = ChatSession(session_id="t-1")
        session.add_message("user", "pregunta")
        session.add_message("assistant", "primera meitat")
        # the FD-S6 merge:
        session.messages[-1]["content"] += " i la segona"
        ctx = session.get_context_messages()
        assistants = [m for m in ctx if m["role"] == "assistant"]
        assert len(assistants) == 1
        assert assistants[0]["content"] == "primera meitat i la segona"

    def test_add_message_would_lose_the_first_half(self):
        """Documents WHY add_message is forbidden here: the dedupe keeps
        only the latest consecutive assistant message."""
        from plugins.web_ui_module.core.session_manager import ChatSession

        session = ChatSession(session_id="t-2")
        session.add_message("user", "pregunta")
        session.add_message("assistant", "primera meitat")
        session.add_message("assistant", "la cua sola")
        ctx = session.get_context_messages()
        assistants = [m for m in ctx if m["role"] == "assistant"]
        if len(assistants) == 1:
            # dedupe active: the first half is GONE — the exact bug
            assert assistants[0]["content"] == "la cua sola"
