"""#1035: a fallback engine answers with the model it has loaded.

The web UI always sends the model selected in its dropdown (nexe-chat.js puts
`model` in every chat body, a Continue's included), and a model name belongs to
one engine: an MLX directory is not a .gguf, and neither is an Ollama tag.
The web doors used to ask the next engine in the cascade to load that name;
its validation raised ValueError("not found"), final for the cascade policy,
so from the browser no fallback ever answered — the cascade of 693df545 and
the notice of #1117 only ever showed the first engine's error. `/v1` already
ran a fallback with its loaded model.

Every engine here has a real one's shape (see test_1117_…): MLX's `_node.config`
names the model it runs, which is what `resolve_loaded_model_name` reads, and
its `switch_model_by_path` refuses a name that is not an MLX directory the way
the real one does (FD-S4), and `can_see_images` says whether that model is a
VLM. A fallback that answers with its own model must be able to see the turn's
image, or a text model would answer as if it saw it.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from plugins.ollama_module.core.errors import ModelNotFoundError
from plugins.web_ui_module.api.wire import _stream_error_notice

from .test_continue_is_a_turn import _cut_session

SERVED = "Qwen3.5-4B-MLX-4bit"
IMAGE = "aGVsbG8="


class _Mlx:
    """MLX: tokens through the callback, the model it runs in its node's
    config, and a switch that only takes an MLX directory."""

    def __init__(self, *, model_path=f"/models/{SERVED}", fail: Exception | None = None, sees=False):
        self.fail = fail
        self.sees = sees
        self.calls: list[dict] = []
        self.switched_to = None
        self._node = SimpleNamespace(config=SimpleNamespace(model_path=model_path))

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        for token in ("ada", " i acabada."):
            stream_callback(token)
        return {"finish_reason": "stop"}

    async def is_model_loaded(self, model_name=""):
        return True

    def can_continue(self, model_name=None):
        return True

    def can_see_images(self) -> bool:
        return self.sees

    def switch_model_by_path(self, local_path) -> bool:
        self.switched_to = Path(local_path).name
        if not Path(local_path).name.endswith("-MLX-4bit"):
            raise ValueError(f"Model '{Path(local_path).name}' not found: no MLX model (config.json)")
        return True


class _Llama(_Mlx):
    """llama.cpp: an image already on the cut turn cannot be resumed here."""

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        if kwargs.get("continue_final") and kwargs.get("images"):
            self.calls.append(kwargs)
            raise RuntimeError("continue with images is not supported by llama.cpp")
        return await super().chat(messages, system, session_id, stream_callback, **kwargs)

    def switch_model_by_path(self, local_path) -> bool:
        self.switched_to = Path(local_path).name
        if not Path(local_path).name.endswith(".gguf"):
            raise ValueError(f"Model '{Path(local_path).name}' not found: not a GGUF file")
        return True


class _Ollama:
    """`chat(model, …)` returns a generator; the first read is the request."""

    def __init__(self, exc: Exception | None = None):
        self.exc = exc
        self.models: list[str] = []

    async def is_model_loaded(self, model_name: str) -> bool:
        return True

    def chat(self, model, messages, stream=False, **kwargs):
        self.models.append(model)
        exc = self.exc

        async def _gen():
            if exc is not None:
                raise exc
            yield "des d'ollama"

        return _gen()


def _models(ctx) -> list:
    """Every `[MODEL:]` token on the wire, in order."""
    return [c[len("\x00[MODEL:"):-2] for c in ctx.lab_wire_chunks
            if isinstance(c, str) and c.startswith("\x00[MODEL:")]


def _visible(ctx) -> str:
    return "".join(c for c in ctx.lab_wire_chunks if isinstance(c, str) and not c.startswith("\x00"))


def _last_assistant(session_manager, sid) -> dict:
    stored = json.loads((Path(session_manager._storage_path) / f"{sid}.json").read_text(encoding="utf-8"))
    return [m for m in stored["messages"] if m["role"] == "assistant"][-1]


async def test_an_image_continue_from_the_browser_is_answered_by_mlx(turn_lab, session_manager, app_state):
    """(f) of the manual test, with the body the browser sends: the Continue
    carries the GGUF that was selected for llama.cpp."""
    llama = _Llama(model_path="/models/Qwen3-30B-A3B-Q4_K_M.gguf")
    mlx = _Mlx(sees=True)
    app_state.modules = {"llama_cpp_module": llama, "mlx_module": mlx}
    _cut_session(session_manager, "r1035-f", image="aGVsbG8=")
    ctx = await turn_lab.ui(
        streaming=True, session_id="r1035-f", message="",
        body_extra={"continue": True, "backend": "llama_cpp", "model": "Qwen3-30B-A3B-Q4_K_M.gguf"},
    )
    assert llama.calls and mlx.calls
    assert mlx.calls[0].get("continue_final") is True
    assert mlx.switched_to is None, "a fallback was asked to load another engine's model"
    assert "ada" in _visible(ctx)
    assert _stream_error_notice(RuntimeError("x"), ctx.lang).strip() not in _visible(ctx)
    call = ctx.usage["llm"]["calls"][-1]
    assert (call["engine"], call["model"]) == ("mlx", SERVED)


async def test_a_missing_ollama_model_from_the_browser_is_answered_by_mlx(turn_lab, session_manager, app_state):
    """(h) of the manual test: the stream, and what is stored names the model
    that answered."""
    mlx = _Mlx()
    app_state.modules = {"ollama_module": _Ollama(ModelNotFoundError("model-que-no-existeix-c4")),
                         "mlx_module": mlx}
    ctx = await turn_lab.ui(streaming=True, session_id="r1035-h", message="hola",
                            body_extra={"backend": "ollama", "model": "model-que-no-existeix-c4"})
    assert mlx.calls and mlx.switched_to is None
    assert "ada" in _visible(ctx)
    assert ctx.outcomes["generate"] == "ok"
    assert ctx.usage["llm"]["calls"][-1]["model"] == SERVED
    assert _last_assistant(session_manager, "r1035-h")["stats"]["model"] == SERVED
    # The client keeps the last `[MODEL:]`: the footer names who answered,
    # live and on reload (`stats.model`) alike.
    assert _models(ctx) == ["model-que-no-existeix-c4", SERVED]


class _GptOssMlx(_Mlx):
    """MLX running gpt-oss: its text comes in harmony channels, which the
    turn's parser only folds into `<think>` when it knows the model's name."""

    async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
        self.calls.append(kwargs)
        for token in ("<|channel|>analysis<|message|>pensant", "<|end|>",
                      "<|start|>assistant<|channel|>final<|message|>", "ada"):
            stream_callback(token)
        return {"finish_reason": "stop"}


async def test_the_fallbacks_text_is_read_as_its_own_models(turn_lab, app_state):
    """The parser that splits the reasoning from the answer depends on the
    model's name (gpt-oss speaks harmony): it gets the fallback's, not the
    name picked for the engine that failed."""
    app_state.modules = {"ollama_module": _Ollama(ModelNotFoundError("qwen3.5:4b")),
                         "mlx_module": _GptOssMlx(model_path="/models/gpt-oss-20b-MLX-4bit")}
    ctx = await turn_lab.ui(streaming=True, session_id="r1035-harmony", message="hola",
                            body_extra={"backend": "ollama", "model": "qwen3.5:4b"})
    # Read under the name picked for Ollama, the channels leak into the
    # bubble as "analysispensantassistantfinalada" (B027a).
    assert _visible(ctx).strip() == "ada"


async def test_the_json_door_falls_back_the_same_way(turn_lab, session_manager, app_state):
    mlx = _Mlx()
    app_state.modules = {"ollama_module": _Ollama(ModelNotFoundError("model-que-no-existeix-c4")),
                         "mlx_module": mlx}
    ctx = await turn_lab.ui(streaming=False, session_id="r1035-json", message="hola",
                            body_extra={"backend": "ollama", "model": "model-que-no-existeix-c4"})
    assert mlx.calls and mlx.switched_to is None
    assert "ada" in ctx.response
    assert ctx.usage["llm"]["calls"][-1]["model"] == SERVED
    assert _last_assistant(session_manager, "r1035-json")["stats"]["model"] == SERVED


async def test_the_engine_the_user_picked_still_gets_the_model_they_picked(turn_lab, app_state):
    """Only fallbacks keep their own model: the first engine is switched to
    the selection, and answers under that name."""
    mlx = _Mlx(model_path="/models/Gemma-3-4B-MLX-4bit")
    app_state.modules = {"mlx_module": mlx}
    ctx = await turn_lab.ui(streaming=True, session_id="r1035-first", message="hola",
                            body_extra={"backend": "mlx", "model": SERVED})
    assert mlx.switched_to == SERVED
    assert ctx.usage["llm"]["calls"][-1]["model"] == SERVED
    assert _models(ctx) == [SERVED], "no second label when the picked engine answers"


@pytest.mark.parametrize("image", [None, IMAGE])
async def test_ollama_as_a_fallback_is_still_asked_for_the_requested_name(turn_lab, app_state, image):
    """Ollama picks its model per request and has no single loaded one, so a
    fallback to it carries the requested name, as before (#1035 leaves which
    model it should run to the C4.8), and it says nothing about seeing: the
    image guard leaves it alone. Pinned so a change here is deliberate."""
    ollama = _Ollama()
    app_state.modules = {"mlx_module": _Mlx(fail=RuntimeError("worker died")), "ollama_module": ollama}
    body = {"backend": "mlx", "model": SERVED}
    if image:
        body.update(image_b64=image, image_type="image/png")
    await turn_lab.ui(streaming=True, session_id=f"r1035-ollama-{bool(image)}", message="hola", body_extra=body)
    # #1144: a turn with an image is followed by its description, asked of the
    # same engine and model that served (here inline: the lab runs no queue).
    assert ollama.models == ([SERVED, SERVED] if image else [SERVED])


# ── a fallback that cannot see the image does not answer about it ─────────


@pytest.mark.parametrize("streaming", [True, False])
async def test_a_text_model_on_a_fallback_is_not_given_an_image(turn_lab, app_state, caplog, streaming):
    """A fallback answers with its own model; a text one, handed a picture,
    would answer as if it saw it. It is skipped, and the first engine's
    failure is what the user gets."""
    down = ModelNotFoundError("gemma4:e4b")
    mlx = _Mlx(sees=False)
    app_state.modules = {"ollama_module": _Ollama(down), "mlx_module": mlx}
    body = {"backend": "ollama", "model": "gemma4:e4b", "image_b64": IMAGE, "image_type": "image/png"}
    with caplog.at_level(logging.WARNING, logger="plugins.web_ui_module.api.turn_adapters"):
        if streaming:
            ctx = await turn_lab.ui(streaming=True, session_id="r1035-blind-1", message="què hi veus?",
                                    body_extra=body)
            assert _stream_error_notice(down, ctx.lang) in ctx.lab_wire_chunks
            assert ctx.outcomes["generate"] == "degraded"
        else:
            # The JSON door's answer when no engine answers (a 503; which one
            # it should be is the C4.8's second decision).
            with pytest.raises(HTTPException) as raised:
                await turn_lab.ui(streaming=False, session_id="r1035-blind-0", message="què hi veus?",
                                  body_extra=body)
            assert raised.value.status_code == 503
    assert mlx.calls == []
    assert any("cannot see the image" in r.getMessage() for r in caplog.records)


async def test_a_vision_model_on_a_fallback_answers_the_image(turn_lab, app_state):
    mlx = _Mlx(sees=True)
    app_state.modules = {"ollama_module": _Ollama(ModelNotFoundError("gemma4:e4b")), "mlx_module": mlx}
    ctx = await turn_lab.ui(streaming=True, session_id="r1035-sees", message="què hi veus?",
                            body_extra={"backend": "ollama", "model": "gemma4:e4b",
                                        "image_b64": IMAGE, "image_type": "image/png"})
    assert mlx.calls and mlx.calls[0].get("images") == [IMAGE]
    assert "ada" in _visible(ctx)


async def test_an_image_continue_is_not_resumed_by_a_text_model(turn_lab, session_manager, app_state):
    """(f) with a text model loaded in MLX: describing from memory is what
    C4.6-a-vlm resumes WITH the image to avoid — llama.cpp's refusal stays."""
    llama = _Llama(model_path="/models/Qwen3-30B-A3B-Q4_K_M.gguf")
    mlx = _Mlx(sees=False)
    app_state.modules = {"llama_cpp_module": llama, "mlx_module": mlx}
    _cut_session(session_manager, "r1035-f-blind", image=IMAGE)
    ctx = await turn_lab.ui(
        streaming=True, session_id="r1035-f-blind", message="",
        body_extra={"continue": True, "backend": "llama_cpp", "model": "Qwen3-30B-A3B-Q4_K_M.gguf"},
    )
    assert mlx.calls == []
    assert ctx.outcomes["generate"] == "degraded"


