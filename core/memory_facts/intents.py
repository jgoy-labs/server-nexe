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
    #: The fact this turn's save left in memory (stored or already there) —
    #: what a door may show as saved (#1098). Empty when storage failed.
    kept_facts: list = field(default_factory=list)
    #: Extra data the UI turns into its own sentinels; other doors use headers.
    deleted_facts: list = field(default_factory=list)
    pending_delete_fact: Optional[str] = None


def detect_with_pending(session, message: str, port) -> tuple[str, Optional[str]]:
    """The intent for this message, honouring a confirmation armed last turn.

    Bug #18 P0 / B028: a pending confirmation hijacks the intent; anything else
    clears the flag and falls through to normal detection. Only ONE pending can
    be answered by a message: whichever is answered (yes or not), the others are
    dropped too — a yes meant for one question must never reach another one a
    turn later (review 19/10).
    """
    detected, extracted = port.detect_intent(message)
    clear_all = getattr(session, "_pending_clear_all", False)
    partial = getattr(session, "_pending_partial_delete", None)
    replace = getattr(session, "_pending_replace", None)
    session._pending_clear_all = False
    session._pending_partial_delete = None
    session._pending_replace = None
    if not (clear_all or partial or replace):
        return detected, extracted
    if not port.matches_clear_all_confirm(message):
        return detected, extracted
    if clear_all:
        session._pending_clear_all = True  # `_clear_all_confirm` resets it
        return "clear_all_confirm", extracted
    if partial:
        session._pending_partial_delete = partial
        return "delete_confirm", extracted
    # TOKENS-20261015-13: the server asked «vols que ho canviï?» and armed this
    # at `memory.write`; only the user's very next yes carries it out.
    session._pending_replace = replace
    return "replace_confirm", extracted


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


#: A NEW first-person predicate after "i/y/and" — "visc a Vic i (que) treballo
#: de fuster" is two facts, "m'agraden la vainilla i els macarrons" is one. Only
#: these verbs split: an unknown one keeps the fact whole, which is the old
#: behaviour, never a wrong cut (#1056).
_FIRST_PERSON_SPLIT = re.compile(
    r"\s+(?:i|y|and)\s+(?:que\s+|that\s+)?(?=(?:"
    r"visc|treballo|estudio|tinc|sóc|soc|em dic|m'agrada|m'agraden|parlo|prefereixo|faig|"
    r"vivo|trabajo|tengo|soy|me llamo|me gusta|me gustan|hablo|prefiero|hago|"
    r"i live|i work|i study|i have|i am|i'm|my name is|i like|i speak|i prefer|"
    r"live|work|study|have|am|like|speak|prefer"
    r")\b)",
    re.IGNORECASE,
)


def split_first_person(content: str) -> list:
    """"recorda que A i B" → [A, B] when B starts a new first-person predicate (#1056)."""
    parts = [p.strip(" .,;") for p in _FIRST_PERSON_SPLIT.split(content)]
    parts = [p for p in parts if p]
    return parts if len(parts) >= 2 else [content]


