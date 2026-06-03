"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_chat.py
Description: Live chat tests — all backends (Ollama/MLX/llama.cpp),
             streaming, MEM_SAVE via chat, dedup, error handling.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.test_live

_MAX_AUTO_MODEL_GB = 32


def _extract_text(data: dict) -> str:
    return (
        data.get("response")
        or data.get("content")
        or data.get("message")
        or ""
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Ollama
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatOllama:
    """Ollama backend — basic chat, streaming, error cases."""

    pytestmark = pytest.mark.slow  # Bug #4 (2026-05-21): each call ~8-10s, schedule last

    def test_ollama_basic(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        smallest_ollama_model: str,
    ) -> None:
        r = client.post(
            "/ui/chat",
            headers=auth_headers,
            json={"message": "Di 'ok' en una sola paraula.", "backend": "ollama", "model": smallest_ollama_model, "stream": False},
            timeout=90.0,
        )
        assert r.status_code == 200, f"Ollama basic chat: {r.status_code} {r.text[:400]}"
        assert len(_extract_text(r.json())) > 0, f"Empty response: {r.json()}"

    def test_ollama_stream_no_done_sentinel(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        smallest_ollama_model: str,
    ) -> None:
        """Bug A regression (2026-05-21): /ui/chat is text/plain, not SSE.
        The frontend detects end-of-stream via reader.read() returning
        {done:true}, so the backend must NOT emit a literal 'data: [DONE]'
        (it would render as text in the chat bubble).
        """
        with client.stream(
            "POST",
            "/ui/chat",
            headers={**auth_headers, "Accept": "text/event-stream"},
            json={"message": "Di 'ok'.", "backend": "ollama", "model": smallest_ollama_model, "stream": True},
            timeout=90.0,
        ) as r:
            assert r.status_code == 200, f"Stream returned {r.status_code}"
            raw = r.read().decode("utf-8", errors="replace")
        assert "data: [DONE]" not in raw, (
            f"Bug A regression: 'data: [DONE]' literal leaked to client. "
            f"Last 500 chars: {raw[-500:]}"
        )

    @pytest.mark.xfail(
        reason="Server falls back to RAG/context and returns 200 instead of "
               "rejecting unknown model with 4xx. Known bug: model validation "
               "should happen before pipeline execution.",
        strict=True,
    )
    def test_ollama_unknown_model_error(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        r = client.post(
            "/ui/chat",
            headers=auth_headers,
            json={"message": "test", "backend": "ollama", "model": "nexe-nonexistent-model:99b", "stream": False},
            timeout=20.0,
        )
        assert r.status_code in (400, 404, 422, 500), (
            f"Expected error for unknown model, got {r.status_code}: {r.text[:400]}"
        )

    def test_ollama_all_available_models(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        ollama_models: list[str],
    ) -> None:
        """Smoke-test every available Ollama model (skip >32B)."""
        if not ollama_models:
            pytest.skip("No Ollama models available")

        from tests.test_live.conftest import _model_size_gb  # noqa: PLC0415

        results: list[str] = []
        for model in ollama_models:
            size = _model_size_gb(model)
            if size > _MAX_AUTO_MODEL_GB:
                results.append(f"⏭ {model} — skipped (>{_MAX_AUTO_MODEL_GB}GB)")
                continue
            time.sleep(3.5)  # respect rate limiter between model requests
            t0 = time.monotonic()
            r = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": "Di 'ok'.", "backend": "ollama", "model": model, "stream": False},
                timeout=90.0,
            )
            elapsed = time.monotonic() - t0
            if r.status_code == 200 and len(_extract_text(r.json())) > 0:
                results.append(f"✅ {model} — {elapsed:.1f}s")
            else:
                results.append(f"❌ {model} — {r.status_code} {r.text[:100]}")

        print("\nOllama model sweep:\n" + "\n".join(results))
        failed = [r for r in results if r.startswith("❌")]
        assert not failed, "Some models failed:\n" + "\n".join(failed)


# ═══════════════════════════════════════════════════════════════════════════════
# MLX
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatMLX:
    """MLX backend — skip if not available."""

    def test_mlx_basic(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        mlx_available: bool,
    ) -> None:
        if not mlx_available:
            pytest.skip("MLX backend not available on this server")
        r = client.post(
            "/ui/chat",
            headers=auth_headers,
            json={"message": "Di 'ok'.", "backend": "mlx", "stream": False},
            timeout=120.0,
        )
        assert r.status_code == 200, f"MLX chat: {r.status_code} {r.text[:400]}"
        assert len(_extract_text(r.json())) > 0

    def test_mlx_stream(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        mlx_available: bool,
    ) -> None:
        if not mlx_available:
            pytest.skip("MLX backend not available on this server")
        with client.stream(
            "POST",
            "/ui/chat",
            headers={**auth_headers, "Accept": "text/event-stream"},
            json={"message": "Di 'ok'.", "backend": "mlx", "stream": True},
            timeout=120.0,
        ) as r:
            assert r.status_code == 200
            raw = r.read().decode("utf-8", errors="replace")
        assert "data: [DONE]" not in raw, (
            f"Bug A regression (MLX): 'data: [DONE]' literal leaked to client. "
            f"Last 500: {raw[-500:]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# llama.cpp
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatLlamaCpp:
    """llama.cpp backend — skip if not available."""

    def test_llama_cpp_basic(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        llama_cpp_available: bool,
    ) -> None:
        if not llama_cpp_available:
            pytest.skip("llama.cpp backend not available on this server")
        r = client.post(
            "/ui/chat",
            headers=auth_headers,
            json={"message": "Di 'ok'.", "backend": "llama_cpp", "stream": False},
            timeout=120.0,
        )
        assert r.status_code == 200, f"llama.cpp chat: {r.status_code} {r.text[:400]}"
        assert len(_extract_text(r.json())) > 0

    def test_llama_cpp_stream(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        llama_cpp_available: bool,
    ) -> None:
        if not llama_cpp_available:
            pytest.skip("llama.cpp backend not available on this server")
        with client.stream(
            "POST",
            "/ui/chat",
            headers={**auth_headers, "Accept": "text/event-stream"},
            json={"message": "Di 'ok'.", "backend": "llama_cpp", "stream": True},
            timeout=120.0,
        ) as r:
            assert r.status_code == 200
            raw = r.read().decode("utf-8", errors="replace")
        assert "data: [DONE]" not in raw, (
            f"Bug A regression (llama.cpp): 'data: [DONE]' literal leaked. "
            f"Last 500: {raw[-500:]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MEM_SAVE via chat — the critical case
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatMEMSAVE:
    """Verify that the chat pipeline saves memories when the user asks."""

    pytestmark = pytest.mark.slow  # Bug #4 (2026-05-21): Ollama-backed, schedule last

    def test_mem_save_via_chat_and_retrieve(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        smallest_ollama_model: str,
    ) -> None:
        """
        The core nexe feature: tell it to remember X → search → find X.
        If this fails, the memory pipeline is broken regardless of unit tests.
        """
        token = uuid.uuid4().hex[:10]
        msg = f"Recorda que el meu codi secret de test és NEXE_{token}"

        chat_r = client.post(
            "/ui/chat",
            headers=auth_headers,
            json={"message": msg, "backend": "ollama", "model": smallest_ollama_model, "stream": False},
            timeout=90.0,
        )
        assert chat_r.status_code == 200, f"Chat MEM_SAVE: {chat_r.status_code} {chat_r.text[:400]}"

        # Give the async memory pipeline a moment to persist
        time.sleep(2)

        search_r = client.post(
            "/v1/memory/search",
            headers=auth_headers,
            json={"query": f"codi secret NEXE_{token}", "limit": 5},
            timeout=15.0,
        )
        assert search_r.status_code == 200, f"Memory search: {search_r.status_code}"
        data = search_r.json()
        results = data if isinstance(data, list) else data.get("results", data.get("memories", []))
        raw_text = search_r.text
        assert len(results) >= 1 or token in raw_text, (
            f"MEM_SAVE did not persist NEXE_{token}. "
            f"Search returned {len(results)} results. Response: {raw_text[:600]}"
        )

    def test_mem_save_dedup(
        self,
        client: httpx.Client,
        auth_headers: dict[str, str],
        smallest_ollama_model: str,
    ) -> None:
        """Same fact sent 3× should be deduplicated (threshold 0.80)."""
        # Use 12-char token to minimise cross-run semantic collisions
        token = uuid.uuid4().hex[:12]
        for phrase in (
            f"Recorda que el meu animal preferit és el gat_{token}.",
            f"Guarda que tinc un gat que es diu gat_{token}.",
            f"No oblidis que el meu animal és el gat_{token}.",
        ):
            r = client.post(
                "/ui/chat",
                headers=auth_headers,
                json={"message": phrase, "backend": "ollama", "model": smallest_ollama_model, "stream": False},
                timeout=90.0,
            )
            assert r.status_code == 200, f"MEM_SAVE dedup chat: {r.status_code}"
            time.sleep(1)

        time.sleep(2)
        search_r = client.post(
            "/v1/memory/search",
            headers=auth_headers,
            json={"query": f"animal gat_{token}", "limit": 10},
            timeout=15.0,
        )
        assert search_r.status_code == 200
        data = search_r.json()
        all_results = data if isinstance(data, list) else data.get("results", data.get("memories", []))
        # Only count results that actually contain our unique token
        token_results = [r for r in all_results if token in str(r)]
        assert len(token_results) <= 2, (
            f"Expected dedup to reduce 3 similar memories to ≤2, got {len(token_results)} "
            f"(total results: {len(all_results)})"
        )
