"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/write.py
Description: Writing a turn's facts to memory, for both doors (ADR-007 C3.3).

Two paths used to do this with different rules: the streaming one atomised with
the LLM and filtered with one junk regex, the JSON one had no atomiser, a
different junk regex, and the only "skip the first turn" guard. A fact was
therefore kept or dropped depending on which wire format the client asked for.

One filter (the union of both), one first-turn rule (applied everywhere), and a
coroutine instead of two async generators. It writes, and says what it kept
(`WriteOutcome.kept`, `note_kept`); the door's `emit` turns that into its own
wire — since 25/09 memory.write runs inline before `emit` again (ADR-007 §6
amended, #1098), so the turn that saved is the turn that says so.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import re as _re
import unicodedata as _unicodedata
from dataclasses import dataclass, field

from core.endpoints.chat_engines._common import extract_engine_text
from core.log_redact import redact_user_content

logger = logging.getLogger(__name__)

def memory_saves_enabled(rag_collections) -> bool:
    """False when the user disabled personal memory — MEM_SAVE must not persist.

    Belt-and-braces with the prompt note: even if the model still emits the
    tag, nothing is written while the collection is off.
    """
    return rag_collections is None or "personal_memory" in rag_collections

# ─── Junk MEM_SAVE patterns (compiled once) ───────────────────────────────────
_JUNK_PATTERNS_RE = _re.compile(
    r'(?i)(no\s+(coneix|s\.han|tinc|té|hi ha)|'
    r'no\s+s\.han\s+detectat|'
    r'busco\s+ajuda|necessit[oa]|'
    r'primera\s+interacci|'
    r'no\s+personal|sense\s+dades|'
    r"I\s+don.t\s+(know|have)|no\s+information|"
    r"first\s+interaction|not\s+personal|no\s+data|"
    r"no\s+previous|cannot\s+recall|"
    r'\[MEM_SAVE|ignore\s+(all\s+)?previous|'
    r'system\s+prompt|override\s+instruction)',
)

_MEMSAVE_JUNK_RE = _re.compile(
    r'(?i)(no\s+(coneix|s.han|tinc|té|hi ha)|'
    r'no\s+s.han\s+detectat|busco\s+ajuda|necessit[oa]|'
    r'primera\s+interacci|no\s+personal|sense\s+dades)',
)

# B126 v2 — contextual name guard (replaces the old blanket ban on name claims).
# The v1 ban ("el usuario se llama / l'usuari es diu / the user's name is" =
# always junk) contradicted the system prompt, whose canonical MEM_SAVE example
# for names uses EXACTLY that phrasing (personality/server.toml, all 3 langs):
# the model obeyed the prompt, the filter silently killed every real name, and
# only non-name facts (age, job…) survived — found live on the 2026-07-03
# Windows clean-install test ("El usuario tiene 40 años" saved, "Juan" never).
# Now a name claim is junk ONLY when the claimed name does not appear in any
# user message of the session — a fabricated name the user never typed is still
# dropped, which keeps the original B126 goal (fewer hallucinations persisted).
#
# Known accepted residuals (adversarial review 2026-07-03): (a) only the FIRST
# name token is verified — "es diu Maria José" persists whole if the user said
# just "Maria"; (b) names outside the Latin range of the class below (e.g.
# "Łukasz") produce no claim match and skip the guard — deliberate fail-open.
NAME_CLAIM_RE = _re.compile(
    r"(?i)(?:el\s+usuario\s+se\s+llama|l.usuari\s+es\s+diu|the\s+user.s\s+name\s+is|"
    r"se\s+llama|es\s+diu|name\s+is)\s+"
    r"(?:(?:En|Na|Don|Doña|Mr|Mrs|Ms)\s+)?"  # honorific, not the name itself
    r"([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’·\-]{1,39})"
)


def fold_accents(text: str) -> str:
    """Lowercase + strip combining marks: 'María' ≙ 'maria', 'Òscar' ≙ 'oscar'.

    LLMs canonicalize diacritics both ways (user types "maria", model emits
    "María" — or the reverse), so the name guard must compare accent-folded.
    """
    return "".join(
        ch
        for ch in _unicodedata.normalize("NFKD", text.lower())
        if not _unicodedata.combining(ch)
    )


def hallucinated_name(fact: str, user_text: str) -> bool:
    """True when ``fact`` claims a name the user never typed (B126 v2 guard).

    Accent-folded on both sides, and word-bounded so a hallucinated 'Ana' does
    not slip through because the user wrote 'semana'.
    """
    claim = NAME_CLAIM_RE.search(fact)
    if not claim:
        return False
    name = fold_accents(claim.group(1))
    haystack = fold_accents(user_text or "")
    return not _re.search(r"(?<!\w)" + _re.escape(name) + r"(?!\w)", haystack)


_ATOMIZER_SYSTEM = {
    "ca": "Ets un separador de fets. Separa el fet en fets atòmics, UN per línia. Si ja és atòmic, retorna'l tal com és. Mai afegeixis explicacions — sols els fets.",
    "es": "Eres un separador de hechos. Separa el hecho en hechos atómicos, UNO por línea. Si ya es atómico, devuélvelo tal cual. Nunca añadas explicaciones.",
    "en": "You are a fact splitter. Split the fact into atomic facts, ONE per line. If already atomic, return it as-is. Never add explanations.",
}

_CONJUNCTION_RE = _re.compile(r'\s+(?:i|y|and)\s+', _re.IGNORECASE)


def needs_atomising(fact: str) -> bool:
    """True when splitting this fact would actually cost an inference.

    The one place the rule lives: `atomize_fact_llm` guards itself with it, and
    `write_facts` asks BEFORE calling so it knows whether the turn paid for a
    call (#1061). Two copies of this regex would be two answers to "did we spend
    an LLM call", which is the very thing that went wrong.
    """
    return bool(_CONJUNCTION_RE.search(fact))


async def atomize_fact_llm(fact: str, engine, model_name: str, sig, lang: str = "ca") -> list:
    """LLM-based atomizer: splits a combined fact into atomic facts.

    Uses the already-loaded model with a minimal 2-message call.
    Falls back to [fact] unchanged if the LLM call fails or returns nothing useful.
    Only fires when the fact contains a conjunction ( i / y / and ).
    """
    if not needs_atomising(fact):
        return [fact]
    system = _ATOMIZER_SYSTEM.get(lang[:2], _ATOMIZER_SYSTEM["en"])
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": fact}]
    import inspect
    try:
        gen = engine.chat(model=model_name, messages=msgs, stream=True, thinking_enabled=False) \
              if 'model' in sig.parameters \
              else engine.chat(messages=msgs, stream=True, thinking_enabled=False)
        raw = ""
        # B088: Ollama chat() is sync and returns an async-generator of chunks.
        # MLX chat() is `async def` → calling it returns a coroutine that, when
        # awaited, yields a dict {"response": ...} (it doesn't stream without
        # stream_callback). Same pattern as the main non-streaming chat path.
        if inspect.isasyncgen(gen) or hasattr(gen, "__aiter__"):
            async for chunk in gen:
                if isinstance(chunk, dict) and "message" in chunk:
                    raw += chunk["message"].get("content", "")
                elif isinstance(chunk, dict):
                    raw += chunk.get("content", chunk.get("response", "") or "")  # type: ignore[operator]
                elif isinstance(chunk, str):
                    raw += chunk
        else:
            result = await gen if inspect.iscoroutine(gen) else gen
            raw = extract_engine_text(result)
        lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip() and len(ln.strip()) >= 5]
        if lines:
            logger.info("Atomizer split %s → %d facts", redact_user_content(fact), len(lines))
            return lines
    except Exception as e:
        logger.debug("Atomizer LLM failed (%s), keeping fact as-is", e)
    return [fact]

