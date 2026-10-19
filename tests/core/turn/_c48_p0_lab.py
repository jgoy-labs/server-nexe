"""The lab of the C4.8 part 0 (characterization): fake engines of the real shapes,
and the two REAL doors driven through their route handlers.

Not a test file (the underscore keeps pytest from collecting it). It is the
net the rest of C4.8 works over: `test_c48_p0_matrix.py` and
`test_c48_p0_rows.py` say what the doors do TODAY, and a later part that moves
the cascade changes only the rows its decision names.

What is reused, not invented:

* the engines are `test_1117`'s `_MlxShaped` / `_OllamaShaped` (the shapes
  #1117, #1035 and #1144 already drive), widened only where a failure mode they
  lack is needed (a failure after N tokens, an empty answer, a worker that
  takes time, a JSON-mode answer for `/v1`, which asks MLX and llama.cpp
  without a callback);
* the world is `conftest.py`'s `app_state`, `session_manager`, `server_state`,
  `memory_helper` and `make_request`;
* `/v1` goes through the REAL forwarders (`_forward_to_mlx`,
  `_forward_to_llama_cpp`, `_forward_to_ollama`). The first two read
  `app.state.modules`, so the same fakes serve both doors. `_forward_to_ollama`
  talks to the daemon over `httpx` and never touches the Ollama module, so a
  second fake stands behind it: `FakeOllamaDaemon`, the daemon's own wire
  (`/api/tags`, `/api/chat`, one JSON line per chunk), configured with the same
  mode as the module the web door sees.

What a client sees is read off the real route handlers — `chat_completions`
for `/v1` and the `/chat` handler `register_chat_routes` installs for the web
UI (`/ui/chat`) — so the status code, the headers, the stream and what is on
disk are the doors', not a re-statement of them.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from fastapi.responses import StreamingResponse

from core.turn.errors import BadRequest, ModelNotFound
from plugins.ollama_module.core.errors import ModelNotFoundError, OllamaSemanticError
from plugins.web_ui_module.api.wire import _stream_error_notice

from .conftest import door_patches, make_request
from .test_1117_cascade_keeps_the_notice import OOM, _MlxShaped, _OllamaShaped

#: The real client, captured before any patch: the `/v1` patch below replaces `httpx.AsyncClient`
#: on the shared `httpx` module, and the API engine's own client (it is given a `transport`, the
#: lab's way of putting a fake provider behind it) must keep being a real one.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

ENGINES = ("mlx", "llama_cpp", "ollama")
MODULE_KEY = {"mlx": "mlx_module", "llama_cpp": "llama_cpp_module", "ollama": "ollama_module"}

#: The door names, in the order the tables print them.
DOORS = ("v1_json", "v1_stream", "ui_json", "ui_stream")

#: The model name a fallback answers with when it is MLX / llama.cpp (#1035).
MLX_MODEL = "Qwen3.5-4B-MLX-4bit"
LLAMA_MODEL = "Qwen3-30B-A3B-Q4_K_M.gguf"


def says(engine: str) -> tuple[str, str]:
    """What a healthy `engine` answers, in two chunks: «Hola de mlx.»."""
    return ("Hola ", f"de {engine}.")


def _http_status_error(code: int, text: str = "boom") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    return httpx.HTTPStatusError(text, request=request, response=httpx.Response(code, request=request))


#: The exception each failure mode raises, per engine shape. In-process engines
#: raise plain Python errors from `chat()`; the Ollama module raises what its
#: HTTP client raises. These are the real exception classes, because the
#: cascade policy (`engine_error_to_http`) keys on the class.
def failure_for(engine: str, mode: str) -> Optional[Exception]:
    if mode in ("pre_byte", "mid_stream", "gone"):
        return (_http_status_error(500, "500 Internal Server Error") if engine == "ollama"
                else RuntimeError("worker died"))
    if mode == "oom":
        return _http_status_error(500, "model requires more system memory") if engine == "ollama" else OOM
    if mode == "bad_request":
        if engine == "ollama":
            # The module turns the daemon's 400 into its semantic error, a plain
            # Exception: the cascade policy retries it (a ValueError would be final).
            return OllamaSemanticError("bad request: this engine cannot take it", 400)
        return BadRequest("bad request: this engine cannot take it")
    if mode == "not_found" and engine == "ollama":
        return ModelNotFoundError("model-que-no-existeix")
    if mode == "unauthorized" and engine == "ollama":  # Ollama behind a proxy that wants a key
        return _http_status_error(401, "Client error '401 Unauthorized' for url 'http://127.0.0.1:11434/api/chat'")
    if mode == "unreachable":
        return httpx.ConnectError("connection refused") if engine == "ollama" else ConnectionError("refused")
    if mode == "timeout":
        return httpx.ReadTimeout("timed out") if engine == "ollama" else TimeoutError("took too long")
    return None


#: What the lab's in-process engines say a call cost (pla-tokens-reals).
PROMPT_TOKENS, CACHED_TOKENS = 7, 3


class InProc(_MlxShaped):
    """MLX / llama.cpp as the doors see them.

    `_MlxShaped` (test_1117) streams through the callback and loads its weights
    inside `chat`. This widens it with what the matrix needs: the name it
    answers under, a failure `after` N tokens, `delay` before it acts (so a
    client that leaves is noticed first), and the JSON-mode shape `/v1` asks —
    no callback, the answer in the result dict.
    """

    def __init__(self, name: str, *, fail: Exception | None = None, after: int | None = None,
                 tokens=None, loaded: bool = True, delay: float = 0.0, model: str | None = None,
                 sees: bool | None = None, switch_refuses: bool = False):
        model = model or (MLX_MODEL if name == "mlx" else LLAMA_MODEL)
        super().__init__(fail=fail, loaded=loaded, delay=delay,
                         tokens=says(name) if tokens is None else tokens, model_path=f"/models/{model}")
        self.name = name
        self.after = after
        self.sees = sees
        self.prompts: list[list] = []  # what each call was given, for the rows that measure it
        self.log: list | None = None  # the world's chronological call log, wired by `World`
        self.switch_refuses = switch_refuses

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls.append(kwargs)
        self.prompts.append(messages)
        if self.log is not None:
            self.log.append(self.name)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None and self.after is None:
            raise self.fail
        self.loaded = True
        cancel = kwargs.get("cancel_event")
        # The real MLX loop: the first token is out before the loop checks its cancel
        # event, and every later one is checked first (`generate_helpers`). An engine
        # handed an event that is already set answers one token and stops.
        stopped = lambda number: number > 0 and cancel is not None and cancel.is_set()  # noqa: E731
        if stream_callback is None:  # /v1, non-streaming: the answer is in the result
            if self.fail is not None:
                raise self.fail
            said = []
            for number, token in enumerate(self.tokens):
                if stopped(number):
                    break
                said.append(token)
            return {"response": "".join(said), "finish_reason": "stop", "tokens": len(said),
                    "prompt_tokens": PROMPT_TOKENS}
        for number, token in enumerate(self.tokens):
            if stopped(number):
                break
            if self.after is not None and number == self.after:
                raise self.fail
            stream_callback(token)
        if self.after is not None and self.after >= len(self.tokens):
            raise self.fail
        # What a real engine's result carries (MLX also says what its cache reused).
        return {"finish_reason": "stop", "prompt_tokens": PROMPT_TOKENS, "tokens": len(self.tokens),
                **({"cached_tokens": CACHED_TOKENS} if self.name == "mlx" else {})}

    def can_see_images(self) -> bool:
        return bool(self.sees)

    def switch_model_by_path(self, local_path) -> bool:
        if self.switch_refuses:
            raise ModelNotFound(f"Model '{local_path}' not found: no such model")
        return super().switch_model_by_path(local_path)


class OllamaModule(_OllamaShaped):
    """The Ollama module as the web door sees it: `chat(model, …)` returns a
    generator whose first read is the request (test_1117's `_OllamaShaped`),
    widened with a failure after N tokens and a delay."""

    def __init__(self, *, exc: Exception | None = None, after: int | None = None, tokens=None,
                 loaded: bool = True, delay: float = 0.0, sees: bool | None = None):
        super().__init__(exc=exc, tokens=says("ollama") if tokens is None else tokens, loaded=loaded)
        self.after = after
        self.delay = delay
        self.models: list[str] = []
        self.kwargs: list[dict] = []
        self.sees = sees
        self.name = "ollama"
        self.log: list | None = None

    def chat(self, model, messages, stream=False, continue_final=False, **kwargs):
        # `continue_final` is declared like the real `OllamaChat.chat` declares
        # it: `start_engine_call` decides whether to pass the flag off the
        # signature, so a fake without it could never be asked to resume.
        self.calls += 1
        if self.log is not None:
            self.log.append(self.name)
        self.models.append(model)
        self.kwargs.append({"stream": stream, **({"continue_final": True} if continue_final else {}), **kwargs})
        owner = self

        async def _gen():
            if owner.delay:
                await asyncio.sleep(owner.delay)
            if owner.exc is not None and owner.after is None:
                raise owner.exc
            for number, token in enumerate(owner.tokens):
                if owner.after is not None and number == owner.after:
                    raise owner.exc
                yield {"message": {"content": token}}  # Ollama's /api/chat shape
            if owner.after is not None and owner.after >= len(owner.tokens):
                raise owner.exc
            # the real module closes with the daemon's `done` chunk, marked `continuable`
            yield {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                   "continuable": False, "prompt_eval_count": PROMPT_TOKENS, "eval_count": len(owner.tokens)}

        return _gen()

    def __getattr__(self, name):
        # `can_see_images` exists only when a test says so: the real Ollama
        # module does not declare it (`engine_can_see_images` answers None).
        if name == "can_see_images" and self.sees is not None:
            return lambda: self.sees
        raise AttributeError(name)


# --------------------------------------------------------------------- daemon

class _Response:
    def __init__(self, status: int, lines=(), body: dict | None = None, mid: Exception | None = None):
        self.status_code = status
        self._lines = lines
        self._body = body if body is not None else {}
        self._mid = mid

    def json(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line
        if self._mid is not None:
            raise self._mid


class _Stream:
    def __init__(self, daemon: "FakeOllamaDaemon"):
        self._daemon = daemon

    async def __aenter__(self):
        return await self._daemon.respond()

    async def __aexit__(self, *_exc):
        return False


class _Client:
    def __init__(self, daemon: "FakeOllamaDaemon", **_kwargs):
        self._daemon = daemon

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, **_kwargs):
        self._daemon.requests.append(("GET", url))
        if self._daemon.down:
            raise httpx.ConnectError("connection refused")
        names = [{"name": name} for name in self._daemon.models]
        return _Response(200, body={"models": names})

    async def post(self, url, json=None, **_kwargs):
        self._daemon.requests.append(("POST", url))
        self._daemon.payloads.append(json)
        return await self._daemon.respond(blocking=True)

    def stream(self, method, url, json=None, **_kwargs):
        self._daemon.requests.append((method, url))
        self._daemon.payloads.append(json)
        return _Stream(self._daemon)


class FakeOllamaDaemon:
    """What `_forward_to_ollama` talks to: the daemon's HTTP, not the module.

    `mode` is the same vocabulary the matrix uses for the module: `ok`,
    `pre_byte` (a 500 before the first line), `oom` (500 with the daemon's
    own text), `bad_request` (400), `unreachable` (connection refused),
    `timeout` (the read times out), `mid_stream` (a line, then the socket
    dies), `empty` (done with no content), `not_found` (the model is not in
    `/api/tags`).
    """

    def __init__(self, mode: str = "ok", *, models=("llama3.2:3b",), delay: float = 0.0):
        self.mode = mode
        self.models = list(models)
        self.delay = delay
        self.requests: list[tuple[str, str]] = []
        self.payloads: list[dict] = []
        self.down = mode == "unreachable"
        self.log: list | None = None  # the world's chronological call log, wired by `World`

    def client(self, **kwargs):
        if kwargs.get("transport") is not None:  # not the Ollama forwarder: the API engine, with its fake provider
            return _REAL_ASYNC_CLIENT(**kwargs)
        return _Client(self, **kwargs)

    async def respond(self, blocking: bool = False) -> _Response:
        if self.log is not None:
            self.log.append("ollama")
        if self.delay:
            await asyncio.sleep(self.delay)
        mode = self.mode
        if mode in ("pre_byte", "oom", "gone"):
            text = "model requires more system memory" if mode == "oom" else "internal error"
            return _Response(500, body={"error": text})
        if mode == "bad_request":
            return _Response(400, body={"error": "bad request"})
        if mode == "unauthorized":  # Ollama behind a proxy that wants a key
            return _Response(401, body={"error": "unauthorized"})
        if mode == "timeout":
            raise httpx.ReadTimeout("timed out")
        first, second = says("ollama")
        if mode == "empty":
            lines = [json.dumps({"message": {"content": ""}, "done": True})]
            return _Response(200, lines, self._whole(""))
        if blocking:
            if mode == "mid_stream":
                raise httpx.ReadError("socket closed")
            return _Response(200, body=self._whole(first + second))
        lines = [json.dumps({"message": {"role": "assistant", "content": first}, "done": False})]
        if mode == "mid_stream":
            return _Response(200, lines, mid=httpx.ReadError("socket closed"))
        lines.append(json.dumps({"message": {"role": "assistant", "content": second}, "done": True}))
        return _Response(200, lines)

    @staticmethod
    def _whole(text: str) -> dict:
        return {"model": "llama3.2:3b", "created_at": "t", "message": {"role": "assistant", "content": text},
                "done": True, "done_reason": "stop", "prompt_eval_count": 3, "eval_count": 2}


# ---------------------------------------------------------------------- world

@dataclass
class World:
    """The engines a scenario registers and the daemon behind Ollama's `/v1`.

    `log` is the order the engines were asked to generate, one entry per call,
    whichever door asked: the fakes and the daemon write to it."""
    modules: dict
    daemon: FakeOllamaDaemon
    engines: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    def __post_init__(self) -> None:
        for engine in self.engines.values():
            engine.log = self.log
        self.daemon.log = self.log

    def asked(self) -> tuple:
        """The engines asked to generate, in the order they were, once per call."""
        return tuple(self.log)


def build_engine(engine: str, mode: str = "ok", *, delay: float = 0.0, **extra):
    """One engine in the shape of its real module, failing as `mode` says.

    `loading` is a healthy engine whose model is not in memory yet; `empty`
    answers with no text; `mid_stream` fails after its first token; `gone` is
    a worker that fails after `delay`, with the client already away.
    """
    exc = failure_for(engine, mode)
    after = 1 if mode == "mid_stream" else None
    tokens = ("",) if mode == "empty" else None
    loaded = mode != "loading"
    if engine == "ollama":
        return OllamaModule(exc=exc, after=after, tokens=tokens, loaded=loaded, delay=delay, **extra)
    return InProc(engine, fail=exc, after=after, tokens=tokens, loaded=loaded, delay=delay,
                  switch_refuses=mode == "not_found", **extra)


def build_world(faults: dict[str, str] | None = None, *, delay: float = 0.0, live=ENGINES,
                **extra_by_engine) -> World:
    """Register `live` engines; `faults` says how each fails (default: healthy).

    The Ollama module (web door) and the Ollama daemon (`/v1` door) are given
    the same mode, so both doors see the same event.
    """
    faults = faults or {}
    modules, engines = {}, {}
    for name in live:
        engine = build_engine(name, faults.get(name, "ok"), delay=delay, **extra_by_engine.get(name, {}))
        engines[name] = engine
        modules[MODULE_KEY[name]] = engine
    daemon_mode = faults.get("ollama", "ok")
    daemon = FakeOllamaDaemon("not_found" if daemon_mode == "not_found" else daemon_mode,
                              models=("other-model:1b",) if daemon_mode == "not_found" else ("llama3.2:3b",),
                              delay=delay if daemon_mode != "ok" else 0.0)
    return World(modules=modules, daemon=daemon, engines=engines)


# ----------------------------------------------------------------- observation

_SENTINEL = re.compile(r"\x00\[([A-Z_]+)(?::([^\]]*))?\]\x00")


def _notice_kinds() -> dict[str, set[str]]:
    langs = ("ca", "es", "en")
    return {
        "oom": {_stream_error_notice(OOM, lang) for lang in langs},
        "error": {_stream_error_notice(RuntimeError("x"), lang) for lang in langs},
    }


def _known_notice(text: str) -> Optional[str]:
    for kind, notices in _notice_kinds().items():
        if any(notice.strip() in text for notice in notices):
            return kind
    return None


def _answered(text: str) -> Optional[str]:
    """The engine whose healthy text («de mlx.») is in `text`, if any."""
    found = [engine for engine in ENGINES if f"de {engine}." in text]
    return found[0] if len(found) == 1 else (None if not found else "+".join(found))


@dataclass
class Seen:
    """What one door showed the client, and what it kept.

    `status` is the HTTP code of the answer (200 when a body came back, the
    `HTTPException` code when the door refused, 500 for an error nobody
    wrote an answer for). `cut` is the exception that tore an already-open
    stream down (the client sees a dropped connection, not an answer).
    """
    status: int = 200
    detail: Optional[str] = None
    unhandled: Optional[str] = None
    cut: Optional[str] = None
    text: str = ""
    answered: Optional[str] = None
    notice: Optional[str] = None
    saved: bool = False
    saved_text: str = ""
    engine_tags: tuple = ()
    model_tags: tuple = ()
    usage_tags: tuple = ()  # `[USAGE:in|out|cached]`, the footer's count (pla-tokens-reals D)
    loading: int = 0
    headers: dict = field(default_factory=dict)
    fallback: Optional[tuple] = None
    finish: Optional[str] = None
    wire: Any = None
    saved_stats: dict = field(default_factory=dict)
    ctx: Any = None
    asked: tuple = ()
    #: The headers a JSON answer carried (the response object the route was handed).
    json_headers: dict = field(default_factory=dict)

    def sig(self) -> str:
        """One line: what the matrix compares, in the order a client meets it —
        the code, how the stream ended, who answered, what the chat shows, what
        was kept, and the wire's own labels (`[ENGINE:]`, `[MODEL:]`, the
        loading banner, `X-Nexe-Fallback-*`)."""
        return " ".join([str(self.status), *self._ending(), *self._kept(), *self._labels()])

    def _ending(self) -> list[str]:
        """How the turn ended and what the chat shows."""
        bits = []
        if self.unhandled:
            bits.append(f"unhandled={self.unhandled}")
        if self.cut:
            bits.append(f"cut={self.cut}")
        if self.answered:
            bits.append(f"by={self.answered}")
        if self.notice:
            bits.append(f"notice={self.notice}")
        if self.finish:
            bits.append(f"finish={self.finish}")
        if self.status == 200 and not self.text.strip():
            bits.append("empty")
        elif self.text.startswith("Error:"):
            bits.append("shown=internal-error")
        return bits

    def _kept(self) -> list[str]:
        return ["saved" if self.saved else "not-saved"]

    def _labels(self) -> list[str]:
        """The wire's labels and which engines were asked."""
        bits = []
        if self.engine_tags:
            bits.append("E=" + ">".join(self.engine_tags))
        if self.model_tags:
            bits.append("M=" + ">".join(self.model_tags))
        if self.loading:
            bits.append(f"loading={self.loading}")
        if self.fallback and self.fallback[0]:
            bits.append("fb=" + "/".join(self.fallback))
        if self.asked:
            bits.append("asked=" + ">".join(self.asked))
        return bits


