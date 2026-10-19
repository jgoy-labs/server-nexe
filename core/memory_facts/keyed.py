"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/keyed.py
Description: Facts with a key (who, what), read from the user's message by a
second pass of the model — the change of a fact is found by its key, not by
how much two sentences look alike (pla-memoria-fiable, F-C).

Why: the embeddings score 0.97 for «tinc 45 anys» / «tinc 46 anys» and far less
for «el gos es diu Tro» / «Bruc», and the same fact in another language looks
like a different one. Closeness of topic is not contradiction. The key is:
(who, what) with another value is a change; with the same value it is nothing.

The model only READS the message (a short, narrow task even a 4B does well:
live 19/10, 91–97% found, ≤3% invented); the server decides, asks and writes.
It never changes a fact by itself (B028): a change is armed and the user's own
yes carries it out (`intents.arm_replace`).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.memory_facts import intents

logger = logging.getLogger(__name__)

#: JSON schema Ollama enforces (`format`); the other engines get it as text only.
EXTRACT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {"type": "object", "properties": {
        "entity": {"type": "string"},
        "attribute": {"type": "string"},
        "value": {"type": "string"},
        "statement": {"type": "string"},
        "intent": {"type": "string", "enum": ["set", "change", "delete"]},
    }, "required": ["entity", "attribute", "value", "statement", "intent"]}}},
    "required": ["facts"],
}

#: No literal example reply here: a model of 9B answered the example it saw (live 19/10).
EXTRACT_SYSTEM = (
    "You extract personal facts the USER states about themselves or people close to them, from one message. "
    "Reply with JSON only, shape {\"facts\":[{\"entity\":..,\"attribute\":..,\"value\":..,\"statement\":..,\"intent\":..}]}. "
    "entity is who the fact is about (\"user\" for the speaker, otherwise the relation, e.g. a sister). "
    "attribute is a short english snake_case key for what is described (name, age, phone, email, location, occupation, "
    "company, pets, allergies, family, food_preferences, preferred_language, or another short key). "
    "value is the bare value only (a name, a number, a place), copied from the message, never invented or translated, "
    "without the words that surround it. "
    "statement is the fact as one short sentence in the language of the message, in the third person. "
    "intent is \"set\" when the user states a fact, \"change\" when the message says it is different now, "
    "\"delete\" when the user asks to forget it (value may be empty then). "
    "Only facts that are stated as true now. Questions, requests, hypotheticals, doubts and general knowledge are not facts; "
    "when the message holds no fact, the facts list is simply empty."
)

#: attribute word (any language) → canonical key; anything else keeps its own slug.
_ALIASES: Dict[str, str] = {
    "name": "name", "nom": "name", "nombre": "name", "first_name": "name",
    "age": "age", "edat": "age", "edad": "age", "years": "age", "anys": "age",
    "phone": "phone", "telefon": "phone", "telefono": "phone", "mobil": "phone", "movil": "phone",
    "phone_number": "phone", "mobile": "phone", "cell": "phone",
    "email": "email", "correu": "email", "correo": "email", "mail": "email", "e_mail": "email",
    "location": "location", "city": "location", "ciutat": "location", "ciudad": "location",
    "residence": "location", "address": "location", "residencia": "location", "lives_in": "location",
    "occupation": "occupation", "job": "occupation", "feina": "occupation", "trabajo": "occupation",
    "profession": "occupation", "professio": "occupation", "profesion": "occupation", "work": "occupation",
    "company": "company", "empresa": "company", "employer": "company",
    "pets": "pets", "pet": "pets", "dog": "pets", "gos": "pets", "perro": "pets", "mascota": "pets",
    "mascotes": "pets", "pet_name": "pets", "cat": "pets", "gat": "pets", "gato": "pets",
    "allergies": "allergies", "allergy": "allergies", "alergia": "allergies", "alergies": "allergies",
    "preferred_language": "preferred_language", "language": "preferred_language", "idioma": "preferred_language",
    "food_preferences": "food_preferences", "food": "food_preferences",
}

