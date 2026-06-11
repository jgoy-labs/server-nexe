"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/core/harmony_filter.py
Description: Stateful stream filter for gpt-oss "harmony" output (B027a).
    Rewrites <|channel|>analysis<|message|>…<|channel|>final<|message|>…
    into the canonical <think>…</think> convention the chat pipeline
    already understands.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re

# Structural harmony tags that carry no visible content.
_SIMPLE_TAG_RE = re.compile(r'<\|(end|start|return|endoftext|constrain|call)\|>')

_CHANNEL_TAG = "<|channel|>"
_MESSAGE_TAG = "<|message|>"

# A channel name ("analysis", "final", "commentary to=...") is short — if we
# read this much without finding <|message|>, the output is malformed and we
# bail out to passthrough instead of swallowing the stream.
_MAX_NAME_LEN = 64


class HarmonyStreamFilter:
    """Convert gpt-oss harmony channel structure to <think>…</think> on the fly.

    gpt-oss does NOT use <think> tags. Its raw output looks like::

        <|channel|>analysis<|message|>REASONING<|end|>
        <|start|>assistant<|channel|>final<|message|>ANSWER

    B027a: the tags arrive split across stream chunks (MLX streams token by
    token), so the stateless replaces in ``_normalize_content`` could never
    pair them — the generic ``<|…|>`` strip removed the tags and dumped the
    REASONING verbatim into the visible bubble.

    This filter is a small state machine fed chunk by chunk (same usage
    pattern as ``LatexStreamBuffer``): analysis/commentary channels open a
    ``<think>`` block, the final channel closes it, structural tags and the
    bare role word after ``<|start|>`` are dropped. Output is consumed by
    ``_process_content_think_tags`` exactly like qwq-style embedded thinking.

    States:
        CONTENT — emitting text (visible or thinking; downstream splits it).
        HEADER  — between <|end|>/<|start|> and the next <|channel|>: role
                  words and metadata, never shown.
        NAME    — after <|channel|>, reading the channel name until <|message|>.
    """

    _CONTENT, _HEADER, _NAME = 0, 1, 2

    def __init__(self) -> None:
        self._buf = ""
        self._state = self._CONTENT
        self._thinking_open = False

    def feed(self, content: str) -> str:
        """Feed a stream chunk; return the text safe to pass downstream."""
        if not content:
            return ""
        self._buf += content
        out: list[str] = []
        handlers = {
            self._NAME: self._consume_name,
            self._HEADER: self._consume_header,
            self._CONTENT: self._consume_content,
        }
        # Each handler consumes a slice of the buffer and returns False when
        # it needs more input (or the buffer is drained).
        while handlers[self._state](out):
            pass
        return "".join(out)

    def _bail_out_malformed(self, out: list) -> None:
        """No closing tag within the cap — passthrough rather than swallow."""
        out.append(self._buf)
        self._buf = ""
        self._state = self._CONTENT

    def _consume_name(self, out: list) -> bool:
        """NAME state: read the channel name until <|message|>."""
        m = self._buf.find(_MESSAGE_TAG)
        if m < 0:
            if len(self._buf) > _MAX_NAME_LEN:
                self._bail_out_malformed(out)
            return False  # wait for more chunks
        name = self._buf[:m].strip().lower()
        self._buf = self._buf[m + len(_MESSAGE_TAG):]
        self._state = self._CONTENT
        if name.startswith("final"):
            if self._thinking_open:
                out.append("</think>")
                self._thinking_open = False
        elif not self._thinking_open:
            # analysis / commentary → reasoning block
            out.append("<think>")
            self._thinking_open = True
        return True

    def _consume_header(self, out: list) -> bool:
        """HEADER state: drop role words/metadata until the next <|channel|>."""
        t = self._buf.find(_CHANNEL_TAG)
        if t < 0:
            if len(self._buf) > _MAX_NAME_LEN:
                self._bail_out_malformed(out)
            return False
        self._buf = self._buf[t + len(_CHANNEL_TAG):]
        self._state = self._NAME
        return True

    def _consume_content(self, out: list) -> bool:
        """CONTENT state: emit text until a structural boundary."""
        t = self._buf.find(_CHANNEL_TAG)
        b = _SIMPLE_TAG_RE.search(self._buf)
        if t >= 0 and (b is None or t < b.start()):
            out.append(self._buf[:t])
            self._buf = self._buf[t + len(_CHANNEL_TAG):]
            self._state = self._NAME
            return True
        if b is not None:
            out.append(self._buf[: b.start()])
            self._buf = self._buf[b.end():]
            if b.group(1) in ("end", "start"):
                # Header zone: role words ("assistant") until <|channel|>.
                self._state = self._HEADER
            return True
        # No complete tag: emit all but a possibly-partial tag tail.
        safe, tail = self._split_partial_tag(self._buf)
        out.append(safe)
        self._buf = tail
        return False

    def flush(self) -> str:
        """End of stream: close an open thinking block, drop header leftovers."""
        out = ""
        if self._state == self._CONTENT:
            out = self._buf
        self._buf = ""
        self._state = self._CONTENT
        if self._thinking_open:
            out += "</think>"
            self._thinking_open = False
        return out

    @staticmethod
    def _split_partial_tag(text: str) -> tuple[str, str]:
        """Hold back a trailing partial '<|…' (no closing '|>') for the next chunk."""
        i = text.rfind("<|")
        if i >= 0 and "|>" not in text[i:]:
            return text[:i], text[i:]
        if text.endswith("<"):
            return text[:-1], "<"
        return text, ""
