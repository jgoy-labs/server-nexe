"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/deletes.py
Description: The model's [MEM_DELETE:] tags, armed for confirmation — one rule
             for every door (ADR-007 C4.5).

A model that writes `[MEM_DELETE: x]` asks; it never deletes (B028, red team
RT-04): the turn arms a two-step confirmation and the user answers — a typed
"sí" next turn, the web dialog's button, the CLI's prompt. Until 26/09 the
arming existed three times and no two agreed: the streaming web path skipped a
tag when a confirmation was already pending and put the MODEL's phrase in the
sentinel; the JSON web path overwrote the pending one and put the ENTRY's text;
`/v1` wrote the tags to `usage["mem_deletes"]` and nobody read them.

`arm_pending_deletes` is the one rule. The doors render its outcome in their
own alphabet — the web UI's `\\x00[PENDING_DELETE:…]\\x00` sentinel, a header and
a field at `/v1` — and `confirm_pending_delete` is what the dialog and the CLI
call: the same path a typed "sí" takes, by exact id, with the B093 guard.
`cancel_pending_delete` is their «no» (#1136): it disarms on the server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from core.log_redact import redact_user_content
from core.memory_facts import intents
from core.memory_facts.intent_patterns import matches_clear_all_confirm

logger = logging.getLogger(__name__)

#: A tag shorter than this names nothing that could be found in memory.
MIN_FACT_CHARS = 3

#: The user's own words asking to forget — wider than intent_patterns'
#: DELETE_TRIGGERS on purpose: the model's tag is the fallback for the
#: phrasings those miss («el Bombolla ja no hi és», «treu-ho»). Matched on
#: the FOLDED text (review 04/10: «Bórralo», «Olvídate», «Elimínalo» carry
#: an accent inside the stem and armed nothing, while the model said it had
#: forgotten).
_ASKED_TO_FORGET_RE = re.compile(
    r"\b(?:oblid|esborr|elimin|treu|tregu|olvid|borr|quit|suprim|forget|delet|eras|remov|wipe)\w*"
    r"|\bno\s+(?:ho\s+|lo\s+|te\s+)?(?:recordis|recordes|recuerdes)\b|\bscratch\s+that\b"
    r"|\b(?:ja|ya)\s+no\b|\bno\s+longer\b|\banymore\b"
)
#: A short yes, the second step of «oblida X» — «sí» — «Sí!», «sí, si us
#: plau», «d'acord», «ok», «yes please» (review 04/10: only a bare «sí»
#: counted). At most five words: a yes that goes on is a new request.
_SHORT_YES_RE = re.compile(
    r"^\W*(?:si|yes|ok|okay|vale|val|d'acord|dacord|endavant|fes-ho|confirmo|confirma"
    r"|claro|dale|sure|yep|yeah|correcte|correcto|exacte|exacto)\b"
)
_SHORT_YES_MAX_WORDS = 5


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (text or "").casefold())
                   if unicodedata.category(c) != "Mn").replace("\u2019", "'")


def _asks_to_forget(text: str) -> bool:
    return bool(_ASKED_TO_FORGET_RE.search(_fold(text)))


def _is_short_yes(text: str) -> bool:
    folded = _fold(text).strip()
    return bool(_SHORT_YES_RE.match(folded)) and len(re.findall(r"\w+", folded)) <= _SHORT_YES_MAX_WORDS


def user_asked_to_forget(session, user_message: str) -> bool:
    """Did the USER ask for this? (#1135, live 03/10, second case.)

    Asked how its memory works, the 9B made up an example with the user's real
    name — `[MEM_DELETE: L'usuari es diu Jordi]` — and the dialog offered to
    delete it. No rule on the tag's content can tell that from a request; what
    can is that nobody asked. True when this turn's message asks to forget, or
    is a short yes right after one that did (the instructions' two steps).
    """
    message = user_message or ""
    if _asks_to_forget(message):
        return True
    if not (matches_clear_all_confirm(message) or _is_short_yes(message)):
        return False
    users = [m.get("content") or "" for m in (getattr(session, "messages", None) or []) if m.get("role") == "user"]
    if users and users[-1].strip() == message.strip():
        users = users[:-1]  # this turn's own message (persist_user_turn stores it as is)
    return bool(users) and _asks_to_forget(users[-1])


