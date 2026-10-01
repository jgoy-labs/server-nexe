"""#1107: llama.cpp resumes a cut answer instead of starting a new one.

The installed llama-cpp-python closes every message and then opens a fresh
assistant turn. A continue renders that prefix *without* the cut answer and
appends the raw text, then calls `create_completion`. Dropping `continue_final`
sends the cut answer through `create_chat_completion`, which closes it.
"""
from __future__ import annotations

import pytest

PARTIAL = "tallem aquí"


def _node(**config):
    from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
    from plugins.llama_cpp_module.core.config import LlamaCppConfig

    node = LlamaCppChatNode.__new__(LlamaCppChatNode)
    node.config = LlamaCppConfig(model_path="/tmp/fake.gguf", **config)
    return node


class _Spy:
    def __init__(self, *, finish_reason="stop", prompt_tokens=10, completion_tokens=4, stream=False):
        self.chat_kwargs = None
        self.completion_kwargs = None
        self.finish_reason = finish_reason
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self._stream = stream

    def create_chat_completion(self, **kwargs):
        self.chat_kwargs = kwargs
        if kwargs.get("stream"):
            return iter([
                {"choices": [{"delta": {"content": "nou"}, "finish_reason": None}]},
                {"choices": [{"delta": {}, "finish_reason": self.finish_reason}],
                 "usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}},
            ])
        return {
            "choices": [{"message": {"content": "nou"}, "finish_reason": self.finish_reason}],
            "usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens},
        }

    def create_completion(self, **kwargs):
        self.completion_kwargs = kwargs
        if kwargs.get("stream"):
            return iter([
                {"choices": [{"text": " cua", "finish_reason": None}]},
                {"choices": [{"text": "", "finish_reason": self.finish_reason}],
                 "usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}},
            ])
        return {
            "choices": [{"text": " cua", "finish_reason": self.finish_reason}],
            "usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens},
        }


def _cut():
    return [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": PARTIAL},
    ]


def test_continue_final_ends_the_prompt_on_the_partial_and_does_not_close_it():
    node = _node()
    model = _Spy()
    node._generate(model, "sys", _cut(), continue_final=True)
    assert model.chat_kwargs is None
    prompt = model.completion_kwargs["prompt"]
    assert model.completion_kwargs["echo"] is False
    assert prompt.endswith("<|im_start|>assistant\n" + PARTIAL)
    after = prompt[prompt.rindex(PARTIAL):]
    assert "<|im_end|>" not in after
    assert "<|im_start|>assistant" not in after[len(PARTIAL):]


def test_dropping_continue_final_closes_the_turn_through_chat_completion():
    node = _node()
    model = _Spy()
    node._generate(model, "sys", _cut(), continue_final=False)
    assert model.completion_kwargs is None
    assert model.chat_kwargs is not None
    sent = model.chat_kwargs["messages"]
    assert sent[-1] == {"role": "assistant", "content": PARTIAL}


def test_a_streamed_continue_uses_create_completion_and_only_yields_the_tail():
    node = _node()
    model = _Spy(stream=True)
    seen = []
    result = node._generate_streaming(
        model, "sys", _cut(), seen.append, continue_final=True,
    )
    assert model.chat_kwargs is None
    assert model.completion_kwargs["stream"] is True
    assert model.completion_kwargs["prompt"].endswith(PARTIAL)
    assert seen == [" cua"]
    assert result["text"] == " cua"
    assert result["finish_reason"] == "stop"


def test_length_inside_the_window_is_continuable_and_a_full_window_is_not():
    from plugins.llama_cpp_module.core.chat import continuable_answer

    node = _node()  # n_ctx 8192, max_tokens 2048 → need used + 2560 < 8192
    assert continuable_answer(
        "length", 100, 4, n_ctx=node.config.n_ctx, reply_ceiling=node.config.max_tokens,
    ) is True
    assert continuable_answer(
        "length", 6000, 100, n_ctx=node.config.n_ctx, reply_ceiling=node.config.max_tokens,
    ) is False
    assert continuable_answer(
        "stop", 100, 4, n_ctx=node.config.n_ctx, reply_ceiling=node.config.max_tokens,
    ) is False


def test_a_cancelled_stream_does_not_report_length():
    node = _node()
    model = _Spy(stream=True, finish_reason="length")

    class _Cancel:
        def is_set(self):
            return True

    result = node._generate_streaming(
        model, "sys", [{"role": "user", "content": "hola"}], lambda _t: None,
        cancel_event=_Cancel(),
    )
    assert result["cancelled"] is True
    assert result["finish_reason"] is None


def test_unknown_chat_format_refuses_instead_of_closing_the_turn():
    node = _node(chat_format="phi-3")
    model = _Spy()
    with pytest.raises(RuntimeError, match="phi-3"):
        node._generate(model, "sys", _cut(), continue_final=True)
    assert model.chat_kwargs is None
    assert model.completion_kwargs is None


def test_images_on_a_continue_raise_before_either_generation():
    node = _node(mmproj_path="/tmp/clip.gguf")
    called = {"model": False}

    def _boom(*_a, **_k):
        called["model"] = True
        raise AssertionError("generation ran")

    node._get_model = lambda *_a, **_k: (called.__setitem__("model", True), False)[1] and None

    async def _run():
        with pytest.raises(RuntimeError, match="images"):
            await node.execute({
                "system": "sys",
                "messages": _cut(),
                "continue_final": True,
                "images": [b"\x89PNG"],
            })

    import asyncio
    asyncio.run(_run())
    assert called["model"] is False


def test_can_continue_follows_the_loaded_node():
    from plugins.llama_cpp_module.module import LlamaCppModule

    module = LlamaCppModule.__new__(LlamaCppModule)
    module._initialized = False
    module._node = None
    assert module.can_continue("ignored") is False
    module._initialized = True
    module._node = object()
    assert module.can_continue(None) is True


def test_execute_marks_a_length_answer_continuable(monkeypatch):
    node = _node()
    node._get_model = lambda *_a, **_k: (object(), False)
    node._generate = lambda *a, **k: {
        "text": "cua",
        "tokens": 4,
        "prompt_tokens": 100,
        "finish_reason": "length",
        "cancelled": False,
        "timing": {},
    }

    async def _run():
        return await node.execute({
            "system": "sys",
            "messages": [{"role": "user", "content": "hola"}],
        })

    import asyncio
    result = asyncio.run(_run())
    assert result["finish_reason"] == "length"
    assert result["continuable"] is True


def test_execute_hides_the_button_when_the_answer_used_images():
    node = _node(mmproj_path="/tmp/clip.gguf")
    node._get_model = lambda *_a, **_k: (object(), False)
    node._generate_vlm = lambda *a, **k: {
        "text": "veig",
        "tokens": 4,
        "prompt_tokens": 100,
        "finish_reason": "length",
        "cancelled": False,
        "timing": {},
    }

    async def _run():
        return await node.execute({
            "system": "sys",
            "messages": [{"role": "user", "content": "què és"}],
            "images": [b"\x89PNG"],
        })

    import asyncio
    result = asyncio.run(_run())
    assert result["finish_reason"] == "length"
    assert result["continuable"] is False
