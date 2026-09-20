"""`/v1` accepts an inline image via OpenAI-style content parts (#1081).

This is the only piece of C4.3 that gives real NEW functionality: before it,
`/v1` had no way to carry an image at all.
Three layers, each with its own test group below:

* `parse_content_parts` (`core/turn/validate.py`) — the pure parser that turns
  a message's `content` (plain string OR a list of content parts) into
  `(text, image_b64, image_type)`.
* the schema (`core/endpoints/chat_schemas.py`) — the dual-limit trap
  measured: `content`'s old flat `max_length=8000` would 422 any real image
  before `decode_image_attachment` ever saw it.
* the real pipeline (`turn_lab.api`) — a content-parts message must reach
  `ctx.attachments` exactly like the UI door's `image_b64` field always has,
  a plain-string request must stay byte-identical (the public contract), and
  the image note (#1081) must fire through the same port.

Verified live, no mocks, against a real vision model
(`scratchpad/live_check_pas3.py`, gemma3:4b/Ollama): the model correctly named
the colour of a real generated image sent through this exact path.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from core.turn.validate import parse_content_parts


# ── parse_content_parts: the pure parser ─────────────────────────────────────

class TestParseContentParts:

    def test_plain_string_passes_through_unchanged(self):
        text, image_b64, image_type = parse_content_parts("hola, com estàs?")
        assert text == "hola, com estàs?"
        assert image_b64 is None
        assert image_type is None

    def test_text_and_image_parts_split_apart(self):
        from core.endpoints.chat_schemas import Message

        msg = Message(role="user", content=[
            {"type": "text", "text": "què hi ha en aquesta imatge?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
        ])
        text, image_b64, image_type = parse_content_parts(msg.content)
        assert text == "què hi ha en aquesta imatge?"
        assert image_b64 == "aGVsbG8="
        assert image_type == "image/png"

    def test_multiple_text_parts_join_with_newline(self):
        from core.endpoints.chat_schemas import Message

        msg = Message(role="user", content=[
            {"type": "text", "text": "primera línia"},
            {"type": "text", "text": "segona línia"},
        ])
        text, image_b64, image_type = parse_content_parts(msg.content)
        assert text == "primera línia\nsegona línia"
        assert image_b64 is None

    def test_more_than_one_image_part_is_refused_by_the_schema(self):
        """#1081 review: the turn carries ONE image to the engine, so a
        second part was only ever going to be discarded. Refusing is both
        cheaper (no ~14 MB buffered for nothing) and honest to a client that
        asked about two images and would have got a confident answer about
        one."""
        from pydantic import ValidationError

        from core.endpoints.chat_schemas import Message

        with pytest.raises(ValidationError) as exc_info:
            Message(role="user", content=[
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,d29ybGQ="}},
            ])
        assert "one image per message" in str(exc_info.value)

    def test_only_the_first_image_is_kept(self):
        """The parser stays tolerant even though the schema now refuses a
        second image part: `parse_content_parts` is reachable from anywhere,
        and a function that picks one of two must say WHICH one. Built
        part-by-part on purpose — `Message` would refuse this input, which is
        the point of the test above."""
        from core.endpoints.chat_schemas import ImageContentPart

        parts = [
            ImageContentPart(image_url={"url": "data:image/png;base64,aGVsbG8="}),
            ImageContentPart(image_url={"url": "data:image/jpeg;base64,d29ybGQ="}),
        ]
        text, image_b64, image_type = parse_content_parts(parts)
        assert image_b64 == "aGVsbG8="
        assert image_type == "image/png"

    def test_empty_base64_payload_is_rejected(self):
        """#1081 review: `data:image/png;base64,` with nothing after the
        comma used to sail through as `image_b64 = ""`. Falsy, so
        `validate_turn` skipped the decode, `has_image` was False and the
        turn answered 200 as if no image had been sent — the #965 shape."""
        from core.endpoints.chat_schemas import Message

        msg = Message(role="user", content=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,"}},
        ])
        with pytest.raises(HTTPException) as exc_info:
            parse_content_parts(msg.content)
        assert exc_info.value.status_code == 400
        assert "no base64 payload" in str(exc_info.value.detail)

    def test_media_type_parameters_do_not_reject_a_valid_image(self):
        """RFC 2397 allows `data:image/png;charset=utf-8;base64,…`. Keeping
        the whole header handed `decode_image_attachment` a media type that
        is not in the allow-list — a valid image refused on a technicality."""
        from core.endpoints.chat_schemas import Message

        msg = Message(role="user", content=[
            {"type": "image_url", "image_url": {
                "url": "data:image/png;charset=utf-8;base64,aGVsbG8=",
            }},
        ])
        _text, image_b64, image_type = parse_content_parts(msg.content)
        assert image_type == "image/png", "the parameters must not become part of the type"
        assert image_b64 == "aGVsbG8="

    def test_non_data_uri_is_rejected(self):
        """`/v1` accepts an INLINE image only — never a remote URL. This repo
        has no fetcher on this path and no SSRF surface worth adding for one."""
        from core.endpoints.chat_schemas import Message

        msg = Message(role="user", content=[
            {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
        ])
        with pytest.raises(HTTPException) as exc_info:
            parse_content_parts(msg.content)
        assert exc_info.value.status_code == 400


# ── the schema: the dual-limit trap ────────────────────────────────────────

class TestMessageContentDualLimit:

    def test_plain_text_over_8000_chars_still_rejected(self):
        from pydantic import ValidationError

        from core.endpoints.chat_schemas import Message

        with pytest.raises(ValidationError):
            Message(role="user", content="A" * 8001)

    def test_a_real_sized_image_data_uri_is_not_rejected(self):
        """The mistake this ceiling exists to fix: `content`'s old flat
        `max_length=8000` would have 422'd this before any image ever got
        this large — a real photo easily clears 8000 base64 chars.

        The assertion is that the URI ROUND-TRIPS intact: `len(...) > 8000`
        would be a check on the literal this test itself built (always true,
        schema change or not) — the teatre pattern the 19/09 review caught
        three times. Building the Message at all is what proves the ceiling
        moved; the assert proves nothing was silently truncated on the way.
        """
        from core.endpoints.chat_schemas import Message

        real_sized_b64 = "A" * 100_000
        msg = Message(role="user", content=[
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{real_sized_b64}"}},
        ])
        assert msg.content[0].image_url.url.endswith(real_sized_b64), (
            "the data URI must round-trip intact — truncation here would mean "
            "a silently corrupted image reaching decode_image_attachment"
        )

    def test_oversized_data_uri_is_rejected(self):
        """A data URI bigger than any real image under `MAX_IMAGE_BYTES` can
        be — Pydantic stops it before `decode_image_attachment` runs."""
        from pydantic import ValidationError

        from core.endpoints.chat_schemas import MAX_IMAGE_DATA_URI_LENGTH, Message

        with pytest.raises(ValidationError):
            Message(role="user", content=[
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + ("A" * MAX_IMAGE_DATA_URI_LENGTH),
                }},
            ])


