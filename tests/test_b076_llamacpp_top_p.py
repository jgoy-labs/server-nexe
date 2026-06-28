"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b076_llamacpp_top_p.py
Description: B076 — the opt-in `top_p` (nucleus sampling) parameter must reach
            the terminal sampling call. The four generation methods of
            LlamaCppChatNode forward `top_p` into
            model.create_chat_completion(..., top_p=top_p if top_p is not None
            else 0.9, ...). These tests SPY on that terminal call (a fake model
            whose create_chat_completion captures kwargs) and assert the EXACT
            top_p that lands there.

            This is an ARRIVAL proof, not an output-quality proof: with
            temperature>0 the generated text is non-deterministic and no MLX
            engine has a reliable seed, so asserting on output is meaningless.
            We assert the value propagated to the sampler instead.

            RED-ON-MUTATION by construction: each test asserts the exact value
            captured by the spy (0.33 when the caller passes top_p=0.33, and the
            0.9 default when top_p=None). If production regressed to a hardcoded
            top_p, dropped the kwarg, or changed the None-default away from 0.9,
            these equality assertions fail.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest


# Stop sequences forwarded by every generation method (class attribute on the
# bare instance). The terminal sampling value we care about is `top_p`.
DEFAULT_TOP_P = 0.9
USER_TOP_P = 0.33


def _make_node():
    """Build a bare LlamaCppChatNode without touching __init__/ModelPool.

    The four _generate* methods only reference self._STOP_SEQUENCES (a class
    attribute, present on the bare instance) and — for the VLM pair —
    self._build_vlm_messages, which we stub per-test.
    """
    from plugins.llama_cpp_module.core.chat import LlamaCppChatNode

    return LlamaCppChatNode.__new__(LlamaCppChatNode)


class _SpyModel:
    """Fake llama-cpp model. create_chat_completion captures kwargs and returns
    a minimal response shaped exactly as the production methods consume it.
    """

    def __init__(self, stream: bool = False):
        self.captured_kwargs = None
        self._stream = stream

    def create_chat_completion(self, **kwargs):
        self.captured_kwargs = kwargs
        if kwargs.get("stream"):
            return iter(self._stream_chunks())
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"completion_tokens": 1, "prompt_tokens": 1},
        }

    @staticmethod
    def _stream_chunks():
        # First chunk carries content (delta.content); last carries usage.
        yield {"choices": [{"delta": {"content": "ok"}}]}
        yield {
            "choices": [{"delta": {}}],
            "usage": {"completion_tokens": 1, "prompt_tokens": 1},
        }


def _noop_callback(_piece):
    """Streaming sink — methods only require it to be callable."""
    return None


class TestGenerateTopP:
    """_generate (non-streaming text)."""

    def test_top_p_value_propagates(self):
        node = _make_node()
        model = _SpyModel()

        node._generate(model, "sys", [{"role": "user", "content": "hi"}], top_p=USER_TOP_P)

        assert model.captured_kwargs["top_p"] == USER_TOP_P

    def test_top_p_none_uses_default(self):
        node = _make_node()
        model = _SpyModel()

        node._generate(model, "sys", [{"role": "user", "content": "hi"}], top_p=None)

        assert model.captured_kwargs["top_p"] == DEFAULT_TOP_P


class TestGenerateStreamingTopP:
    """_generate_streaming (streaming text)."""

    def test_top_p_value_propagates(self):
        node = _make_node()
        model = _SpyModel(stream=True)

        node._generate_streaming(
            model, "sys", [{"role": "user", "content": "hi"}],
            _noop_callback, top_p=USER_TOP_P,
        )

        assert model.captured_kwargs["top_p"] == USER_TOP_P
        assert model.captured_kwargs["stream"] is True

    def test_top_p_none_uses_default(self):
        node = _make_node()
        model = _SpyModel(stream=True)

        node._generate_streaming(
            model, "sys", [{"role": "user", "content": "hi"}],
            _noop_callback, top_p=None,
        )

        assert model.captured_kwargs["top_p"] == DEFAULT_TOP_P


class TestGenerateVlmTopP:
    """_generate_vlm (non-streaming VLM)."""

    def test_top_p_value_propagates(self):
        node = _make_node()
        node._build_vlm_messages = lambda system, messages, images: [
            {"role": "system", "content": system}
        ]
        model = _SpyModel()

        node._generate_vlm(
            model, "sys", [{"role": "user", "content": "hi"}],
            [b"\x89PNG"], top_p=USER_TOP_P,
        )

        assert model.captured_kwargs["top_p"] == USER_TOP_P

    def test_top_p_none_uses_default(self):
        node = _make_node()
        node._build_vlm_messages = lambda system, messages, images: [
            {"role": "system", "content": system}
        ]
        model = _SpyModel()

        node._generate_vlm(
            model, "sys", [{"role": "user", "content": "hi"}],
            [b"\x89PNG"], top_p=None,
        )

        assert model.captured_kwargs["top_p"] == DEFAULT_TOP_P


class TestGenerateVlmStreamingTopP:
    """_generate_vlm_streaming (streaming VLM)."""

    def test_top_p_value_propagates(self):
        node = _make_node()
        node._build_vlm_messages = lambda system, messages, images: [
            {"role": "system", "content": system}
        ]
        model = _SpyModel(stream=True)

        node._generate_vlm_streaming(
            model, "sys", [{"role": "user", "content": "hi"}],
            [b"\x89PNG"], _noop_callback, top_p=USER_TOP_P,
        )

        assert model.captured_kwargs["top_p"] == USER_TOP_P
        assert model.captured_kwargs["stream"] is True

    def test_top_p_none_uses_default(self):
        node = _make_node()
        node._build_vlm_messages = lambda system, messages, images: [
            {"role": "system", "content": system}
        ]
        model = _SpyModel(stream=True)

        node._generate_vlm_streaming(
            model, "sys", [{"role": "user", "content": "hi"}],
            [b"\x89PNG"], _noop_callback, top_p=None,
        )

        assert model.captured_kwargs["top_p"] == DEFAULT_TOP_P


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-x", "-q"]))
