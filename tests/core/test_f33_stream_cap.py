"""Hard cap on streamed bytes per response.

Tests target the pure resolver `_resolve_max_stream_bytes` (env parsing)
and the runtime `TokenBridge.on_token` behaviour (with the cap patched
directly via monkeypatch rather than reloading the module, so the global
state stays clean for downstream tests).
"""

import asyncio

import pytest

from core.endpoints.chat_engines import _streaming
from core.endpoints.chat_engines._streaming import (
  TokenBridge,
  _resolve_max_stream_bytes,
)


# ── _resolve_max_stream_bytes ────────────────────────────────────────────────

def test_resolver_default_when_unset(monkeypatch):
  monkeypatch.delenv("NEXE_MAX_STREAM_MB", raising=False)
  assert _resolve_max_stream_bytes() == 100 * 1024 * 1024


def test_resolver_env_override(monkeypatch):
  monkeypatch.setenv("NEXE_MAX_STREAM_MB", "50")
  assert _resolve_max_stream_bytes() == 50 * 1024 * 1024


def test_resolver_invalid_falls_back(monkeypatch, caplog):
  monkeypatch.setenv("NEXE_MAX_STREAM_MB", "not-a-number")
  with caplog.at_level("WARNING"):
    value = _resolve_max_stream_bytes()
  assert value == 100 * 1024 * 1024
  assert any("not an integer" in r.message for r in caplog.records)


def test_resolver_non_positive_falls_back(monkeypatch, caplog):
  monkeypatch.setenv("NEXE_MAX_STREAM_MB", "-5")
  with caplog.at_level("WARNING"):
    value = _resolve_max_stream_bytes()
  assert value == 100 * 1024 * 1024
  assert any("not positive" in r.message for r in caplog.records)


def test_resolver_above_ceiling_logs_but_honours(monkeypatch, caplog):
  monkeypatch.setenv("NEXE_MAX_STREAM_MB", "500")
  with caplog.at_level("WARNING"):
    value = _resolve_max_stream_bytes()
  assert value == 500 * 1024 * 1024
  assert any("exceeds the recommended ceiling" in r.message for r in caplog.records)


def test_resolver_empty_env_falls_back(monkeypatch):
  monkeypatch.setenv("NEXE_MAX_STREAM_MB", "  ")
  assert _resolve_max_stream_bytes() == 100 * 1024 * 1024


# ── TokenBridge.on_token cap enforcement ────────────────────────────────────

@pytest.mark.asyncio
async def test_token_bridge_stops_accumulating_when_cap_hit(monkeypatch):
  """on_token must early-out and signal done once the byte cap is reached."""
  monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 1 * 1024 * 1024)
  bridge = TokenBridge(maxsize=1024)
  big_chunk = "x" * (256 * 1024)  # 256 KiB → 4 fit (1 MiB), 5th overflows.

  for _ in range(8):
    bridge.on_token(big_chunk)

  # `set_done` schedules `done.set` via call_soon_threadsafe; yield so the
  # event loop runs that callback before we observe the flag.
  await asyncio.sleep(0)

  assert bridge._cap_triggered is True
  assert bridge._response_bytes <= 1 * 1024 * 1024
  assert bridge.done.is_set()
  assert bridge.error == "stream_cap_exceeded"


@pytest.mark.asyncio
async def test_token_bridge_below_cap_keeps_streaming(monkeypatch):
  """Tokens that fit must accumulate without triggering the cap."""
  monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 1 * 1024 * 1024)
  bridge = TokenBridge(maxsize=1024)
  bridge.on_token("hello")
  bridge.on_token(" ")
  bridge.on_token("world")

  assert bridge._cap_triggered is False
  assert bridge._response_bytes == len("hello") + 1 + len("world")
  assert bridge.get_response_text() == "hello world"


@pytest.mark.asyncio
async def test_token_bridge_late_tokens_after_cap_are_dropped_silently(monkeypatch):
  """Engine threads may still emit tokens after the cap fires; drop them."""
  monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 64)
  bridge = TokenBridge(maxsize=1024)
  bridge.on_token("a" * 32)
  bridge.on_token("b" * 64)  # overflows → cap triggers
  pre_bytes = bridge._response_bytes
  bridge.on_token("late")  # must be ignored, no exception
  assert bridge._response_bytes == pre_bytes
  assert bridge._cap_triggered is True
