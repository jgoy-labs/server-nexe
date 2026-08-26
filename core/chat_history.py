"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/chat_history.py
Description: The CANONICAL policy for consecutive same-role chat messages
             (finding #963). One implementation, used by every layer that
             builds a message list.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

from typing import Dict, List


def merge_consecutive_same_role(messages: List[Dict]) -> List[Dict]:
    """Merge consecutive messages that share a role, joining them with a blank line.

    THE decision (#963, Jordi, 2026-08-26): when two messages of the same role
    end up adjacent, their contents are MERGED — never discarded.

    Until now the repo answered this question twice, differently:
      - ``session_manager`` kept only the LATEST (``cleaned[-1] = m``), on the
        MC-116 reasoning that an interrupted stream leaves two adjacent 'user'
        turns and the model should answer the NEW one;
      - ``mlx_module``'s ``_merge_same_role`` joined them with "\\n\\n".
    They did not collide in practice only because they sit in different layers
    and the UI passes through the first before reaching the second — which is
    the two-hand-synchronised-lists pattern this project has already watched
    drift apart. Hence one function, in core, imported by both.

    The accepted trade-off: no user text is ever lost, at the price of a
    question the user stopped being re-sent to the model prepended to the new
    one. That was chosen over silently dropping something the user did type.

    Returns NEW dicts — the caller's messages are never mutated. Role defaults
    to "user" and content to "" so a malformed entry cannot raise here.
    """
    merged: List[Dict] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if merged and merged[-1]["role"] == role:
            merged[-1]["content"] += "\n\n" + content
        else:
            merged.append({"role": role, "content": content})
    return merged
