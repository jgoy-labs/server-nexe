"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/text/chunks.py
Description: One engine chunk, read and normalised (C4.4, moved from routes_chat.py).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re as _re
from typing import Any


def parse_chunk(chunk: Any) -> tuple[str, str]:
    """Extreu (content, thinking) d'un chunk de l'engine."""
    content = ""
    thinking = ""
    if isinstance(chunk, dict):
        if "message" in chunk:
            thinking = chunk["message"].get("thinking", "")
            content = chunk["message"].get("content", "")
        elif "content" in chunk:
            content = chunk["content"]
        elif "response" in chunk:
            content = chunk["response"]
    elif isinstance(chunk, str):
        content = chunk
    return content, thinking


# MC-004: precompiled once (these subs run per stream chunk in normalize_content).
PIPE_TAG_RE = _re.compile(r'<\|[^|]+\|>')
ANGLE_TAG_RE = _re.compile(r'[◁◀][^▷▶]*[▷▶]')


def normalize_content(content: str, model_name: str) -> str:
    """Normalize GPT-OSS and pipe tags for the specific model."""
    if "gpt-oss" in model_name.lower():
        content = content.replace('<|analysis|>', '<think>')
        content = content.replace('<|assistant|>', '</think>')
    else:
        content = content.replace('<|thinking|>', '<think>')
        content = content.replace('<|/thinking|>', '</think>')
    content = PIPE_TAG_RE.sub('', content)
    content = ANGLE_TAG_RE.sub('', content)
    return content