async def _save(
    extracted_content: str, message: str, session_id: str, rag_collections, port, session=None,
) -> IntentOutcome:
    """D6: save the fact and hand the turn back to the model.

    The fact is persisted here, deterministically, before anything is generated:
    whatever the model then answers, the memory is already written. A request
    that carries two facts ("recorda que visc a Vic i que treballo de fuster")
    is stored as two (#1056) — one card each, so forgetting one leaves the other.
    """
    content_to_save = (extracted_content.strip() if extracted_content else message).rstrip("?!").strip()
    if not content_to_save:
        return IntentOutcome(kind="save", memory_action="save", continue_turn=True)

    saved = 0
    kept: list = []
    for fact in split_first_person(content_to_save):
        result = await port.save_to_memory(
            content=fact,
            session_id=session_id,
            metadata={"original_message": message, "type": "user_fact"},
            collections=rag_collections,
        )
        if result["success"] and result.get("document_id"):
            saved += 1
            kept.append(fact)
        elif result.get("duplicate") and result.get("same", True):
            kept.append(fact)
        elif result.get("duplicate"):
            # Similar to a stored fact, not the same: it was not saved, so the
            # turn must not say it was (TOKENS-20261015-13) — and the model
            # asks whether to replace it; the user's next yes does.
            logger.info("memory intent 'save' not kept: similar to a stored fact, not the same")
            if session is not None and result.get("similar_to"):
                arm_replace(session, result["similar_to"], fact)
        else:
            logger.warning("memory intent 'save' did not persist: %s", result.get("message", "unknown"))
    return IntentOutcome(
        kind="save",
        memory_action="save",
        mem_saved=saved,
        kept_facts=kept,
        # The port has seen this turn's facts (stored, or refused as duplicates
        # of what is already there) — either way `memory.write` must not write
        # what the model repeats about them.
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


async def _delete_confirm(session, port, message: str, *, explicit_reference: bool = False) -> IntentOutcome:
    """Execute a confirmed partial delete by exact id (B028 2-turn flow).

    B093: profile entries require an explicit reference, not a bare "yes".
    `explicit_reference` (C4.5) is the caller vouching that `message` IS the
    pending entry (the web dialog sends back the very text it showed): a click
    on the shown entry names it, even when its words are all too short for
    `references_entry` to count any ("el meu gos es diu Tro").
    """
    pending = getattr(session, "_pending_partial_delete", None) or {}
    session._pending_partial_delete = None
    entries = pending.get("entries", [])
    content = pending.get("content", "")
    if not entries:
        return IntentOutcome(kind="delete", text=_t("delete.nothing_pending"), memory_action="delete")
    if _has_profile_entry(entries) and not explicit_reference and not references_entry(message, entries):
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


def arm_replace(session, old: str, new: str, keyed: Optional[dict] = None) -> None:
    """A fact close to a stored one but not the same: remember the pair for the
    user's next yes. Nothing is changed here — B028: a model's tag asks, the
    user's own answer decides.

    Several changes in one message wait together, in `more`, and one yes does
    them all (review 19/10: the second used to overwrite the first). `keyed` is
    the key the new fact will carry when it is saved.
    """
    item = {"old": old, "new": new}
    if keyed:
        item["keyed"] = keyed
    pending = getattr(session, "_pending_replace", None)
    if pending and not pending.get("asked"):
        pending.setdefault("more", []).append(item)
    else:
        session._pending_replace = dict(item)
    logger.info("MEM_SAVE: replace armed, waiting for the user's yes")


async def _remove_old_fact(port, old: str) -> bool:
    """Delete the stored entry that IS `old`, by exact id. False on any doubt."""
    from core.memory_facts.helper import same_fact  # deferred: helper imports this module

    try:
        preview = await port.preview_delete_from_memory(old)
        entry = next((c for c in (preview.get("candidates") or []) if same_fact(c.get("text", ""), old)), None)
        if not (preview.get("success") and entry):
            return False
        removed = await port.delete_memory_entries([entry])
        return bool(removed.get("success") and removed.get("deleted", 0) > 0)
    except Exception:  # noqa: BLE001 — the answer must say nothing was changed
        logger.warning("replace: removing the old fact failed", exc_info=True)
        return False


async def _replace_one(session, port, old: str, new: str, keyed: Optional[dict]) -> tuple[bool, bool]:
    """(removed, stored): delete the stored entry that IS `old`, then save `new`."""
    if not await _remove_old_fact(port, old):
        return False, False
    session._recently_deleted_facts = [*getattr(session, "_recently_deleted_facts", []), old]
    # `force`: the user has just said yes to THIS pair, and the closeness test
    # would refuse the new fact for resembling some other stored one.
    saved = await port.save_to_memory(
        content=new, session_id=session.id, metadata=dict(keyed or {"type": "user_fact", "is_mem_save": True}),
        force=True,
    )
    stored = bool(saved.get("document_id"))
    if not stored:
        logger.error("replace: the old fact is gone and the new one was not saved: %s", saved.get("message"))
    return True, stored


async def _replace_confirm(session, port) -> IntentOutcome:
    """The user said yes to «vols que ho canviï?»: for each pair, delete the old
    entry by exact id, then save the new fact. Either both or the old one stays."""
    pending = getattr(session, "_pending_replace", None) or {}
    session._pending_replace = None
    pairs = [pending, *pending.get("more", [])] if pending else []
    pairs = [p for p in pairs if p.get("old") and p.get("new")]
    if not pairs:
        return IntentOutcome(kind="replace", text=_t("delete.nothing_pending"), memory_action="replace")
    session._recently_deleted_facts = []
    lines: list = []
    saved_n = deleted_n = 0
    kept: list = []
    for pair in pairs:
        removed, stored = await _replace_one(session, port, pair["old"], pair["new"], pair.get("keyed"))
        if not removed:
            lines.append(_t("replace.failed", old=pair["old"][:100]))
            continue
        deleted_n += 1
        if stored:
            saved_n += 1
            kept.append(pair["new"])
            lines.append(_t("replace.done", old=pair["old"][:100], new=pair["new"][:100]))
        else:
            lines.append(_t("replace.lost", old=pair["old"][:100], new=pair["new"][:100]))
    return IntentOutcome(
        kind="replace", text=" ".join(lines), memory_action="replace",
        mem_saved=saved_n, mem_deleted=deleted_n, kept_facts=kept,
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
        return await _save(extracted_content, message, session.id, rag_collections, port, session)
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
    if intent == "replace_confirm":
        return await _replace_confirm(session, port)
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


def replace_question(session, *, accompany: bool, lang: Optional[str] = None) -> str:
    """The question a change waiting for the user's yes is asked with, written by
    the server (pla-comportament-segons-mida-model, C).

    Only for a model the server accompanies (`core.turn.model_tier`); an
    autonomous one asks by itself. Asked once per arming, and it joins the last
    assistant message of the history so a reload shows what the user answered.
    The change itself stays untouched: B028 — the user's own yes carries it out.
    """
    pending = getattr(session, "_pending_replace", None)
    if not (accompany and pending and not pending.get("asked")):
        return ""
    pending["asked"] = True
    more = pending.get("more") or []
    if more:
        pairs = "; ".join(f"«{p['old'][:100]}» → «{p['new'][:100]}»" for p in [pending, *more])
        question = _t("replace.ask_many", lang=lang, pairs=pairs)
    else:
        question = _t("replace.ask", lang=lang, old=pending["old"][:100], new=pending["new"][:100])
    messages = getattr(session, "messages", None) or []
    if messages and messages[-1].get("role") == "assistant":
        last = messages[-1]
        last["content"] = f"{last.get('content') or ''}\n\n{question}".lstrip()
    return question
