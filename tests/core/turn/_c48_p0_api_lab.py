"""The API column of the C4.8 matrix (phase 3 of the API providers): a fake
PROVIDER (an HTTP server in miniature, behind `httpx.MockTransport`) and the real
`ApiModule` in front of it, driven through the two real doors by the part 0 lab.

Not a test file. What the column pins is what a client meets when it asks for
`api` EXPLICITLY, with the gate open or closed, and when the provider answers
200, 401, 402, 429, 5xx, a timeout, a connection refused, a stream that dies
after its first token, or nothing at all. The key in every request is a
FAKE one, evidently so, and nothing here reaches a network.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from plugins.api_module.module import ApiModule

from ._c48_p0_lab import Seen, World, build_world, run_door

FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"
MODEL = "deepseek-chat"
PROVIDER = "deepseek"
TEXT = ("Hola ", "de api.")

#: How the provider answers, as a vocabulary shared with the matrix of the other engines.
MODES = ("ok", "unauthorized", "balance", "rate_limited", "down", "bad_request", "timeout", "unreachable",
         "mid_stream", "empty")


class _Dying(httpx.AsyncByteStream):
    """A body that gives its first events and then the socket dies."""

    def __init__(self, first: bytes) -> None:
        self._first = first

    async def __aiter__(self):
        yield self._first
        raise httpx.ReadError("socket closed")


def _event(text: str, finish: Optional[str] = None) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": finish}]}) + "\n\n"


class FakeProvider:
    """Records every request it gets (the machine's way out) and answers as `mode` says."""

    def __init__(self, mode: str = "ok", *, script: Optional[list] = None) -> None:
        self.mode = mode
        #: Reply by reply, the whole text each request answers with (the last one repeats): for the
        #: turns that ask the provider twice (the re-prompt, the compaction).
        self.script = list(script or [])
        self.seen: list[httpx.Request] = []
        self.log: Optional[list] = None  # the world's chronological call log, wired by `api_world`

    def bodies(self) -> list:
        return [json.loads(request.content) for request in self.seen]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.log is not None:
            self.log.append("api")
        status = {"unauthorized": 401, "balance": 402, "rate_limited": 429, "down": 503, "bad_request": 400}
        if self.mode in status:
            # The body carries the key on purpose: nothing of it may reach the client or a log.
            return httpx.Response(status[self.mode], json={"error": {"message": f"nope {FAKE_KEY}"}})
        if self.mode == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if self.mode == "unreachable":
            raise httpx.ConnectError("connection refused", request=request)
        stream = json.loads(request.content).get("stream")
        text = TEXT
        if self.script:
            text = (self.script.pop(0) if len(self.script) > 1 else self.script[0],)
        if self.mode == "empty":
            if not stream:
                return httpx.Response(200, json={"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]})
            return httpx.Response(200, content=(_event("", "stop") + "data: [DONE]\n\n").encode())
        if self.mode == "mid_stream":
            if not stream:
                raise httpx.ReadError("socket closed", request=request)
            return httpx.Response(200, stream=_Dying(_event(TEXT[0]).encode()))
        if not stream:
            return httpx.Response(200, json={"choices": [{"message": {"content": "".join(text)}, "finish_reason": "stop"}]})
        body = "".join(_event(t) for t in text) + _event("", "stop") + "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode())

    def module(self) -> ApiModule:
        return ApiModule(transport=httpx.MockTransport(self.handler))


def api_world(provider: FakeProvider, *, live=("ollama",), faults: Optional[dict] = None) -> World:
    """The lab's local engines (healthy by default) plus the API module in front of `provider`."""
    world = build_world(faults or {}, live=live)
    world.modules["api_module"] = provider.module()
    provider.log = world.log
    return world


def consent_for(door: str, provider: str = PROVIDER) -> dict:
    """The consent each door takes: the session's dialog `cloud_consent` at the web, the request's own at /v1."""
    return {"nexe_cloud_consent": provider} if door.startswith("v1") else {"cloud_consent": provider}


async def ask_api(lab, door: str, provider: FakeProvider, *, consent: bool = True, model: Optional[str] = MODEL,
                  live=("ollama",), faults: Optional[dict] = None, sid: Optional[str] = None,
                  extra: Optional[dict] = None) -> tuple[Seen, World]:
    """One turn that asks for `api` through `door`; returns what the client saw and the world."""
    world = api_world(provider, live=live, faults=faults)
    body = ({"model": model} if model else {}) | (consent_for(door) if consent else {}) | (extra or {})
    seen = await run_door(lab, world, door, backend="api", sid=sid or f"api-{provider.mode}-{door}", extra=body)
    if seen.answered is None and "de api." in seen.text:
        seen.answered = "api"  # the web's text is the only evidence of who answered
    return seen, world