def filter_facts(facts: list, deleted_facts: list, user_text: str = "") -> list:
    """Filter atomized facts: remove empty, short, deleted, junk and
    hallucinated-name entries.

    ``user_text`` is the concatenated content of the session's user messages:
    a name claim (B126 v2, NAME_CLAIM_RE) is only kept when the claimed name
    actually appears there. Pure function — no side effects.

    Skips log at INFO (redacted): a legitimate fact silently rejected was
    exactly the invisible failure mode of the 2026-07-03 name bug.
    """
    filtered = []
    for fact in facts:
        fact = fact.strip()
        if not fact or len(fact) < 5:
            continue
        if deleted_facts and any(
            fact.lower() in d.lower() or d.lower() in fact.lower()
            for d in deleted_facts
        ):
            logger.info("MEM_SAVE skip (recently deleted): %s", redact_user_content(fact))
            continue
        if JUNK_RE.search(fact):
            logger.info("MEM_SAVE skip (junk): %s", redact_user_content(fact))
            continue
        if hallucinated_name(fact, user_text):
            logger.info(
                "MEM_SAVE skip (name not present in user messages): %s",
                redact_user_content(fact),
            )
            continue
        filtered.append(fact)
    return filtered


async def persist_facts(facts: list, port, session_id: str) -> int:
    """Save filtered facts to memory. Returns the count of actually saved facts."""
    saved, _kept = await persist_facts_kept(facts, port, session_id)
    return saved