# ── the dispatch chain: images reach the forwarder, whichever engine ────────

class TestDispatchForwardsImages:
    """The gap the live check (`scratchpad/live_check_pas3.py`) found and this
    pins: the plan only named the schema/parse/validate files — none of
    the THREE forwarders (`_forward_to_ollama`/`_forward_to_mlx`/
    `_forward_to_llama_cpp`) took an `images` param at all before this,
    unlike the UI door's unified `_start_engine_call`. An image that
    validated fine would have been silently dropped one layer down —
    exactly the silence this project has paid for before (#899/#965/#1079).
    """

    async def test_dispatch_to_engine_forwards_images_to_ollama(self):
        from core.endpoints.chat import _dispatch_to_engine
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")])
        with patch(
            "core.endpoints.chat._forward_to_ollama", new=AsyncMock(return_value={}),
        ) as mock_fwd:
            await _dispatch_to_engine(
                "ollama", [{"role": "user", "content": "hola"}], body,
                request=None, app_state=None, last_user_msg="hola",
                images=["aGVsbG8="],
            )
        assert mock_fwd.call_args.kwargs.get("images") == ["aGVsbG8="]

    async def test_dispatch_to_engine_forwards_images_to_mlx(self):
        from core.endpoints.chat import _dispatch_to_engine
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")])
        with patch(
            "core.endpoints.chat._forward_to_mlx", new=AsyncMock(return_value={}),
        ) as mock_fwd:
            await _dispatch_to_engine(
                "mlx", [{"role": "user", "content": "hola"}], body,
                request=None, app_state=None, last_user_msg="hola",
                images=["aGVsbG8="],
            )
        assert mock_fwd.call_args.kwargs.get("images") == ["aGVsbG8="]

    async def test_dispatch_to_engine_forwards_images_to_llama_cpp(self):
        from core.endpoints.chat import _dispatch_to_engine
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")])
        with patch(
            "core.endpoints.chat._forward_to_llama_cpp", new=AsyncMock(return_value={}),
        ) as mock_fwd:
            await _dispatch_to_engine(
                "llama_cpp", [{"role": "user", "content": "hola"}], body,
                request=None, app_state=None, last_user_msg="hola",
                images=["aGVsbG8="],
            )
        assert mock_fwd.call_args.kwargs.get("images") == ["aGVsbG8="]

    def test_build_ollama_payload_puts_images_in_the_last_user_message(self):
        """Ollama's `/api/chat` wants `images` INSIDE the message, not as a
        top-level payload key (that shape is `/api/generate`'s)."""
        from core.endpoints.chat_engines.ollama import _build_ollama_payload
        from core.endpoints.chat_schemas import ChatCompletionRequest, Message

        body = ChatCompletionRequest(messages=[Message(role="user", content="hola")])
        messages = [
            {"role": "system", "content": "ets nexe"},
            {"role": "user", "content": "hola"},
        ]
        payload = _build_ollama_payload(body, messages, "gemma3:4b", images=["aGVsbG8="])

        assert "images" not in payload, "images must not sit at the top level"
        assert payload["messages"][-1]["images"] == ["aGVsbG8="]
        assert payload["messages"][0].get("images") is None