def _read_saved(session_manager, sid: str) -> tuple[bool, str, dict]:
    """Is an assistant message on disk for this conversation, its text, and its stats."""
    found, text, stats = False, "", {}
    for path in sorted(session_manager._storage_path.glob(f"{sid}*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for message in data.get("messages", []):
            if message.get("role") == "assistant":
                found, text, stats = True, message.get("content") or "", message.get("stats") or {}
    return found, text, stats


def _sse_text(chunks: list) -> tuple[str, Optional[str]]:
    """The answer a /v1 stream carried, and its last finish_reason."""
    out, finish = [], None
    for chunk in chunks:
        raw = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in raw.splitlines():
            if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                continue
            try:
                data = json.loads(line[6:])
            except ValueError:
                continue
            for choice in data.get("choices") or []:
                out.append((choice.get("delta") or {}).get("content") or "")
                finish = choice.get("finish_reason") or finish
    return "".join(out), finish


#: C5 part C: a client that STOPS reading after this many chunks (and closes the
#: stream, as the server does when the connection drops). None reads it all.
STOP_AFTER: dict = {"chunks": None}


async def _drain(response: StreamingResponse, seen: Seen) -> list:
    chunks: list = []
    try:
        async for chunk in response.body_iterator:
            chunks.append(chunk)
            if STOP_AFTER["chunks"] is not None and len(chunks) >= STOP_AFTER["chunks"]:
                await response.body_iterator.aclose()
                break
    except HTTPException as exc:
        seen.cut = f"HTTPException({exc.status_code})"
    except Exception as exc:
        seen.cut = type(exc).__name__
    return chunks


def _read_labels(raw: str, seen: Seen) -> None:
    """The web alphabet's labels in `raw` — `[ENGINE:]`, `[MODEL:]`, the loading
    banner. Looked for at every door: `/v1` must not carry them, and a claim that
    it does not is only worth something if the wire was read for them. (A NUL
    inside a JSON string is written `\\u0000`.)"""
    tags = [(m.group(1), m.group(2)) for m in _SENTINEL.finditer(raw.replace("\\u0000", "\x00"))]
    seen.engine_tags = tuple(v for k, v in tags if k == "ENGINE")
    seen.model_tags = tuple(v for k, v in tags if k == "MODEL")
    seen.usage_tags = tuple(v for k, v in tags if k == "USAGE")
    seen.loading = sum(1 for k, _v in tags if k == "MODEL_LOADING")


def _read_web_stream(chunks: list, seen: Seen) -> None:
    joined = "".join(c.decode() if isinstance(c, bytes) else c for c in chunks)
    _read_labels(joined, seen)
    seen.text = _SENTINEL.sub("", joined)
    seen.notice = _known_notice(seen.text)
    seen.answered = _answered(seen.text)


def _spy_on_turn(module: str, seen: Seen):
    """Remember the `TurnContext` of the turn the route walks, to read what the
    route does not return (the usage record, the cancel token). A spy, not a
    stand-in: it calls the real `run_turn` / `stream_turn` with what it got."""
    import contextlib

    import core.turn.run as turn_run

    real_run, real_stream = turn_run.run_turn, turn_run.stream_turn

    async def run_turn(ctx, *args, **kwargs):
        seen.ctx = ctx
        return await real_run(ctx, *args, **kwargs)

    async def stream_turn(ctx, *args, **kwargs):
        seen.ctx = ctx
        return await real_stream(ctx, *args, **kwargs)

    @contextlib.contextmanager
    def spy():
        with patch(f"{module}.run_turn", new=run_turn), patch(f"{module}.stream_turn", new=stream_turn):
            yield

    return spy()


async def _answer_of(call, seen: Seen, *, keep_message: bool = False):
    """What the route handler gave back, or the way it refused: an
    `HTTPException` is an answer with a code; anything else is what the
    framework turns into a bare 500."""
    try:
        return await call
    except HTTPException as exc:
        seen.status, seen.detail = exc.status_code, str(exc.detail)
    except Exception as exc:
        seen.status, seen.unhandled = 500, type(exc).__name__
        seen.detail = str(exc) if keep_message else None
    return None


def _read_web_json(response: dict, seen: Seen) -> None:
    seen.wire = response
    nexe = response.get("nexe_fallback") or {}
    seen.fallback = (nexe.get("from"), nexe.get("reason"))
    _read_labels(json.dumps(response, ensure_ascii=False), seen)
    seen.text = response.get("response", "")
    seen.notice = _known_notice(seen.text)
    seen.answered = _answered(seen.text)


async def _run_ui(lab, world: World, *, stream: bool, backend: str, sid: str, message: str,
                  extra: dict | None, gone: bool) -> Seen:
    from plugins.web_ui_module.api.routes_chat import register_chat_routes

    lab.app_state.modules = world.modules
    router = APIRouter()
    register_chat_routes(router, session_mgr=lab.session_manager, require_ui_auth=lambda: None)
    endpoint = next(r.endpoint for r in router.routes if r.path.endswith("/chat"))
    body = {"message": message, "session_id": sid, "stream": stream, "backend": backend}
    body.update(extra or {})
    request = make_request(lab.app_state)
    request.is_disconnected = AsyncMock(return_value=gone)  # the bare request has no receive channel
    seen = Seen()
    with door_patches(lab.server_state, lab.memory_helper), \
         _spy_on_turn("plugins.web_ui_module.api.routes_chat", seen):
        sink = Response()
        response = await _answer_of(endpoint(request, body, None, sink), seen)
        seen.json_headers = dict(sink.headers)
        if isinstance(response, StreamingResponse):
            _read_web_stream(await _drain(response, seen), seen)
            seen.headers = dict(response.headers)
            seen.fallback = (seen.headers.get("x-nexe-fallback-from"), seen.headers.get("x-nexe-fallback-reason"))
        elif response is not None:
            _read_web_json(response, seen)
    seen.saved, seen.saved_text, seen.saved_stats = _read_saved(lab.session_manager, sid)
    seen.asked = world.asked()
    return seen


def _v1_patches(lab, world: World):
    """`door_patches`'s four stand-ins without the `_forward_to_ollama` one: the
    real forwarders run, and the Ollama one talks to the fake daemon."""
    import contextlib

    from core.endpoints.chat_engines import ollama as ollama_forwarder

    async def _no_rag(*_args, **_kwargs):
        return "", []

    @contextlib.contextmanager
    def patches():
        # The daemon's model list is cached for 30 s at module level: a fresh
        # (empty) one for this turn, and the cache as it was when the turn ends.
        with patch.dict(ollama_forwarder._ollama_tags_cache, {"models": None, "ts": 0.0}), \
             patch("core.lifespan.get_server_state", return_value=lab.server_state), \
             patch("core.memory_facts.helper_for", return_value=lab.memory_helper), \
             patch("core.endpoints.chat_rag.build_rag_context", new=_no_rag), \
             patch("core.endpoints.chat.build_rag_context", new=_no_rag), \
             patch("core.endpoints.chat_engines.ollama.httpx.AsyncClient", new=world.daemon.client):
            yield

    return patches()


async def _read_v1_stream(response: StreamingResponse, seen: Seen) -> None:
    chunks = await _drain(response, seen)
    seen.text, seen.finish = _sse_text(chunks)
    _read_labels("".join(c.decode() if isinstance(c, bytes) else c for c in chunks), seen)
    seen.headers = dict(response.headers)
    seen.fallback = (seen.headers.get("x-nexe-fallback-from"), seen.headers.get("x-nexe-fallback-reason"))
    seen.answered = seen.headers.get("x-nexe-engine") if seen.text else None
    seen.wire = chunks


def _read_v1_json(response: dict, seen: Seen) -> None:
    seen.wire = response
    _read_labels(json.dumps(response, ensure_ascii=False), seen)
    seen.text = ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    nexe = response.get("nexe_fallback") or {}
    seen.fallback = (nexe.get("from"), nexe.get("reason")) if nexe else (None, None)
    seen.answered = response.get("nexe_engine") if seen.text else None


async def _run_v1(lab, world: World, *, stream: bool, engine: str, sid: str, message: str,
                  extra: dict | None, gone: bool, messages=None) -> Seen:
    from core.endpoints.chat import chat_completions
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message

    lab.app_state.modules = world.modules
    msgs = ([Message(**m) if isinstance(m, dict) else m for m in messages] if messages
            else [Message(role="user", content=message)])
    body = ChatCompletionRequest(messages=msgs, use_rag=True, stream=stream, engine=engine, **(extra or {}))
    request = make_request(lab.app_state)
    request.scope["headers"] = [(b"x-api-key", b"test-key"), (b"x-session-id", sid.encode())]
    request.is_disconnected = AsyncMock(return_value=gone)  # the bare request has no receive channel
    tasks = BackgroundTasks()
    seen = Seen()
    with _v1_patches(lab, world), _spy_on_turn("core.endpoints.chat", seen):
        sink = Response()
        response = await _answer_of(chat_completions(body, request, tasks, sink), seen, keep_message=True)
        seen.json_headers = dict(sink.headers)
        if isinstance(response, StreamingResponse):
            await _read_v1_stream(response, seen)
        elif response is not None:
            _read_v1_json(response, seen)
        for task in tasks.tasks:  # FastAPI runs them after the body
            await task()
    seen.saved, seen.saved_text, seen.saved_stats = _read_saved(lab.session_manager, sid)
    seen.notice = _known_notice(seen.text)
    seen.asked = world.asked()
    return seen


async def run_door(lab, world: World, door: str, *, backend: str = "mlx", sid: str = "p0",
                   message: str = "hola", extra: dict | None = None, gone: bool = False,
                   messages=None) -> Seen:
    """One real turn through one real door, and what the client saw."""
    stream = door.endswith("stream")
    if door.startswith("v1"):
        return await _run_v1(lab, world, stream=stream, engine=backend, sid=sid, message=message,
                             extra=extra, gone=gone, messages=messages)
    return await _run_ui(lab, world, stream=stream, backend=backend, sid=sid, message=message,
                         extra=extra, gone=gone)
