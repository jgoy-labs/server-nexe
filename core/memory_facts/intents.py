"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/intents.py
Description: Memory commands, resolved in the core for every door (ADR-007 C3.1).

What moved here from plugins/web_ui_module/api/routes_chat.py: the six intent
handlers and their helpers. What changed on the way: they return DATA
(`IntentOutcome`), never a wire format. The `\\x00[MODEL:nexe-system]\\x00`
sentinels are the web UI's alphabet and are added by its own renderer; /v1 gets
the same outcome as plain text plus headers.

D6 (Jordi, 2026-09-07): "remember that ..." saves deterministically and lets the
conversation continue — it no longer answers with a fixed English line instead of
the model. Commands (forget / list / clear all / confirmations) still short-circuit:
they are orders, not conversation.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from core.memory_facts.intent_texts import text as _t

logger = logging.getLogger(__name__)

#: Entry types that count as user profile data (a bare "yes" must not erase them).
PROFILE_LIKE_TYPES = {"fact", "preference", "profile", "user_fact"}

#: B093: generic ≥4-char tokens that carry no reference to a specific entry.
DELETE_REF_STOPWORDS = {
    "user", "this", "that", "with", "from", "have", "your", "want", "just",
    "yes", "sure", "okay", "delete", "remove", "forget", "memory",
    "usuari", "usuario", "memoria", "perfil", "profile", "esborra", "elimina",
    "borra", "borrar", "oblida", "olvida", "quiero", "vull", "please", "sisplau",
}


@dataclass
class IntentOutcome:
    """What a memory command produced — data, not a wire format.

    `continue_turn` is D6's switch: True and the turn goes on to the model
    (the fact is already saved); False and the door answers with `text`.
    """

    kind: str
    text: str = ""
    memory_action: Optional[str] = None
    mem_deleted: int = 0
    mem_saved: int = 0
    continue_turn: bool = False
    #: True when `_save` handed this turn's fact to the port — persisted OR
    #: refused as a duplicate. It is NOT `mem_saved > 0`: a refused save still
    #: means the fact is in memory, so the model's paraphrase of it must not be
    #: written either. `memory.write` reads this to drop the tag the model
    #: repeats after D6 already saved (live-tested 08/09 on a 4B and a 27B:
    #: both parrot it, and past the first turn it became a second, paraphrased
    #: entry that the 0.80 dedup could not see).
    saved_by_intent: bool = False
    #: Extra data the UI turns into its own sentinels; other doors use headers.
    deleted_facts: list = field(default_factory=list)
    pending_delete_fact: Optional[str] = None


def detect_with_pending(session, message: str, port) -> tuple[str, Optional[str]]:
    """The intent for this message, honouring a confirmation armed last turn.

    Bug #18 P0 / B028: a pending confirmation hijacks the intent; anything else
    clears the flag and falls through to normal detection.
    """
    detected, extracted = port.detect_intent(message)
    if getattr(session, "_pending_clear_all", False):
        if port.matches_clear_all_confirm(message):
            return "clear_all_confirm", extracted
        session._pending_clear_all = False
    elif getattr(session, "_pending_partial_delete", None):
        if port.matches_clear_all_confirm(message):
            return "delete_confirm", extracted
        session._pending_partial_delete = None
    return detected, extracted


def sanitize_delete_history(session, content_to_delete: str) -> None:
    """Sanitize session history before delete so the LLM never sees raw 'Oblida que...' turns."""
    if not (session.messages and session.messages[-1]["role"] == "user"):
        return
    if content_to_delete:
        session.messages[-1]["content"] = f"[Memory command: delete '{content_to_delete[:50]}']"
    else:
        session.messages[-1]["content"] = "[Memory command: delete (no content specified)]"


def references_entry(message: str, entries: list) -> bool:
    """True if `message` names an entry's content with a significant token.

    A significant token is ≥4 chars and not a generic confirmation/stop word,
    so "yes" / "ok" / "delete it" alone do not count as a reference.
    """
    tokens = {t for t in re.findall(r"\w+", (message or "").lower())
              if len(t) >= 4 and t not in DELETE_REF_STOPWORDS}
    if not tokens:
        return False
    for e in entries:
        entry_text = str(e.get("text", "")).lower()
        if any(t in entry_text for t in tokens):
            return True
    return False