async def persist_facts_kept(facts: list, port, session_id: str) -> tuple[int, list]:
    """Save filtered facts; return (newly saved, facts that are in memory now).

    A duplicate is already remembered, so it is in the second list — what the
    user is told was kept. A storage error is in neither: the one thing a
    door must never call "saved" is a fact that is not there (#1098).
    """
    saved_count = 0
    kept: list = []
    for fact in facts:
        try:
            result = await port.save_to_memory(
                content=fact,
                session_id=session_id,
                metadata={"type": "user_fact", "source": "llm_extract", "is_mem_save": True},
            )
            if result.get("document_id"):
                saved_count += 1
                kept.append(fact)
                logger.info("MEM_SAVE: %s", redact_user_content(fact))
            elif result.get("duplicate"):
                # Legitimate no-op: the fact is already stored.
                kept.append(fact)
                logger.debug("MEM_SAVE skip (dedup): %s", redact_user_content(fact))
            else:
                # MC-016: a storage error is NOT a dedup skip — make it visible.
                logger.warning(
                    "MEM_SAVE failed (storage error): %s — %s",
                    redact_user_content(fact), result.get("message", "unknown"),
                )
        except Exception as e:
            # MC-016: an exception while saving must not be silently swallowed.
            logger.warning("MEM_SAVE failed (exception): %s", e)
    return saved_count, kept


#: One junk filter for both doors: the union of the streaming path's
#: `_JUNK_PATTERNS_RE` and the JSON path's `_MEMSAVE_JUNK_RE`. Every pattern of
#: both survives — a fact one door refused and the other stored was the bug.
#: Both source patterns carry a global `(?i)` flag, which Python only accepts
#: at the very start of an expression — concatenating them raises
#: `re.error: global flags not at the start`. The flag is stripped and applied
#: to the union instead, which is the same matching, once.
JUNK_RE = _re.compile(
    "(?:{})|(?:{})".format(
        _JUNK_PATTERNS_RE.pattern.replace("(?i)", "", 1),
        _MEMSAVE_JUNK_RE.pattern.replace("(?i)", "", 1),
    ),
    _re.IGNORECASE,
)


def note_kept(usage: dict, saved: int, kept: list) -> None:
    """Record on the turn what memory kept, for the door's `emit` (#1098).

    `usage["memory_saved"]` counts the facts stored new this turn;
    `usage["memory_kept"]` lists every fact that is in memory because of it
    (new or already there), once each. Both the intent step (D6) and
    `memory.write` add here, so a turn has ONE note — before 25/09 a D6 turn
    could carry two [MEM:n] with different meanings.
    """
    usage["memory_saved"] = usage.get("memory_saved", 0) + (saved or 0)
    listed = usage.setdefault("memory_kept", [])
    for fact in kept or []:
        if fact not in listed:
            listed.append(fact)