async def arm_pending_deletes(
    session, deletes: list, port, collections: Optional[list] = None, *, user_message: str,
) -> Optional[intents.IntentOutcome]:
    """Arm the confirmation for the first tag that matches an entry; never delete.

    Returns the outcome the door renders — `kind="delete_pending"`, `text` the
    question, `pending_delete_fact` the ENTRY's text (what the user will
    confirm, not the model's paraphrase of it) — or None when nothing armed.

    The rule (26/09), taken from the three variants:

    * A confirmation already pending is not overwritten: the typed "sí" of the
      next turn answers the question the user actually saw.
    * The turn's selected collections narrow the search, as a typed "oblida"
      does (`intents._delete`); a tag never reaches a collection the user
      switched off.
    * A failed, erroring or empty preview arms nothing and shows nothing
      (TUR-PHANTOM-DEL): no dead confirm button, no pending flag.
    * Best match only, `entries=[:1]` (B028/RT-04): what the user confirms is
      exactly what dies, never cross-collection collateral.
    """
    if not deletes:
        return None
    if not user_asked_to_forget(session, user_message):
        logger.info("MEM_DELETE (model tag): the user asked to forget nothing — a mention, not armed (#1135)")
        return None
    if getattr(session, "_pending_partial_delete", None):
        logger.info("MEM_DELETE (model tag): a confirmation is already pending; the new tag waits")
        return None
    for fact in deletes:
        fact = (fact or "").strip()
        if len(fact) < MIN_FACT_CHARS:
            continue
        try:
            preview = await port.preview_delete_from_memory(fact, collections=collections)
        except Exception:
            logger.warning("MEM_DELETE preview failed for %s", redact_user_content(fact), exc_info=True)
            continue
        candidates = (preview or {}).get("candidates") or []
        if not ((preview or {}).get("success") and candidates):
            logger.info("MEM_DELETE (model tag): no match for %s", redact_user_content(fact))
            continue
        best = candidates[:1]
        session._pending_partial_delete = {"content": fact, "entries": best}
        logger.info("MEM_DELETE (model tag): pending confirmation for %s", redact_user_content(fact))
        return intents.IntentOutcome(
            kind="delete_pending",
            text=intents.delete_confirm_question(best),
            memory_action="delete_pending",
            pending_delete_fact=(best[0].get("text") or fact),
        )
    return None


def cancel_pending_delete(session) -> bool:
    """The dialog's «Cancel·la», the CLI's "no": disarm the session's pending
    delete, so a bare "sí" next turn finds nothing to confirm (#1136).

    Until 03/10 the cancel stayed in the client: the flag waited for the next
    message, and a "sí" to anything else would have deleted the entry the
    user had just refused. Returns whether something was pending.
    """
    pending = bool(getattr(session, "_pending_partial_delete", None))
    session._pending_partial_delete = None
    if pending:
        logger.info("MEM_DELETE: cancelled by the user, nothing deleted")
    return pending


def _same_text(a: str, b: str) -> bool:
    """The two texts, letters and digits only, case-folded — the dialog shows
    the entry and sends it back; a trailing period or a capital must not turn
    that into "not a reference"."""
    norm = lambda t: " ".join(re.findall(r"\w+", (t or "").casefold()))  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


async def confirm_pending_delete(session, port, reference: str = "") -> intents.IntentOutcome:
    """The dialog's button, the CLI's "yes": delete the session's pending entry
    by exact id — the very path a typed "sí" takes, B093 included.

    `reference` is what the user confirmed. When it IS the pending entry's text
    (what the dialog showed and sends back), the confirmation names the entry
    explicitly — B093's condition — whatever the length of its words (live
    26/09: "el meu gos es diu Tro" has no token `references_entry` counts, and
    the click was refused). Any other reference still has to name the entry
    the way a typed message does. Nothing pending → `delete.nothing_pending`,
    nothing deleted; the caller decides the status code.
    """
    entries = (getattr(session, "_pending_partial_delete", None) or {}).get("entries", [])
    explicit = any(_same_text(reference, e.get("text", "")) for e in entries)
    return await intents._delete_confirm(session, port, reference, explicit_reference=explicit)