def _has_profile_entry(entries: list) -> bool:
    return any(
        str((e.get("metadata") or {}).get("type", "")).lower() in PROFILE_LIKE_TYPES
        for e in entries
    )


def _delete_success(result: dict, session) -> IntentOutcome:
    """The answer for a delete that actually removed something."""
    deleted_facts = result.get("deleted_facts", [])
    details = ""
    if deleted_facts:
        facts_list = ", ".join(f'"{f["text"][:60]}"' for f in deleted_facts[:5])
        details = f" [{facts_list}]"
        session._recently_deleted_facts = [f["text"] for f in deleted_facts]
    return IntentOutcome(
        kind="delete",
        text=_t("delete.done", n=result["deleted"], details=details),
        memory_action="delete",
        mem_deleted=result["deleted"],
        deleted_facts=[f["text"] for f in deleted_facts],
    )


def delete_confirm_question(candidates: list) -> str:
    items = "".join(f'\n• "{c.get("text", "")[:120]}"' for c in candidates)
    warn = _t("delete.profile_warning") if _has_profile_entry(candidates) else ""
    return _t("delete.confirm", items=items + "\n", profile_warn=warn)


async def _save(extracted_content: str, message: str, session_id: str, rag_collections, port) -> IntentOutcome:
    """D6: save the fact and hand the turn back to the model.

    The fact is persisted here, deterministically, before anything is generated:
    whatever the model then answers, the memory is already written.
    """
    content_to_save = (extracted_content.strip() if extracted_content else message).rstrip("?!").strip()
    if not content_to_save:
        return IntentOutcome(kind="save", memory_action="save", continue_turn=True)

    result = await port.save_to_memory(
        content=content_to_save,
        session_id=session_id,
        metadata={"original_message": message, "type": "user_fact"},
        collections=rag_collections,
    )
    saved = bool(result["success"] and result.get("document_id"))
    if not saved and not result.get("duplicate"):
        logger.warning("memory intent 'save' did not persist: %s", result.get("message", "unknown"))
    return IntentOutcome(
        kind="save",
        memory_action="save",
        mem_saved=1 if saved else 0,
        # The port has seen this fact this turn (stored, or refused as a
        # duplicate of what is already there) — either way `memory.write` must
        # not write what the model repeats about it.
        saved_by_intent=True,
        continue_turn=True,
    )


async def _delete(extracted_content: str, session, rag_collections, port) -> IntentOutcome:
    """Arm a 2-turn confirmation for a partial delete (B028 — never deletes directly)."""
    content_to_delete = extracted_content.strip() if extracted_content else ""
    # B-mem-delete fix: sanitize history BEFORE the result check, so the original
    # "Oblida que..." is never seen by the LLM in later turns, deleted or not.
    sanitize_delete_history(session, content_to_delete)
    if not content_to_delete:
        return IntentOutcome(kind="delete", text=_t("delete.empty"), memory_action="delete")

    preview = await port.preview_delete_from_memory(content_to_delete, collections=rag_collections)
    candidates = preview.get("candidates", [])
    if preview.get("success") and candidates:
        # Best global match only — see delete_from_memory (B028/RT-04).
        best = candidates[:1]
        session._pending_partial_delete = {"content": content_to_delete, "entries": best}
        return IntentOutcome(
            kind="delete_pending",
            text=delete_confirm_question(best),
            memory_action="delete_pending",
            pending_delete_fact=best[0].get("text", "") if best else "",
        )
    if preview.get("success"):
        return IntentOutcome(
            kind="delete",
            text=_t("delete.not_found", fact=content_to_delete[:100]),
            memory_action="delete",
        )
    return IntentOutcome(
        kind="delete",
        text=_t("delete.error", error=preview.get("message", "Unknown error")),
        memory_action="delete",
    )