# ── the engines say whether they see ──────────────────────────────────────


def test_mlx_sees_when_its_model_is_a_vlm(tmp_path):
    from plugins.mlx_module.module import MLXModule

    vlm, text = tmp_path / "vlm", tmp_path / "text"
    vlm.mkdir()
    text.mkdir()
    (vlm / "config.json").write_text(json.dumps({"architectures": ["Qwen3VLForConditionalGeneration"]}))
    (text / "config.json").write_text(json.dumps({"architectures": ["Qwen3ForCausalLM"]}))
    module = MLXModule.__new__(MLXModule)
    module._initialized = True
    module._node = SimpleNamespace(config=SimpleNamespace(model_path=str(vlm)))
    assert module.can_see_images() is True
    module._node.config.model_path = str(text)
    assert module.can_see_images() is False
    module._initialized = False
    module._node.config.model_path = str(vlm)
    assert module.can_see_images() is False


def test_llama_cpp_sees_with_a_projector():
    from plugins.llama_cpp_module.module import LlamaCppModule

    module = LlamaCppModule.__new__(LlamaCppModule)
    module._initialized = True
    module._node = SimpleNamespace(config=SimpleNamespace(mmproj_path="/models/mmproj.gguf"))
    assert module.can_see_images() is True
    module._node.config.mmproj_path = ""
    assert module.can_see_images() is False
    module._node = None
    assert module.can_see_images() is False


