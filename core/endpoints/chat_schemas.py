"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_schemas.py
Description: Pydantic schemas for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Annotated, List, Literal, Optional, Union

from core.turn.validate import MAX_IMAGE_BYTES

#: The trap this ceiling exists for: a data: URI carries
#: the image as base64 INSIDE `content`, base64 inflates length by ~4/3, and
#: the old flat `max_length=8000` on `content` would 422 any real image before
#: `core.turn.validate.decode_image_attachment` ever saw it. Sized FROM
#: `MAX_IMAGE_BYTES` (+ slack for the `data:<mime>;base64,` header) so the two
#: ceilings cannot silently drift apart — this one only keeps an absurdly
#: oversized payload from reaching that real check, it is not the real guard.
MAX_IMAGE_DATA_URI_LENGTH = (MAX_IMAGE_BYTES * 4) // 3 + 100


class TextContentPart(BaseModel):
    """One OpenAI-style text part of a multi-part message `content`."""

    type: Literal["text"] = "text"
    text: str = Field(..., max_length=8000)

    model_config = ConfigDict(protected_namespaces=())


class ImageUrlData(BaseModel):
    """`{"url": "data:<mime>;base64,<...>"}` — inline only, no remote fetch.

    `core.turn.validate.parse_content_parts` is what actually parses and
    validates this string (allowed MIME, real base64, decoded size under
    `MAX_IMAGE_BYTES`); this length ceiling exists only so Pydantic does not
    have to buffer an unbounded string first.
    """

    url: str = Field(..., max_length=MAX_IMAGE_DATA_URI_LENGTH)


class ImageContentPart(BaseModel):
    """One OpenAI-style image part of a multi-part message `content`."""

    type: Literal["image_url"] = "image_url"
    image_url: ImageUrlData

    model_config = ConfigDict(protected_namespaces=())


ContentPart = Annotated[
    Union[TextContentPart, ImageContentPart], Field(discriminator="type"),
]


class Message(BaseModel):
    """A single message in a chat conversation (role + content).

    `content` is a plain string (unchanged path — the public contract stays
    byte-identical for every text-only request) OR a list of OpenAI-style
    content parts (#1081: how `/v1` accepts an inline image). The two
    variants carry their OWN length ceiling each — a flat one on `content`
    would either 8000 a real image (too small) or open a text message to
    ~14 MB (too big) — see `MAX_IMAGE_DATA_URI_LENGTH`.

    Pydantic anti-DoS constraints:
      - role: max_length=64 (standard short identifier, e.g. ``user``, ``assistant``, ``system``)
      - content (str case): max_length=8000 (mirrors the existing
        ``validate_string_input`` guard; rejects oversized payloads at
        deserialization with HTTP 422 before reaching the endpoint)
      - content (list case): max_length=4 parts (a real turn needs at most a
        caption and one image; `core.turn.validate.parse_content_parts` keeps
        only the first image and logs the rest, this just bounds the list
        itself against a payload of thousands of empty parts)
    """

    role: str = Field(..., max_length=64)
    content: Union[
        Annotated[str, Field(max_length=8000)],
        Annotated[List[ContentPart], Field(min_length=1, max_length=4)],
    ] = Field(...)

    model_config = ConfigDict(protected_namespaces=())

    @field_validator("content")
    @classmethod
    def _at_most_one_image(cls, content):
        """One image part per message, refused rather than silently dropped.

        The turn carries ONE image to the engine (`_images_arg =
        [image_b64]`), so a second part was only ever going to be discarded.
        Accepting four parts of up to ~14 MB each and using one is memory
        this server buffers for nothing; refusing is also the honest answer
        to a client that asked about two images and would have got a
        confident reply about one.
        """
        if isinstance(content, list):
            images = sum(1 for part in content if getattr(part, "type", None) == "image_url")
            if images > 1:
                raise ValueError(
                    f"one image per message ({images} image parts sent); "
                    "send the others in their own turns"
                )
        return content

class ChatCompletionRequest(BaseModel):
    """Request body for the ``/v1/chat/completions`` endpoint.

    Pydantic anti-DoS constraints:
      - messages: max_length=100 (no real conversation needs more; prevents DoS via 1M msgs)
      - model: max_length=200 (long enough for HF-style ``org/repo-name:tag``)
      - engine: max_length=50 (``mlx``/``ollama``/``llama_cpp``/``auto``)
    """

    messages: List[Message] = Field(..., min_length=1, max_length=100)
    model: Optional[str] = Field(default=None, max_length=200)
    engine: Optional[str] = Field(default="auto", max_length=50)
    stream: bool = False
    use_rag: bool = True  # RAG enabled by default - searches nexe_documentation + personal_memory
    # F-D block 3: same toggle the UI has always had — None searches every
    # collection (unchanged default); a list restricts the search to those.
    rag_collections: Optional[List[str]] = Field(default=None, max_length=20)
    # F-D block 3: same per-turn override the UI's RAG slider has always had —
    # None keeps the 3 tuned per-collection thresholds.
    rag_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)  # Validated range
    top_p: Optional[float] = Field(default=None, gt=0.0, le=1.0)  # Nucleus sampling (OpenAI-compat; gt=0 excludes the degenerate empty-nucleus value that engines treat divergently)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32000)  # Prevent DoS via huge values

    model_config = ConfigDict(protected_namespaces=())
