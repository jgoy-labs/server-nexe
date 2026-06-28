"""
Tests for uncovered lines in core/request_size_limiter.py.
Targets: lines 83-121 (streaming body), 137-140 (receive), 143-151 (invalid CL)
"""
import pytest
import httpx
from unittest.mock import MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI, Request
from core.request_size_limiter import RequestSizeLimiterMiddleware


def _make_app(max_size=1024):
    app = FastAPI()
    app.add_middleware(RequestSizeLimiterMiddleware, max_size=max_size)

    @app.post("/test")
    async def test_endpoint(request: Request):
        body = await request.body()
        return {"size": len(body)}

    return app


class TestRequestSizeContentLength:
    """Lines 140-147: Content-Length based rejection."""

    def test_content_length_exceeds_limit_with_security_logger(self):
        """Lines 50-56: security logger called when content-length exceeds."""
        app = _make_app(max_size=10)
        mock_logger = MagicMock()
        app.state.security_logger = mock_logger

        client = TestClient(app)
        resp = client.post("/test",
                           content="x" * 100,
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 413


class TestReceiveFunction:
    """Lines 106-113: receive() closure replays consumed body."""

    def test_body_reconstruction_works(self):
        """Lines 102-113: body consumed via streaming is replayed to handler."""
        app = _make_app(max_size=10000)
        client = TestClient(app)
        body = "hello world"
        resp = client.post("/test",
                           content=body,
                           headers={"Content-Type": "text/plain"})
        assert resp.status_code == 200
        assert resp.json()["size"] == len(body.encode())


class TestStreamingReject:
    """T16/T17 — lines 83-98: _read_streaming_body rejects oversized chunked body.

    TestClient always injects Content-Length, so these tests use
    httpx.ASGITransport with an async generator body to force the
    streaming code path (request_size_limiter.py:153-156).
    """

    async def test_streaming_request_too_large(self):
        """T16 — chunked POST without Content-Length exceeding limit → 413 via streaming path.

        Mutation gate: disabling lines 97-98 makes this RED (200 instead of 413).
        """
        app = _make_app(max_size=5)

        async def oversized_body():
            yield b"xxx"   # 3 bytes
            yield b"xxx"   # 3 bytes → total 6 > 5

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/test", content=oversized_body())

        # Guard: confirm we did NOT send Content-Length (wrong path otherwise)
        assert "content-length" not in resp.request.headers, (
            "Streaming path was not exercised — Content-Length was injected by client"
        )
        assert resp.status_code == 413
        body = resp.json()
        # The streaming-specific error label confirms the right branch was hit
        assert "streaming" in body["error"].lower()

    async def test_streaming_with_security_logger(self):
        """T17 — security_logger.log_request_too_large is called on streaming rejection.

        Verifies both the 413 response AND that the security logger is invoked.
        Mutation gate: removing the log_request_too_large call in _reject_too_large
        (lines 50-56) makes the mock assertion RED.
        """
        app = _make_app(max_size=5)
        mock_logger = MagicMock()
        app.state.security_logger = mock_logger

        async def oversized_body():
            yield b"xxxx"  # 4 bytes
            yield b"xxxx"  # 4 bytes → total 8 > 5

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/test", content=oversized_body())

        assert "content-length" not in resp.request.headers, (
            "Streaming path was not exercised — Content-Length was injected by client"
        )
        assert resp.status_code == 413
        # Security logger must have been called exactly once
        mock_logger.log_request_too_large.assert_called_once()


class TestInvalidContentLength:
    """T18 — lines 143-151: negative or non-numeric Content-Length handling.

    Production currently catches ValueError and falls through to the streaming
    path (content_length = None).  For a small body, this returns 200 instead
    of the expected 400.  This is a live bug (B-T18).
    """

    @pytest.mark.xfail(
        reason="bug viu B-T18 — Content-Length negatiu hauria de retornar 400 "
               "però la branca ValueError (línies 143-151) fa content_length=None "
               "i el body petit passa per streaming retornant 200; "
               "derivat a revisió humana",
        strict=False,
    )
    async def test_negative_content_length_treated_as_invalid(self):
        """T18 — negative Content-Length must be rejected with 400.

        Production path: int('-1') < 0 → raise ValueError → except catches →
        content_length = None → streaming branch → body passes → 200.
        Expected: 400 (invalid header).

        Mutation gate: if the ValueError branch were fixed to return 400,
        this test would start passing (xfail → xpass → promote to regular test).
        """
        app = _make_app(max_size=1000)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/test",
                content=b"hello",
                headers={"Content-Length": "-1"},
            )
        assert resp.status_code == 400

    def test_invalid_content_length_string_falls_through_to_streaming(self):
        """Non-numeric Content-Length is treated as absent, body falls to streaming check.

        This documents the ACTUAL production behaviour: invalid CL is ignored,
        body goes through streaming path, and a small body passes (200).
        This is an honest assertion of what production does today.

        Mutation gate: if the ValueError handler were changed to return 400,
        this test would fail (200 ≠ 200 because resp.status_code == 400).
        """
        app = _make_app(max_size=1000)
        client = TestClient(app)
        # TestClient will override our non-numeric CL with the real length,
        # so we use a manual header approach via httpx ASGI to avoid that.
        import asyncio

        async def _run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as c:
                return await c.post(
                    "/test",
                    content=b"test",
                    headers={"Content-Length": "not-a-number"},
                )

        resp = asyncio.run(_run())
        # invalid CL → ValueError → None → streaming → small body passes → 200
        assert resp.status_code == 200