def test_an_engine_that_does_not_say_is_left_alone_and_one_that_breaks_says_no():
    from core.endpoints.chat_engines.routing import engine_can_see_images

    class _Breaks:
        def can_see_images(self):
            raise RuntimeError("config gone")

    assert engine_can_see_images(object()) is None
    assert engine_can_see_images(_Breaks()) is False


class _StartRefused(_Ollama):
    """An Ollama whose start fails as it is called (no generator yet), with
    an error worth the next engine."""

    def chat(self, model, messages, stream=False, **kwargs):
        self.models.append(model)
        raise RuntimeError("connection reset")


async def test_a_fallbacks_failure_replayed_as_the_notice_sends_no_second_label(turn_lab, app_state):
    """No engine answered: the notice is a fallback's failure (the first one
    that failed on its first event), and the footer keeps the requested
    model — a second `[MODEL:]` would name a model that said nothing."""
    worker = RuntimeError("worker died")
    app_state.modules = {"ollama_module": _StartRefused(), "mlx_module": _Mlx(fail=worker)}
    ctx = await turn_lab.ui(streaming=True, session_id="r1035-replay", message="hola",
                            body_extra={"backend": "ollama", "model": "gemma4:e4b"})
    assert _stream_error_notice(worker, ctx.lang) in ctx.lab_wire_chunks
    assert _models(ctx) == ["gemma4:e4b"]