#: attributes that hold several values at once; a new one is not necessarily a change.
_MULTI = frozenset({"pets", "allergies", "family", "food_preferences", "hobbies", "interests", "tools"})


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _fold(text)).strip("_")


def _squash(text: str) -> str:
    """Letters and digits only, accents folded: the way two values are compared."""
    return re.sub(r"[^a-z0-9@.]+", "", _fold(text))


#: «45», «45 anys», «600 111 222», «+34 600111222»: a number, maybe with a unit word.
_NUMERIC = re.compile(r"^[\d\s.,+()-]+(?:\s*[^\W\d_]{1,10})?$")


def _comparable(value: str) -> str:
    """What two values are compared by: a number without its unit («45 anys» = «45» =
    «45 years»), anything else letters and digits only."""
    text = _fold(value).strip()
    if text and re.search(r"\d", text) and _NUMERIC.match(text):
        return "".join(re.findall(r"\d+", text))
    return _squash(value)


#: The thing is a pet. Its NAME is the user's pets' value; its age or breed is another fact.
_PET_NAME_WORDS = frozenset({"name", "nom", "nombre", "pet_name", "pets", "pet", "dog", "cat", "gos", "gat", "mascota"})
_PET_ENTITIES = frozenset({"dog", "gos", "gossa", "perro", "cat", "gat", "gata", "gato", "pet", "mascota", "horse", "cavall"})


@dataclass
class KeyedFact:
    entity: str
    attribute: str
    value: str
    statement: str
    intent: str

    @property
    def key(self) -> tuple:
        entity = _slug(self.entity) or "user"
        entity = "user" if entity in {"user", "me", "i", "myself", "usuari", "usuario", "speaker"} else entity
        slug = _slug(self.attribute)
        if entity in _PET_ENTITIES and (slug in _PET_NAME_WORDS or not slug):
            return "user", "pets"  # «el gos es diu X»: the name is the value of the user's pets
        if entity == "user" and slug not in _ALIASES and set(slug.split("_")) & _PET_NAME_WORDS:
            return "user", "pets"  # «dog_name», «pet_name_current»: still the user's pets
        return entity, _ALIASES.get(slug, slug)

    @property
    def multi(self) -> bool:
        return self.key[1] in _MULTI

    @property
    def value_norm(self) -> str:
        return _comparable(self.value)

    def metadata(self) -> dict:
        entity, attribute = self.key
        return {
            "type": "user_fact", "source": "keyed_extract", "is_mem_save": True,
            "entity": entity, "attribute": attribute, "value": self.value, "value_norm": self.value_norm,
            "cardinality": "multi" if self.multi else "single",
        }


def parse(raw: str) -> Optional[List[KeyedFact]]:
    """The facts a reply holds; None when it is not the JSON asked for."""
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    items = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    out: List[KeyedFact] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent") or "set").lower()
        out.append(KeyedFact(
            entity=str(item.get("entity") or "user"), attribute=str(item.get("attribute") or ""),
            value=str(item.get("value") or "").strip(), statement=str(item.get("statement") or "").strip(),
            intent=intent if intent in {"set", "change", "delete"} else "set",
        ))
    return out


def _words(text: str) -> set:
    return {w.strip(".") for w in re.split(r"[^a-z0-9@.]+", _fold(text)) if w.strip(".")}


def _in_message(value: str, message: str) -> bool:
    """The value is in the user's own words: written there as it is, or made only of
    words written there (the model may keep a word around it: «gos Tro»)."""
    flat = _squash(value)
    if not flat:
        return False
    return flat in _squash(message) or _words(value) <= _words(message)


def grounded(facts: List[KeyedFact], message: str) -> List[KeyedFact]:
    """Drop what the message does not hold: a value the user never wrote is an invention.

    A delete may carry no value; every other fact needs a value, an attribute and a
    sentence, and the value must be in the user's own words.
    """
    kept = []
    for fact in facts:
        if not fact.key[1]:
            continue
        if fact.intent == "delete":
            kept.append(fact)
            continue
        if _in_message(fact.value, message) and len(fact.statement) >= 5:
            kept.append(fact)
        else:
            logger.info("keyed extract: dropped a fact whose value is not in the message")
    return kept