async def _delete_confirm(session, port, message: str) -> IntentOutcome:
    """Execute a confirmed partial delete by exact id (B028 2-turn flow).

    B093: profile entries require an explicit reference, not a bare "yes".
    """
    pending = getattr(session, "_pending_partial_delete", None) or {}
    session._pending_partial_delete = None
    entries = pending.get("entries", [])
    content = pending.get("content", "")
    if not entries:
        return IntentOutcome(kind="delete", text=_t("delete.nothing_pending"), memory_action="delete")
    if _has_profile_entry(entries) and not references_entry(message, entries):
        return IntentOutcome(kind="delete", text=_t("delete.blocked"), memory_action="delete_blocked")

    result = await port.delete_memory_entries(entries)
    if result["success"] and result.get("deleted", 0) > 0:
        return _delete_success(result, session)
    if result["success"]:
        return IntentOutcome(
            kind="delete", text=_t("delete.not_found", fact=content[:100]), memory_action="delete",
        )
    return IntentOutcome(
        kind="delete",
        text=_t("delete.error", error=result.get("message", "Unknown error")),
        memory_action="delete",
    )


async def _list(rag_collections, port) -> IntentOutcome:
    list_result = await port.list_memories(limit=20, collections=rag_collections)
    if not (list_result["success"] and list_result["facts"]):
        return IntentOutcome(kind="list", text=_t("list.empty"), memory_action="list")
    lines = []
    for i, f in enumerate(list_result["facts"], 1):
        date_str = f.get("created_at", "")[:10] if f.get("created_at") else ""
        lines.append(f"  {i}. {f['text']}" + (f" ({date_str})" if date_str else ""))
    header = _t("list.header", shown=len(list_result["facts"]), total=list_result["total"])
    return IntentOutcome(kind="list", text=header + "\n" + "\n".join(lines), memory_action="list")


async def _clear_all_confirm(session, port) -> IntentOutcome:
    session._pending_clear_all = False
    try:
        clear_result = await port.clear_memory(confirm=True)
        if clear_result.get("success"):
            logger.info("clear_all executed via 2-turn confirmation (session=%s)", session.id)
            return IntentOutcome(
                kind="clear_all", text=_t("clear_all.done"), memory_action="clear_all", mem_deleted=1,
            )
        err = str(clear_result.get("message", "unknown"))
        logger.warning("clear_all failed: %s", err)
    except Exception as exc:  # noqa: BLE001 — the answer must say what failed
        err = str(exc)
        logger.error("clear_all exception: %s", exc)
    return IntentOutcome(
        kind="clear_all", text=_t("clear_all.error", error=err), memory_action="clear_all",
    )


async def resolve(
    intent: str, extracted_content: str, session, port, message: str, *, rag_collections=None,
) -> IntentOutcome:
    """Run a detected memory intent and return what the door should do with it.

    `rag_collections` is passed explicitly rather than dug out of a body: the
    two doors carry different request objects (the UI a dict, /v1 a Pydantic
    model) and the core should know neither.
    """

    if intent == "save":
        return await _save(extracted_content, message, session.id, rag_collections, port)
    if intent == "delete":
        return await _delete(extracted_content, session, rag_collections, port)
    if intent == "list":
        return await _list(rag_collections, port)
    if intent == "clear_all":
        # Bug #18 P0: arm the 2-turn confirmation; the wipe happens on confirm.
        session._pending_clear_all = True
        return IntentOutcome(
            kind="clear_all_pending",
            text=_t("clear_all.confirm"),
            memory_action="clear_all_pending",
        )
    if intent == "clear_all_confirm":
        return await _clear_all_confirm(session, port)
    if intent == "delete_confirm":
        return await _delete_confirm(session, port, message)
    if intent == "recall":
        # Recall is not a command: the model answers it with the recalled context.
        return IntentOutcome(kind="chat", memory_action="recall", continue_turn=True)
    return IntentOutcome(kind="chat", continue_turn=True)


def intent_enabled() -> bool:
    """D7: one global flag, both doors. Default on."""
    import os

    from core.env_utils import parse_truthy

    return parse_truthy(os.environ.get("NEXE_MEMORY_INTENT", "true"))


def outcome_for(ctx_intent: str, outcome: IntentOutcome) -> str:
    """The resolved intent name for the trace/wire ('chat' when the turn goes on)."""
    return "chat" if outcome.continue_turn else (outcome.kind or ctx_intent)
