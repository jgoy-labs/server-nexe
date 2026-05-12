"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_chat.py
Description: Live chat endpoint tests (Ollama backend).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import pytest
import httpx


pytestmark = pytest.mark.test_live

# Smallest available model — override with NEXE_TEST_MODEL env var
import os
TEST_MODEL = os.getenv("NEXE_TEST_MODEL", "gemma4:e4b")


class TestChat:
    """POST /ui/chat — basic chat, streaming, error handling."""

    def test_chat_basic(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            "/ui/chat",
            headers=auth_headers,
            json={"message": "Respon amb una sola paraula: hola", "model": TEST_MODEL},
            timeout=60.0,
        )
        assert r.status_code == 200, (
            f"Chat returned {r.status_code}: {r.text[:400]}"
        )
        data = r.json()
        response_text = (
            data.get("response") or data.get("content") or data.get("message") or ""
        )
        assert len(response_text) > 0, f"Empty response body: {data}"

    def test_chat_nonexistent_model_returns_error(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            "/ui/chat",
            headers=auth_headers,
            json={"message": "test", "model": "nexe-model-que-no-existeix:99b"},
            timeout=15.0,
        )
        assert r.status_code in (400, 404, 422, 500), (
            f"Expected error status for unknown model, got {r.status_code}"
        )

    def test_chat_stream_contains_done(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """SSE streaming response must end with [DONE] marker."""
        with client.stream(
            "POST",
            "/ui/chat",
            headers={**auth_headers, "Accept": "text/event-stream"},
            json={
                "message": "Di 'ok'",
                "model": TEST_MODEL,
                "stream": True,
            },
            timeout=60.0,
        ) as r:
            assert r.status_code == 200, f"Stream returned {r.status_code}"
            raw = r.read().decode("utf-8", errors="replace")

        assert "[DONE]" in raw or "data: [DONE]" in raw, (
            f"[DONE] marker not found in stream response. "
            f"First 500 chars: {raw[:500]}"
        )

    def test_openai_compat_chat(
        self, client: httpx.Client, auth_headers: dict[str, str]
    ) -> None:
        """POST /v1/chat/completions — OpenAI-compatible endpoint."""
        r = client.post(
            "/v1/chat/completions",
            headers=auth_headers,
            json={
                "model": TEST_MODEL,
                "messages": [{"role": "user", "content": "Di 'ok'"}],
            },
            timeout=60.0,
        )
        assert r.status_code in (200, 501), (
            f"OpenAI compat returned {r.status_code}: {r.text[:400]}"
        )