def _call_kwargs(sig, system: str, message: str) -> Dict[str, Any]:
    """The arguments `engine.chat` takes for this one short call, whichever engine it is."""
    params = sig.parameters if sig is not None else {}
    kwargs: Dict[str, Any] = {"stream": True, "thinking_enabled": False}
    if "system" in params:  # in-process engines (MLX) take the system prompt apart
        kwargs["messages"] = [{"role": "user", "content": message}]
        kwargs["system"] = system
        if "session_id" in params:
            kwargs["session_id"] = "memory-extract"  # its own KV cache, not the conversation's
    else:
        kwargs["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": message}]
    if "model" in params:
        kwargs["model"] = ""  # the caller fills in the model name
    if "response_schema" in params:  # Ollama: the engine enforces the shape
        kwargs["response_schema"] = EXTRACT_SCHEMA
    return kwargs


async def _drain(gen) -> str:
    """The text of whatever `engine.chat` returned: an async generator of chunks (Ollama),
    a coroutine of a dict (MLX) or a plain result."""
    from core.endpoints.chat_engines._common import extract_engine_text  # deferred: heavy module

    if inspect.isasyncgen(gen) or hasattr(gen, "__aiter__"):
        raw = ""
        async for chunk in gen:
            if isinstance(chunk, dict) and "message" in chunk:
                raw += chunk["message"].get("content", "")
            elif isinstance(chunk, dict):
                raw += chunk.get("content", chunk.get("response", "") or "")
            elif isinstance(chunk, str):
                raw += chunk
        return raw
    return extract_engine_text(await gen if inspect.iscoroutine(gen) else gen)


async def _call(engine, model_name: str, sig, message: str, system: str = EXTRACT_SYSTEM) -> str:
    """One short, non-streaming call to the engine that answered the turn."""
    kwargs = _call_kwargs(sig, system, message)
    if "model" in kwargs:
        kwargs["model"] = model_name
    return await _drain(engine.chat(**kwargs))


def known_hint(known: List[dict]) -> str:
    """The keys already in memory, as a line for the prompt: the same thing must get the
    same name every time, or a change would look like a new fact."""
    pairs = []
    for row in known:
        label = f"{row['entity']}.{row['attribute']}"
        pairs.append(f"{label} = {row['value']}" if row.get("value") else label)
    if not pairs:
        return ""
    return (" Attribute names already in use for this user (use the same name when the message is about the same thing): "
            + "; ".join(pairs[:20]) + ".")


async def extract(engine, model_name: str, sig, message: str, known: Optional[List[dict]] = None) -> Optional[List[KeyedFact]]:
    """The keyed facts of `message`, or None when the model could not be read (the
    caller then falls back to the model's own tags). One retry on a reply that is not JSON."""
    if engine is None or len((message or "").strip()) < 6:
        return None
    system = EXTRACT_SYSTEM + known_hint(known or [])
    for _attempt in range(2):
        try:
            facts = parse(await _call(engine, model_name, sig, message, system))
        except Exception as exc:  # noqa: BLE001 — the turn goes on without the second pass
            logger.info("keyed extract: the engine call failed (%s)", type(exc).__name__)
            return None
        if facts is not None:
            return grounded(facts, message)
        logger.info("keyed extract: the reply was not the JSON asked for (try %d)", _attempt + 1)
    return None


def uncovered(tags: List[str], facts: List[KeyedFact]) -> List[str]:
    """The model's own [MEM_SAVE] tags that no extracted fact accounts for.

    A tag is covered when it holds the value of one of the facts; the rest still
    go the old way — a fact the extractor missed must not be lost because it found
    another one (review 19/10).
    """
    values = [f.value_norm for f in facts if f.value_norm]
    return [t for t in tags if not any(v in _squash(t) or v in _comparable(t) for v in values)]


