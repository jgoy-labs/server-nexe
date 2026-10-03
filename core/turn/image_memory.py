"""#1144 — an image stays in the conversation after the turn it came in.

Live 03/10 (Ollama, qwen3.5:9b): a screenshot was described, and two turns
later «mira dos torns amunt» got «No tinc informació sobre cap imatge». The
session held the image; the engine never saw it again — an image reaches the
model only on its own turn (Ollama's payload, MLX's `has_image`), and the
history the engine gets is `role` + `content` (core/turn/assemble.py).

Jordi's decisions (03/10): the history carries a note with the image's OWN
description, written in the background by the same model after the turn
(«descripció pròpia»), and an image the user mentions is attached again
(«sí, posa la capa 2») — at both doors («però aplica a l'API també»).

This module is the part both doors share: the words that mention an image,
the note, the key an image is remembered by, the descriptions themselves and
the call that writes one. The doors decide where an image comes from — the
web's session stores it with the message; /v1's client resends it.

Descriptions live in process memory only, keyed by a hash of the image: the
web also keeps each one with its message in the (encrypted) session; nothing
here writes plaintext to disk.
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import re
import unicodedata
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The section label of the note. Short and bracketed, so a model that echoes
#: it is stripped like the other context labels (core/turn/text/clean.py).
NOTE_LABEL = {"ca": "IMATGE ADJUNTA", "es": "IMAGEN ADJUNTA", "en": "ATTACHED IMAGE"}

DESCRIBE_PROMPT = {
    "ca": "Descriu objectivament aquesta imatge en dues o tres frases: què s'hi veu i el text "
          "important que conté. Només la descripció, sense comentaris.",
    "es": "Describe objetivamente esta imagen en dos o tres frases: qué se ve y el texto "
          "importante que contiene. Solo la descripción, sin comentarios.",
    "en": "Describe this image objectively in two or three sentences: what it shows and the "
          "important text in it. Only the description, no comments.",
}

#: A description is a few sentences; a model that rambles is cut here.
MAX_DESCRIPTION_CHARS = 600

#: Review 03/10: a bare noun misfired both ways — «build the docker image»,
#: «captura l'excepció», «the big picture» re-attached the image, each time a
#: cold turn. So: an article or demonstrative right before the noun («la
#: imatge», «aquesta foto», «the screenshot»), or a word that can only mean it.
_DETERMINERS = (
    r"(?:la|l'|el|les|els|una|un|aquesta|aquestes|aquella|aquell|la meva|"
    r"esta|esa|estas|aquella|mi|tu|"
    r"the|this|that|these|those|my|your)"
)
_IMAGE_NOUNS = (
    r"(?:imatges?|fotos?|fotografi(?:a|es|as)|captur(?:a|es|as)|imagen(?:es)?|"
    r"images?|pictures?|photos?|screenshots?|pantallazos?)"
)
_MENTION_RE = re.compile(
    rf"(?:^|[\s(«\"']){_DETERMINERS}\s*{_IMAGE_NOUNS}\b"
    r"|\b(?:screenshots?|pantallazos?|captura de pantalla|captures de pantalla)\b"
)


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (text or "").casefold())
                   if unicodedata.category(c) != "Mn")


def mentions_image(text: str) -> bool:
    """Does the message talk about an image («mira la imatge», «a la foto»…)?"""
    return bool(_MENTION_RE.search(_fold(text)))


def image_key(image_b64: str) -> str:
    """What an image is remembered by: the same bytes give the same key."""
    return hashlib.sha256((image_b64 or "").encode("ascii", "ignore")).hexdigest()[:32]


class _Descriptions:
    """Bounded, process-wide: image key → its value (a description, or the
    number of times one could not be written)."""

    def __init__(self, size: int = 512) -> None:
        self._size = size
        self._items: "OrderedDict[str, Any]" = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, key: str, description: Any) -> None:
        self._items[key] = description
        self._items.move_to_end(key)
        while len(self._items) > self._size:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


DESCRIPTIONS = _Descriptions()

#: Review 04/10: «no description yet» could not be told from «none will ever
#: come» — a blind engine, or text the input filter refuses («<script…» in a
#: screenshot of code) — so the image went again on every later turn,
#: unprompted, each a cold turn and one more description call. A description
#: that comes back empty this many times (a cancelled one does not count) is
#: given up: the note stays bare, and the image goes again only when the user
#: talks about it.
MAX_DESCRIBE_ATTEMPTS = 2
FAILED_ATTEMPTS = _Descriptions()


def note_failed_attempt(key: str) -> None:
    FAILED_ATTEMPTS.put(key, (FAILED_ATTEMPTS.get(key) or 0) + 1)


def gave_up(key: str) -> bool:
    return (FAILED_ATTEMPTS.get(key) or 0) >= MAX_DESCRIBE_ATTEMPTS


def describable(key: str) -> bool:
    """Still to be described: no description, and not given up."""
    return not DESCRIPTIONS.get(key) and not gave_up(key)


def note(description: Optional[str], lang: Optional[str]) -> str:
    """The line an earlier image leaves in the history."""
    label = NOTE_LABEL.get((lang or "")[:2], NOTE_LABEL["en"])
    return f"[{label}] {description}" if description else f"[{label}]"


def tidy(text: str) -> str:
    """A description as the history carries it: the model's format stripped,
    one paragraph, no brackets of its own, bounded."""
    from core.turn.text.clean import clean_full_response  # deferred: clean imports turn.text

    clean, _, _ = clean_full_response(text or "")
    # A closed reasoning block is gone already; one cut by the length bound
    # never closes, and what follows its opening is reasoning (review 04/10).
    clean = clean.split("<think>")[0]
    one_line = " ".join(clean.replace("[", "(").replace("]", ")").split())
    return one_line[:MAX_DESCRIPTION_CHARS].strip()


def _is_ollama(engine: Any) -> bool:
    kind = f"{type(engine).__module__}.{type(engine).__name__}".lower()
    return "ollama" in kind


def _text_of(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        message = result.get("message")
        if isinstance(message, dict):
            return message.get("content") or ""
        for field in ("response", "content", "text"):
            if isinstance(result.get(field), str):
                return result[field]
    return ""


#: The description needs the gist, not the pixels: a smaller image keeps the
#: part MLX cannot interrupt (reading the prompt, #1127) short.
DESCRIBE_IMAGE_SIDE = 768
#: A few sentences; also bounds how long a description can hold the engine.
DESCRIBE_MAX_TOKENS = 200


def _smaller(image_b64: str) -> str:
    """The image at DESCRIBE_IMAGE_SIDE at most, for the description only."""
    import base64
    import io

    from PIL import Image

    from core.turn.validate import _PILLOW_FORMATS, _to_rgb, _upright

    try:
        raw = base64.b64decode(image_b64, validate=False)
        with Image.open(io.BytesIO(raw), formats=_PILLOW_FORMATS) as original:
            if max(original.size) <= DESCRIBE_IMAGE_SIDE:
                return image_b64
            img = _to_rgb(_upright(original))
            img.thumbnail((DESCRIBE_IMAGE_SIDE, DESCRIBE_IMAGE_SIDE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85)
        return base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:  # unreadable: the engine gets it as the turn did
        return image_b64


def _safe(description: str) -> str:
    """Nothing the user's own words could not carry. The description writes
    out the text in the image, and it rides in the history as a user turn on
    every later turn: a line the sanitizer would refuse or the jailbreak
    speed-bump would flag is not kept (review 03/10)."""
    from core.turn.validate import jailbreak_notice, sanitize_user_text

    if not description:
        return ""
    try:
        sanitize_user_text(description)
    except Exception:
        logger.info("Image description not kept: the sanitizer refused it (#1144)")
        return ""
    if jailbreak_notice(description):
        logger.info("Image description not kept: it reads like an instruction (#1144)")
        return ""
    return description


def _content_of(chunk: Any) -> str:
    """The visible text of one streamed chunk, whatever the engine's shape —
    the core's own parser, so the reasoning half never becomes description
    (live 03/10: MLX streams `{'message': {'content', 'thinking'}, 'raw'}`
    dicts, not strings, and joining them as strings failed every time)."""
    from core.turn.text.chunks import parse_chunk

    content, _thinking = parse_chunk(chunk)
    return content or ""


async def _stream_ollama(engine: Any, model_name: str, messages: list, image_b64: str, cancel_event: Any) -> str:
    parts: list[str] = []
    stream = engine.chat(model=model_name, messages=messages, stream=True,
                         images=[image_b64], thinking_enabled=False)
    try:
        async for chunk in stream:
            if cancel_event is not None and cancel_event.is_set():
                return ""
            parts.append(_content_of(chunk))
            if sum(map(len, parts)) > MAX_DESCRIPTION_CHARS * 2:
                break
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()  # closing the stream ends Ollama's request
    return "".join(parts)


async def _stream_in_process(engine: Any, messages: list, image_b64: str, cancel_event: Any) -> str:
    """MLX / llama.cpp: the streaming path, the one that honours `cancel_event`
    between tokens — the one-shot path has no way to stop (review 03/10)."""
    parts: list[str] = []
    kwargs = {"messages": messages, "system": "", "images": [image_b64], "thinking_enabled": False,
              "stream_callback": lambda chunk: parts.append(_content_of(chunk)),
              "max_tokens": DESCRIBE_MAX_TOKENS}
    if cancel_event is not None:
        kwargs["cancel_event"] = cancel_event
    result = engine.chat(**kwargs)
    if inspect.iscoroutine(result):
        result = await result
    return "".join(parts) or _text_of(result)


async def describe(engine: Any, model_name: str, image_b64: str, lang: Optional[str], *,
                   cancel_event: Any = None) -> str:
    """Ask the engine that served the turn for the image's own description.

    A post-commit job (`describe_image`) on the shared engine gate: a user turn
    that arrives meanwhile sets `cancel_event`, and this must give the slot
    back fast or that turn answers 429 after the gate's 5 s (review 03/10). So
    it streams and checks the event (MLX between tokens, Ollama between chunks
    — closing the stream ends the request), on a smaller image and a bounded
    reply; a cancelled call returns "" and the queue runs it again later.
    MLX keeps every op on its own worker (`_MLX_EXECUTOR`): its `chat()` is the
    same entry a turn uses. An engine that cannot see now — another model may
    have been loaded since the turn — is not asked: it would make one up.
    """
    from core.endpoints.chat_engines.routing import engine_can_see_images  # deferred: endpoints → turn

    if engine_can_see_images(engine) is False:
        logger.info("Image not described: the engine cannot see now (#1144)")
        return ""
    if cancel_event is not None and cancel_event.is_set():
        return ""  # already asked to give the slot back: not one token of prefill
    prompt = DESCRIBE_PROMPT.get((lang or "")[:2], DESCRIBE_PROMPT["en"])
    messages = [{"role": "user", "content": prompt}]
    small = _smaller(image_b64)
    if _is_ollama(engine):
        text = await _stream_ollama(engine, model_name, messages, small, cancel_event)
    else:
        text = await _stream_in_process(engine, messages, small, cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        return ""
    return _safe(tidy(text))