def is_first_turn(session) -> bool:
    """True on the turn that has only the user's opening message.

    A model that "remembers" something on the very first exchange is almost
    always hallucinating: there is nothing to remember yet. The JSON path has
    always dropped those; the streaming path never did.
    """
    user_msgs = [m for m in getattr(session, "messages", []) if m.get("role") == "user"]
    return len(user_msgs) <= 1


def user_text_of(session) -> str:
    """The haystack the name guard checks a claimed name against.

    User turns plus the compaction summary: compaction trims old turns
    (COMPACT_KEEP) but the running summary still carries salient facts.
    """
    text = " ".join(
        str(m.get("content", ""))
        for m in getattr(session, "messages", [])
        if m.get("role") == "user"
    )
    summary = getattr(session, "context_summary", None) or ""
    return f"{text} {summary}".strip()


#: Words every fact is made of, whoever it is about: sharing one of these with
#: the user's message proves nothing (ca/es/en).
_GENERIC_WORDS = frozenset({
    "usuari", "usuaria", "usuario", "user", "agrada", "agraden", "gusta", "gustan",
    "likes", "like", "loves", "prefereix", "prefiere", "prefers", "viu", "vive",
    "lives", "nom", "nombre", "name", "named", "called", "llama", "diu", "dice",
    "treballa", "trabaja", "works", "molt", "mucho", "very", "much", "vol", "quiere",
    "wants", "recordi", "recorda", "recuerda", "remember", "seva", "suya", "their",
    "teva", "tuya", "your", "aquest", "aquesta", "este", "esta", "this", "that",
    # function words of 3+ letters, present in almost any sentence
    "que", "qui", "del", "dels", "els", "les", "per", "pel", "amb", "una", "uns",
    "com", "son", "hola", "los", "las", "con", "por", "para", "como", "the", "and",
    "for", "with", "his", "her", "has", "have", "are", "was", "not", "you",
})
_WORD_RE = _re.compile(r"\w+", _re.UNICODE)


def grounded_in_user_text(fact: str, user_text: str) -> bool:
    """True when ``fact`` shares a telling word with what the user wrote.

    The opening-turn rule (25/09): a fact the user's own words back is kept
    ("em dic Aran i visc a Vic" → Aran, Vic); one the model brought is not —
    the prompt's example names (#831), an invented taste. Telling = a number,
    or 3+ letters and not a word every fact is made of. Accent-folded both
    sides, so "tè" matches "te" and "Àngel" matches "angel". If the user really
    is called Joan, "Joan" is in their words and the fact stays.
    """
    haystack = set(_WORD_RE.findall(fold_accents(user_text or "").lower()))
    for word in _WORD_RE.findall(fold_accents(fact or "").lower()):
        if word in _GENERIC_WORDS:
            continue
        if (word.isdigit() or len(word) >= 3) and word in haystack:
            return True
    return False


def _opening_turn_facts(facts: list, session) -> list:
    """The opening turn's facts that the user's own words back.

    25/09 (Jordi): "em dic Aran, recorda-ho" as the opening message used to be
    dropped whole. Keep what the user said; drop what the model brought (the
    prompt's example names, invented tastes).
    """
    user_text = user_text_of(session)
    grounded = [f for f in facts if grounded_in_user_text(f, user_text)]
    if len(grounded) < len(facts):
        logger.info(
            "MEM_SAVE skip (first turn, not in the user's words): %d fact(s) dropped",
            len(facts) - len(grounded),
        )
    return grounded


