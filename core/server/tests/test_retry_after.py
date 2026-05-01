"""C13 r4: 429 responses carry a standard `Retry-After` header.

The slowapi default emits `X-RateLimit-*` headers (de-facto), but RFC 7231
§7.1.3 mandates `Retry-After` for 429. Without it, well-behaved clients have
no portable way to back off — they fall back to fixed retry intervals or fail.
"""
import pytest

from core.server.exception_handlers import _retry_after_seconds


@pytest.mark.parametrize(
  ("detail", "expected"),
  [
    ("2 per 1 minute", 60),
    ("100 per 1 hour", 3600),
    ("1 per 5 second", 5),
    ("10 per 2 minute", 120),
    ("1 per 1 day", 86400),
    # Whitespace variations
    ("2 per  1   minute", 60),
    # Unit case-insensitive
    ("2 per 1 MINUTE", 60),
    ("5 per 1 Hour", 3600),
  ],
)
def test_retry_after_parses_slowapi_format(detail, expected):
  """Standard slowapi `'<n> per <m> <unit>'` → seconds."""
  assert _retry_after_seconds(detail) == expected


@pytest.mark.parametrize("detail", [None, "", "   ", "garbage", "10/min", "limit exceeded"])
def test_retry_after_unparseable_falls_back_to_60(detail):
  """Anything we can't parse → 60s default. NEVER 0 (would mean retry-now)."""
  assert _retry_after_seconds(detail) == 60


def test_retry_after_is_always_positive_integer():
  """Output MUST be a positive int — RFC 7231 forbids fractional or negative."""
  for detail in ["1 per 1 second", "2 per 1 minute", None, "garbage"]:
    result = _retry_after_seconds(detail)
    assert isinstance(result, int)
    assert result > 0


def test_handler_attaches_retry_after_header():
  """Integration-lite: the 429 JSONResponse carries a Retry-After header."""
  from fastapi import FastAPI, Request
  from fastapi.testclient import TestClient
  from slowapi import Limiter
  from slowapi.errors import RateLimitExceeded
  from slowapi.util import get_remote_address

  from core.server.exception_handlers import register_exception_handlers

  app = FastAPI()
  limiter = Limiter(key_func=get_remote_address)
  app.state.limiter = limiter
  register_exception_handlers(app, i18n=None)

  @app.get("/limited")
  @limiter.limit("1 per 1 minute")
  async def limited(request: Request):
    return {"ok": True}

  client = TestClient(app)
  # First call: 200
  r1 = client.get("/limited")
  assert r1.status_code == 200
  # Second call within the minute: 429 with Retry-After
  r2 = client.get("/limited")
  assert r2.status_code == 429
  assert "Retry-After" in r2.headers, f"Headers: {dict(r2.headers)}"
  retry_after = int(r2.headers["Retry-After"])
  assert retry_after == 60, f"Expected 60s for '1 per 1 minute', got {retry_after}"