@dataclass
class KeyedOutcome:
    """What the pass did with this turn's message."""

    handled: bool = False  # the extractor ran and found facts: the tags it covers are not needed
    saved: int = 0
    kept: list = field(default_factory=list)
    #: The facts that are in memory because of this pass (for the message's stats).
    facts: list = field(default_factory=list)


async def stored_keyed(port) -> List[dict]:
    """Every stored fact that carries a key (payload read by scroll, no similarity)."""
    try:
        memory = await port.get_memory_api()
        if not memory:
            return []
        from core.memory_access import MEMORY_COLLECTION

        if not await memory.collection_exists(MEMORY_COLLECTION):
            return []
        points, _next = await memory.scroll(collection=MEMORY_COLLECTION, limit=500)
    except Exception as exc:  # noqa: BLE001 — without the list the pass still reads the message
        logger.debug("keyed: could not list the stored facts: %s", exc)
        return []
    rows = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        if payload.get("entity") and payload.get("attribute") and payload.get("text"):
            rows.append({"entity": payload["entity"], "attribute": payload["attribute"], "text": payload["text"],
                         "value": payload.get("value", ""), "value_norm": payload.get("value_norm", "")})
    return rows


def _row_for_text(rows: List[dict], text: str) -> Optional[dict]:
    from core.memory_facts.helper import same_fact  # deferred: helper imports intents

    return next((r for r in rows if same_fact(r["text"], text)), None)


def _noted(outcome: KeyedOutcome, text: str, *, saved: bool) -> None:
    outcome.kept.append(text)
    if saved:
        outcome.saved += 1
        outcome.facts.append(text)


async def _save_new(fact: KeyedFact, session, port, snapshot: List[dict], outcome: KeyedOutcome, rag_collections) -> None:
    """A key nobody holds: save it. Closeness may still say a stored fact is near."""
    result = await port.save_to_memory(
        content=fact.statement, session_id=session.id, metadata=fact.metadata(), collections=rag_collections,
    )
    if result.get("document_id"):
        _noted(outcome, fact.statement, saved=True)
    elif result.get("duplicate") and result.get("same", True):
        _noted(outcome, fact.statement, saved=False)
    elif result.get("duplicate") and result.get("similar_to"):
        if _row_for_text(snapshot, result["similar_to"]) is None:
            # A fact saved before keys existed: closeness (0.80) is all there is, as it always was.
            intents.arm_replace(session, result["similar_to"], fact.statement, fact.metadata())
            return
        # The close fact carries ANOTHER key (the sister's age, not the user's): closeness
        # proves nothing here, the key says it is a new fact.
        forced = await port.save_to_memory(
            content=fact.statement, session_id=session.id, metadata=fact.metadata(),
            collections=rag_collections, force=True,
        )
        if forced.get("document_id"):
            _noted(outcome, fact.statement, saved=True)


async def apply(facts: List[KeyedFact], session, port, *, rag_collections=None) -> KeyedOutcome:
    """Save what is new, skip what is already there, arm what changes.

    By key, never by similarity: the same value is nothing (also across languages),
    another value of a key that is already stored arms a change for the user's yes
    — a several-valued key (`pets`) too: a question can be answered no, a silent
    second dog cannot be taken back. The memory is read ONCE, before the facts of
    this message are written, so two facts of one message cannot meet each other.
    """
    outcome = KeyedOutcome(handled=True)
    snapshot = await stored_keyed(port)
    for fact in facts:
        if fact.intent == "delete":
            continue  # a delete is a conversation of its own (deletes.py), not this pass
        same_key = [r for r in snapshot if (r["entity"], r["attribute"]) == fact.key]
        hit = next((r for r in same_key if r["value_norm"] == fact.value_norm), None)
        if hit is not None:
            _noted(outcome, hit["text"], saved=False)
        elif same_key:
            intents.arm_replace(session, same_key[0]["text"], fact.statement, fact.metadata())
        else:
            await _save_new(fact, session, port, snapshot, outcome, rag_collections)
    return outcome