def will_write(facts: list, session, rag_collections=None, *, saved_by_intent: bool = False) -> bool:
    """Whether `write_facts` can store anything at all for this turn.

    The deterministic guards only — memory switched off, the intent step
    already owning this turn's fact — not the per-fact ones (junk, dedup, a
    hallucinated name, an opening turn's fact not in the user's words), which
    need the facts themselves. A door that
    shows a "saving…" indicator must ask this BEFORE showing it: the indicator
    is cleared by the [MEM:n] that never comes when the answer is "nothing to
    save", and the user is left with a spinner that spins forever
    (nexe-chat.js:749-767).
    """
    if not facts:
        return False
    if not memory_saves_enabled(rag_collections):
        return False
    return not saved_by_intent


@dataclass
class WriteOutcome:
    """What the write step did — the wire is somebody else's problem."""

    saved: int = 0
    facts: list = field(default_factory=list)
    #: The facts that are in memory after this write — newly stored or already
    #: there (dedup). The only list a door may show as "saved" (#1098).
    kept: list = field(default_factory=list)
    #: True only when at least one fact reached `engine.chat()` through the
    #: atomiser. It is NOT `bool(facts)`, and it is NOT `engine is not None`:
    #: a fact without a conjunction is stored as written and costs nothing
    #: (`needs_atomising`), so both doors used to bill an inference that never
    #: happened (#1061). `memory.write` reads this to gate `record_llm_call`.
    #: An attempt that reached the engine and then failed still counts — the
    #: turn paid for it.
    engine_called: bool = False


async def write_facts(
    facts: list,
    session,
    port,
    *,
    engine=None,
    model_name: str = "",
    sig=None,
    lang: str = "ca",
    rag_collections=None,
    saved_by_intent: bool = False,
) -> WriteOutcome:
    """Store this turn's facts. A coroutine: nothing here yields to a wire.

    `engine` enables the LLM atomiser ("X i Y" -> two facts); without one the
    facts are stored as the model wrote them, which is what the JSON path has
    always done.

    `saved_by_intent` is D6's turn (`IntentOutcome.saved_by_intent`): the fact
    was already handed to the port at the `intent` step, so everything the
    model then marks about it is a repetition — dropped here, at the one place
    both doors write through.
    """
    if not facts:
        return WriteOutcome()
    if not memory_saves_enabled(rag_collections):
        # Collection toggle belt-and-braces: the prompt already tells the model
        # not to emit MEM_SAVE with memory off; if it does, nothing persists —
        # and the drop is visible.
        logger.info(
            "MEM_SAVE skip (personal memory disabled by user): %d fact(s) dropped", len(facts),
        )
        return WriteOutcome()
    if saved_by_intent:
        # D6 (C3 review, 08/09): "recorda que X" saved X deterministically
        # before the model ran, and the model then marks its own paraphrase of
        # X. Past the opening turn the first-turn guard below is not there to
        # catch it and the 0.80 dedup does not see a paraphrase, so it landed
        # as a second entry for the same fact. Before the first-turn check so
        # the log names the real reason.
        logger.info(
            "MEM_SAVE skip (the intent step already saved this turn's fact, D6): %d fact(s) dropped",
            len(facts),
        )
        return WriteOutcome()
    if is_first_turn(session):
        facts = _opening_turn_facts(facts, session)
        if not facts:
            return WriteOutcome()

    candidates: list = []
    engine_called = False
    for raw in facts:
        raw = (raw or "").strip()
        if not raw:
            continue
        # Asked here, not left to the atomiser's own guard, because this is the
        # only place that knows whether the turn spent a call (#1061). A fact
        # with no conjunction reaches `atomize_fact_llm` only to come straight
        # back, so skipping it changes nothing but the bookkeeping.
        if engine is None or not needs_atomising(raw):
            candidates.append(raw)
            continue
        engine_called = True
        try:
            candidates.extend(await atomize_fact_llm(raw, engine, model_name, sig, lang=(lang or "ca")[:2]))
        except Exception:
            candidates.append(raw)

    filtered = filter_facts(candidates, getattr(session, "_recently_deleted_facts", []), user_text_of(session))
    saved, kept = await persist_facts_kept(filtered, port, session.id)
    return WriteOutcome(saved=saved, facts=filtered, kept=kept, engine_called=engine_called)