# ── /v1: the same rule for a fallback and an image ────────────────────────


def _v1_tries(images):
    import asyncio
    from unittest.mock import MagicMock, patch

    import core.endpoints.chat as chat_mod
    from core.endpoints.chat_schemas import ChatCompletionRequest, Message

    from tests.core.test_fd_block5_engine_routing import _Engine, _state

    mlx, llama = _Engine(), _Engine()
    # Text models both: the resolved engine is still asked (it decides what
    # to do with the image); only a fallback that cannot see is skipped.
    mlx.can_see_images = lambda: False
    llama.can_see_images = lambda: False  # a GGUF with no projector
    state = _state(mlx=mlx, llama_cpp=llama, ollama=_Engine())
    tried: list[str] = []

    async def _dispatch(engine, *a, **kw):
        tried.append(engine)
        if engine == "mlx":
            raise RuntimeError("model went bad")
        return {"ok": True}

    body = ChatCompletionRequest(messages=[Message(role="user", content="hola")], engine="mlx")
    request = MagicMock()
    request.app.state = state
    with patch.object(chat_mod, "_dispatch_to_engine", _dispatch):
        asyncio.run(chat_mod._dispatch_through_cascade(
            body, request, [], "hola", "sid", "mlx", None, images=images,
        ))
    return tried


def test_v1_skips_a_fallback_that_cannot_see_the_image():
    assert _v1_tries([IMAGE]) == ["mlx", "ollama"]


def test_v1_without_an_image_asks_the_same_fallback():
    assert _v1_tries(None) == ["mlx", "llama_cpp"]