# ── the real pipeline: turn_lab drives api_adapters end to end ───────────────

class TestV1AcceptsImagesThroughTheRealPipeline:

    async def test_content_parts_land_in_attachments(self, turn_lab):
        """The whole point of this step: an image sent as a content part reaches
        `ctx.attachments` exactly like the UI door's `image_b64` body field
        always has — nothing downstream needs to know which door it came
        through."""
        ctx = await turn_lab.api(
            session_id="v1-image-1",
            content=[
                {"type": "text", "text": "què hi ha en aquesta imatge?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
            ],
        )
        assert ctx.attachments.get("image_b64") == "aGVsbG8="
        assert ctx.attachments.get("image_type") == "image/png"
        assert ctx.attachments.get("image_bytes") == b"hello"

    async def test_the_mirrored_message_is_plain_text_not_a_list(self, turn_lab):
        """`mirror_v1_conversation` and every other consumer of
        `ctx.body.messages` expect a string `content` — content parts are
        peeled apart ONCE in `validate` and never reach the mirror as
        anything else."""
        ctx = await turn_lab.api(
            session_id="v1-image-2",
            content=[
                {"type": "text", "text": "descriu-la"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
            ],
        )
        assert ctx.body.messages[-1].content == "descriu-la"

    async def test_the_image_note_fires_through_the_same_port_as_pas_2(self, turn_lab):
        """#1081's `has_image` wiring was dormant at `/v1` until this
        step set `ctx.attachments["image_b64"]` — this is the test that turns
        it on. Mutation: drop `has_image` from the `budget` adapter's call to
        `_assemble_v1_messages` and this goes red."""
        ctx = await turn_lab.api(
            session_id="v1-image-3",
            content=[
                {"type": "text", "text": "descriu-la"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
            ],
        )
        # A short message like "descriu-la" is ambiguous for the language
        # detector (documented pitfall, `test_context_framing_is_one_piece.py`)
        # and can fall back to English — the note's WORDING is not this
        # test's point, only that it fired at all.
        note_turns = [
            m for m in ctx.prompt
            if m.get("role") == "user" and (
                "adjuntat una imatge" in (m.get("content") or "")
                or "attached an image" in (m.get("content") or "")
            )
        ]
        assert note_turns, f"no image note in the assembled prompt: {ctx.prompt}"

    async def test_an_image_from_an_earlier_turn_still_reaches_the_model(self, turn_lab):
        """#1081 review, the one that broke the commonest vision flow: a
        client re-sends its history, the image rides on turn 1 and the
        follow-up question arrives on turn 3 with no parts at all. Reading
        only the last user message dropped it — no log, `has_image` False,
        and a confident answer about an image nobody had.

        Mutation: go back to reading only `last_user_msg` and this goes red.
        """
        ctx = await turn_lab.api(
            session_id="v1-image-history",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "què hi ha en aquesta imatge?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
                ]},
                {"role": "assistant", "content": "Un gat."},
                {"role": "user", "content": "i de quin color és?"},
            ],
        )
        assert ctx.attachments.get("image_b64") == "aGVsbG8=", (
            "the image from the earlier turn never reached the turn's attachments"
        )
        assert ctx.message == "i de quin color és?"

    async def test_an_image_with_no_text_is_a_valid_turn(self, turn_lab):
        """#1081 review: "what is this?" with the question in the system
        message and the image alone in the user one is the canonical OpenAI
        vision request. It used to answer 400 "Message is required", blaming
        the text for a turn whose image had already decoded fine."""
        ctx = await turn_lab.api(
            session_id="v1-image-only",
            content=[
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
            ],
        )
        assert ctx.attachments.get("image_b64") == "aGVsbG8="
        assert ctx.wire is not None, "an image-only turn must produce an answer, not a 400"

    async def test_content_parts_on_a_system_message_are_accepted(self, turn_lab):
        """#1081 review: the schema accepts parts on any role and the OpenAI
        SDKs really do send a `system` that way, but `_validate_chat_request`
        ran FIRST and answered 400 "Input must be a string" for a list. The
        door that accepts the shape has to normalise it before validating."""
        ctx = await turn_lab.api(
            session_id="v1-system-parts",
            messages=[
                {"role": "system", "content": [{"type": "text", "text": "be brief"}]},
                {"role": "user", "content": "hola"},
            ],
        )
        assert ctx.body.messages[0].content == "be brief"
        assert ctx.wire is not None

    async def test_plain_string_content_stays_byte_identical(self, turn_lab):
        """The public contract this must not break: a text-only `/v1`
        request is untouched by any of this — no attachments, no note, the
        message reaches the model exactly as sent."""
        ctx = await turn_lab.api(session_id="v1-text-only", message="hola, què tal?")

        assert ctx.attachments.get("image_b64") is None
        assert ctx.body.messages[-1].content == "hola, què tal?"
        assert not any(
            "adjuntat una imatge" in (m.get("content") or "") for m in ctx.prompt
        )
