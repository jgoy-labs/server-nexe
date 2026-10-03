"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_live/test_rate_retry.py
Description: The live chat stream waits out a 429 (#1111) instead of failing
             the memory assertion. No server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import httpx

from tests.test_live.conftest import read_stream_with_retry


def test_stream_retry_waits_out_one_429(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("tests.test_live.conftest.time.sleep", lambda seconds: slept.append(seconds))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, text="later")
        return httpx.Response(200, text="FET")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://nexe.test")
    status, body = read_stream_with_retry(client, "/ui/chat", json={"message": "hola"})

    assert status == 200
    assert body == "FET"
    assert slept == [1.0]
    assert calls["n"] == 2


def test_stream_retry_returns_the_last_429(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("tests.test_live.conftest.time.sleep", lambda seconds: slept.append(seconds))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"}, text="no")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://nexe.test")
    status, body = read_stream_with_retry(client, "/ui/chat", json={"message": "hola"})

    assert status == 429
    assert body == "no"
    assert slept == [1.0, 1.0]
