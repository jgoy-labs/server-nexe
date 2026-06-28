"""B076 — top_p arrival proof for the Ollama-UI chat path and the UI validator.

These tests are an *arrival* proof, not an output-quality proof: with
temperature>0 the sampled output is non-deterministic and no engine has a
reliable seed under MLX, so we cannot assert on generated text. Instead we
capture the exact value at the terminal sampling boundary:

  (A) `OllamaChat._build_payload` — the value that lands in
      ``payload["options"]["top_p"]`` (what Ollama's sampler reads).
  (B) `_parse_ui_top_p` — the UI validator that decides which value (or None)
      is forwarded into that payload.

Both assert the EXACT propagated value (0.42, 0.5, 1.0, ...). If production
regressed to a hardcoded constant (e.g. 0.9) or dropped the parameter, the
equality asserts fail — i.e. these tests are red-on-mutation by construction.
The top_p=None case pins the opt-in default contract: the key must be ABSENT
so Ollama keeps its own default (no silent behaviour change).

Imports are lazy inside each test, mirroring the existing repo style
(tests/plugins/ollama_module/test_chat_coverage.py).
"""
from unittest.mock import MagicMock

import pytest


class TestOllamaBuildPayloadTopP:
    """(A) top_p reaches payload["options"]["top_p"] in the Ollama-UI engine."""

    def _chat(self):
        from plugins.ollama_module.core.chat import OllamaChat
        mock_client = MagicMock()
        mock_client.base_url = "http://localhost:11434"
        return OllamaChat(mock_client)

    def test_top_p_forwarded_exact_value(self):
        chat = self._chat()
        payload = chat._build_payload(
            "llama3.1:8b",
            [{"role": "user", "content": "hi"}],
            stream=True,
            top_p=0.42,
        )
        # EXACT value pinned: a hardcode (0.9) or an ignored arg would fail here.
        assert payload["options"]["top_p"] == 0.42

    def test_top_p_forwarded_second_value(self):
        # A second distinct value rules out the test passing on a coincidental
        # constant: only genuine propagation satisfies both 0.42 and 0.3.
        chat = self._chat()
        payload = chat._build_payload(
            "llama3.1:8b",
            [{"role": "user", "content": "hi"}],
            stream=False,
            top_p=0.3,
        )
        assert payload["options"]["top_p"] == 0.3

    def test_top_p_none_omits_key(self):
        # Opt-in contract: when top_p is None the key must be ABSENT so Ollama
        # keeps its own default (no behaviour change for non-opt-in callers).
        chat = self._chat()
        payload = chat._build_payload(
            "llama3.1:8b",
            [{"role": "user", "content": "hi"}],
            stream=True,
            top_p=None,
        )
        assert "top_p" not in payload["options"]

    def test_top_p_default_arg_omits_key(self):
        # Same as above but exercising the default (caller omits top_p entirely).
        chat = self._chat()
        payload = chat._build_payload(
            "llama3.1:8b",
            [{"role": "user", "content": "hi"}],
            stream=True,
        )
        assert "top_p" not in payload["options"]


class TestParseUiTopP:
    """(B) _parse_ui_top_p validates + forwards the UI body's top_p."""

    def _fn(self):
        from plugins.web_ui_module.api.routes_chat import _parse_ui_top_p
        return _parse_ui_top_p

    def test_valid_midrange(self):
        # EXACT pass-through: a regression that clamped/replaced the user value
        # (e.g. returned 0.9) would fail this equality.
        assert self._fn()({"top_p": 0.5}) == 0.5

    def test_absent_returns_none(self):
        # Opt-in: absent → None so the engine keeps its current default.
        assert self._fn()({}) is None

    def test_upper_bound_inclusive(self):
        # 1.0 is the inclusive upper limit and must pass through unchanged.
        assert self._fn()({"top_p": 1.0}) == 1.0

    def test_zero_rejected_400(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._fn()({"top_p": 0.0})
        assert exc.value.status_code == 400

    def test_above_one_rejected_400(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._fn()({"top_p": 1.5})
        assert exc.value.status_code == 400

    def test_non_numeric_rejected_400(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            self._fn()({"top_p": "x"})
        assert exc.value.status_code == 400
