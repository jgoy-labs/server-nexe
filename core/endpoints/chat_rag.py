"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_rag.py
Description: RAG context building and helpers for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import copy
import functools
import hashlib
import logging
import time
import unicodedata
from datetime import datetime
from typing import Any, Optional

from core.memory_access import (
    DOCS_COLLECTION,
    KNOWLEDGE_COLLECTION,
    MEMORY_COLLECTION,
    SYSTEM_COLLECTIONS,
)
from core.rag.source import RAGQuery
# ADR-008: a collection's tuned parameters live with the source that applies
# them (`core/rag/collections.py`), not here. The three thresholds are
# nonetheless re-exported from this module because they are a public surface:
# `core/endpoints/chat.py` imports them from here and lists them in its
# `__all__`, and the knowledge base documents the env vars behind them.
from core.rag.collections import (  # noqa: F401  (re-export, see above)
    RAG_DOCS_THRESHOLD,
    RAG_KNOWLEDGE_THRESHOLD,
    RAG_MEMORY_THRESHOLD,
    source_for,
)
from core.rag.profile import profile_hits
from core.rag.registry import registered_names

logger = logging.getLogger(__name__)

# #1004 / ADR-008 E2: RAG_SEARCHES and RAG_SEARCH_DURATION are written HERE,
# once per source per turn. They used to be written in `RAGModule.search`,
# which the server never called, so both series stayed at zero while the chat
# retrieved on every turn. Guarded (#1005): instrumentation must never take
# retrieval down with it, and says so out loud when it cannot load.
try:
    from core.metrics.registry import RAG_SEARCHES, RAG_SEARCH_DURATION
except ImportError as _metrics_exc:  # pragma: no cover - see test_1004
    RAG_SEARCHES = None  # type: ignore[assignment]
    RAG_SEARCH_DURATION = None  # type: ignore[assignment]
    logger.warning(
        "RAG metrics unavailable (%s): core_rag_searches_total and "
        "core_rag_search_duration_seconds will stay at zero; retrieval is unaffected",
        _metrics_exc,
    )

# The import succeeding is not the same as the write succeeding; see
# _record_search_metrics.
_metrics_write_failed_reported = False


def _record_search_metrics(source: str, elapsed_seconds: float) -> None:
    """Publish one source's search attempt to Prometheus (#1004, ADR-008 E2).

    Counted AND timed on both outcomes: the metrics carry only a `source`
    label, so a counter that dropped failures would under-report load exactly
    when the backend breaks, and a histogram that dropped them would lose the
    slow timeouts that are the point of a latency histogram. Same rule for
    both keeps `core_rag_search_duration_seconds_count` equal to
    `core_rag_searches_total`.

    Nothing here can reach the turn. It runs from a `finally`, where a raise
    would REPLACE the search's outcome — and the realistic trigger (adding a
    `status` label to the registry makes every `labels(source=...)` raise)
    touches no retrieval code at all. So the write is fenced, and a failure is
    reported once per process: it is deterministic (the same mismatch on every
    search) and a turn fires one search per source.
    """
    global _metrics_write_failed_reported
    if RAG_SEARCHES is None or RAG_SEARCH_DURATION is None:
        return
    try:
        RAG_SEARCHES.labels(source=source).inc()
        RAG_SEARCH_DURATION.labels(source=source).observe(elapsed_seconds)
    except Exception as exc:
        # Deliberately bare: whatever prometheus_client throws, the retrieval
        # that already ran must still be the answer.
        if not _metrics_write_failed_reported:
            _metrics_write_failed_reported = True
            logger.warning(
                "RAG metrics write failed for source %r: %s — "
                "core_rag_searches_total and core_rag_search_duration_seconds "
                "will stay flat until the process restarts; retrieval is "
                "unaffected. Not repeated for later searches.",
                source, exc,
            )


class _StampedHit:
    """A read-only view of a hit that could not take a `collection` itself
    (frozen, slotted, or a model that refuses unknown fields). Every other
    attribute reads through to the original."""

    __slots__ = ("_hit", "collection")

    def __init__(self, hit: Any, collection: str) -> None:
        object.__setattr__(self, "_hit", hit)
        object.__setattr__(self, "collection", collection)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_hit"), name)


def _stamp_collection(results: list, source_name: str) -> list:
    """Give every hit that lacks a `collection` the name of the source that
    returned it (ADR-008 D4, sealed at E2).

    Downstream reads `getattr(r, "collection", ...)` twice: the per-turn stats
    (`rag_items`, which showed "?") and the section a hit lands in. Stamping
    here, where the source is still known, fixes the first; the second is
    unchanged by design — a name that is not one of the system collections
    still lands in the knowledge section.

    The source's own objects are never mutated: a hit may be shared (a cache,
    a registered source's fixture), so the stamp goes on a shallow copy, or on
    a read-through view when the copy refuses the attribute. A hit that
    already names its collection is passed through untouched.
    """
    stamped = []
    for hit in results:
        existing = getattr(hit, "collection", None)
        if isinstance(existing, str) and existing:
            stamped.append(hit)
            continue
        try:
            clone = copy.copy(hit)
            setattr(clone, "collection", source_name)
            stamped.append(clone)
        except Exception:
            stamped.append(_StampedHit(hit, source_name))
    return stamped


async def _search_source(source: Any, memory: Any, query: RAGQuery) -> list:
    """Ask one source, and account for it: metrics on both outcomes, and the
    source's name on every hit that came back without one.

    A source that raises still propagates (the contract says it must not, and
    the orchestrator's degradation handles one that does) — only after the
    attempt has been counted and timed.
    """
    name = source.name()
    started = time.perf_counter()
    try:
        results = await source.search(memory, query)
    finally:
        _record_search_metrics(name, time.perf_counter() - started)
    return _stamp_collection(results, name)


@functools.lru_cache(maxsize=1)
def system_rag_limit() -> int:
    """How many results (across all collections, after dedup) make the
    context (F-D block 3 — ported from the UI route, which alone had this).

    RAM-derived: virtual_memory().total is invariant at runtime, so cache it
    instead of recomputing via psutil on every chat request.
    """
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        return 3 if ram_gb < 12 else 5
    except Exception:
        return 5


# MC-001's docs→knowledge→memory order (not SYSTEM_COLLECTIONS's docs→memory→
# knowledge, tuned for a different caller): all_results below keeps this
# order, and _build_context_from_results truncates to 5 — so this decides
# which sources get dropped first when a turn pulls in more than 5 hits.
_KNOWN_ORDER = {DOCS_COLLECTION: 0, KNOWLEDGE_COLLECTION: 1, MEMORY_COLLECTION: 2}


async def _discover_collection_names(memory: Any) -> list[str]:
    """Live collection names via list_collections(); SYSTEM_COLLECTIONS if that fails.

    #896: this is what makes a plugin's own collection show up in chat search
    without editing this file — the list used to be 3 hardcoded literals.
    The 3 known collections keep MC-001's fixed order; anything discovered
    beyond them (a plugin's own collection) is searched too, appended after.

    E1b (ADR-008): a REGISTERED source is searchable too, whether or not the
    store reports a collection by that name. Without this union a source could
    register and never be asked anything — and E3's document module is exactly
    the case that does not have to be a Qdrant collection to have something to
    say. The union also runs when discovery FAILED and we fell back to the
    system defaults: losing a registered source because Qdrant hiccuped would
    be the silent kind of degradation this file exists to avoid.
    """
    try:
        infos = await memory.list_collections()
        names = [getattr(info, "name", None) for info in infos] if isinstance(infos, (list, tuple)) else []
        names = [n for n in names if isinstance(n, str) and n]
    except Exception as list_err:
        logger.debug("RAG: collection discovery unavailable, using system defaults: %s", list_err)
        names = []
    names = names or list(SYSTEM_COLLECTIONS)
    names = list(dict.fromkeys([*names, *registered_names()]))
    return sorted(names, key=lambda n: (_KNOWN_ORDER.get(n, len(_KNOWN_ORDER)), n))

# RAG context labels per language (must match system prompt references)
_RAG_CONTEXT_LABELS = {
    "ca": {
        "docs": "DOCUMENTACIO DEL SISTEMA",
        "knowledge": "DOCUMENTACIO TECNICA",
        "memory": "MEMORIA DE L'USUARI",
    },
    "es": {
        "docs": "DOCUMENTACION DEL SISTEMA",
        "knowledge": "DOCUMENTACION TECNICA",
        "memory": "MEMORIA DEL USUARIO",
    },
    "en": {
        "docs": "SYSTEM DOCUMENTATION",
        "knowledge": "TECHNICAL DOCUMENTATION",
        "memory": "USER MEMORY",
    },
}


async def build_rag_context(
    last_user_msg: str,
    app_state: Any,
    server_lang: str,
    *,
    collections: Optional[list[str]] = None,
    limit: Optional[int] = None,
    threshold_override: Optional[float] = None,
) -> tuple[str, list[tuple[str, float]]]:
    """
    Build RAG context by asking every retrieval source (ADR-008) with MemoryAPI.

    Args:
        last_user_msg: The last user message to search for
        app_state: FastAPI app state
        server_lang: Server language code (e.g. "ca", "en")
        collections: F-D block 3 (ported from the UI's per-turn toggle) — when
            given, search ONLY these collection names instead of discovering
            everything. ``None`` (the default) searches everything, same as
            before this parameter existed.
        limit: how many results (after dedup) make the context. ``None``
            defaults to :func:`system_rag_limit` (RAM-derived, ported from
            the UI, which alone had this before F-D block 3).
        threshold_override: F-D block 3 (ported from the UI's per-turn
            ``rag_threshold`` — a slider in app.js, also a CLI flag).
            Applies the same threshold to every collection. ``None`` (the
            default) keeps the 3 tuned per-collection thresholds.

    Returns:
        (context_text, rag_items) — rag_items is [(collection, score), ...]
        for the results actually used, for a caller that wants to show or
        save which sources answered (message stats, RAG toggle counts).
    """
    # NFKC-normalize the query to mirror the ingest path.
    # Documents are NFKC-normalized at ingest via MemoryService.remember().
    # Single normalization here covers the three downstream memory.search() calls.
    last_user_msg = unicodedata.normalize("NFKC", last_user_msg)

    context_text = ""
    rag_items: list[tuple[str, float]] = []

    try:
        try:
            from memory.memory.api.v1 import get_memory_api
            memory = await get_memory_api()

            # F-D block 3: an explicit toggle searches only those collections;
            # #896's discovery (a plugin's own collection included) stays the
            # default when no toggle narrows it. `is not None` (not truthiness):
            # an empty list means "the user disabled every source", which must
            # search nothing — not fall through to "no restriction" (privacy
            # regression: personal_memory would answer despite the toggle).
            names = list(collections) if collections is not None else await _discover_collection_names(memory)
            # ADR-008: one source per collection. Each one carries its own
            # threshold, top_k, language filter and existence guard; what is
            # left here is everything that spans them.
            sources = [source_for(name) for name in names]

            # MC-001: embed the (already NFKC-normalized) query ONCE and reuse it
            # for every collection instead of recomputing the identical embedding
            # three times. Falls back to per-search embedding if this fails.
            query_embedding = None
            try:
                query_embedding = await memory.embed_query(last_user_msg)
            except Exception as emb_err:
                logger.debug("RAG: query embedding precompute unavailable: %s", emb_err)

            # One question, asked of every source: prepared once so no source
            # can normalize, re-embed or re-read the override differently.
            query = RAGQuery(
                text=last_user_msg,
                lang=server_lang,
                embedding=query_embedding,
                threshold_override=threshold_override,
            )

            # MC-001: run the per-collection searches concurrently (was serial).
            # gather preserves argument order, so all_results keeps the original
            # docs→knowledge→memory ordering that dedup/context rely on.
            per_collection = await asyncio.gather(*(
                _search_source(source, memory, query) for source in sources
            ))
            all_results: list = []
            for results in per_collection:
                all_results.extend(results)

            all_results, profile = await _with_stated_facts(memory, names, all_results)

            if all_results or profile:
                _effective_limit = limit if limit is not None else system_rag_limit()
                unique = _deduplicate_results(all_results)[:_effective_limit]
                context_text = _format_results([*unique, *profile], server_lang)
                rag_items = [(getattr(r, "collection", "?"), getattr(r, "score", 0.0)) for r in unique]
                logger.info(
                    "RAG Context found (MemoryAPI): %d chars, %d results, %d stated facts",
                    len(context_text), len(unique), len(profile),
                )
        except Exception as mem_err:
            # #899: this is where `_rag_module_fallback` used to run (the legacy RAG,
            # PersonalityRAG), which ADR-002:68 already describes as structurally
            # empty: it always returned "" and its only signal was the WARNING
            # B114 added so the dead path was audible. The path is gone,
            # the signal stays — what mattered was not the fallback but that
            # the turn is answered WITH NO CONTEXT and that cannot pass in silence.
            # It now fires whenever MemoryAPI fails, not only when a
            # `rag` module was registered.
            logger.warning(
                "RAG: no context this turn — MemoryAPI unavailable: %s", mem_err,
            )

    except Exception as e:
        logger.error("RAG Error: %s", e, exc_info=True)
        # Continue without context rather than failing

    return context_text, rag_items


# ─── Private helpers ─────────────────────────────────────────────────────────


async def _with_stated_facts(memory: Any, names: list, results: list) -> tuple[list, list]:
    """(results without the memory hits the profile already says, the profile).

    What the user stated about themselves is LISTED, not searched, and travels
    outside the hit limit (core/rag/profile.py). Only when the memory source is
    among the ones asked: a user who turned memory off for the turn gets no
    personal facts either.
    """
    if MEMORY_COLLECTION not in names:
        return results, []
    profile = await profile_hits(memory)
    if not profile:
        return results, []
    listed = {h.text for h in profile}
    kept = [
        r for r in results
        if not (getattr(r, "collection", None) == MEMORY_COLLECTION and getattr(r, "text", None) in listed)
    ]
    return kept, profile


def _has_text(r: Any) -> bool:
    """#1075: `SearchResult.text` is `Optional[str]`. A hit with no usable
    text has nothing to contribute to the context."""
    text = getattr(r, "text", None)
    return isinstance(text, str) and bool(text)


def _deduplicate_results(results: list) -> list:
    """Remove results with duplicate content (sha256 of the whole text).

    #1091: the key used to be the first 500 chars. The knowledge ingest puts
    `[Document: …]` + `[Abstract: …]` in front of every chunk, and a long
    abstract filled those 500 chars — two DIFFERENT chunks of one document
    hashed the same and the document gave at most one chunk per turn (336
    distinguishable chunks of the ca KB → 181). Only exact duplicates collapse
    now; for texts of 500 chars or fewer nothing changes.

    #1075: hits whose `text` is not a non-empty str are skipped (debug log)
    instead of raising, which used to cost the whole turn its context.
    """
    seen: set = set()
    unique = []
    for r in results:
        if not _has_text(r):
            logger.debug(
                "RAG: skipping hit with no text (collection=%s, id=%s)",
                getattr(r, "collection", "?"), getattr(r, "id", "?"),
            )
            continue
        h = hashlib.sha256(r.text.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(r)
    return unique


def _format_results(results: list, server_lang: str = "en") -> str:
    """Format already-deduplicated, already-limited results into labelled,
    per-collection sections.

    The system prompt (server.toml, ca/es/en) tells the model to look for
    [DOCUMENTACIO DEL SISTEMA]/[MEMORIA DE L'USUARI]/etc. — those section
    markers must actually be in the context, or the model can deny having
    information it does have. `_RAG_CONTEXT_LABELS` already carries these
    labels; the framing prose that CITES them lives behind the presentation
    port now (`core/context_presentation/`), shared by both doors.
    `[Font: source]` stays per-item inside each section for traceability.
    """
    labels = _RAG_CONTEXT_LABELS.get(server_lang, _RAG_CONTEXT_LABELS["en"])
    buckets: dict[str, list[str]] = {"docs": [], "knowledge": [], "memory": []}
    for r in results:
        # #1075: never write "None" into the context for a text-less hit.
        if not _has_text(r):
            continue
        collection = getattr(r, "collection", None)
        key = (
            "docs" if collection == DOCS_COLLECTION
            else "memory" if collection == MEMORY_COLLECTION
            else "knowledge"
        )
        metadata = getattr(r, 'metadata', None) or {}
        if key == "memory":
            # A stated fact is a line the user said, with WHEN — not a document
            # with a `[Font: web_ui]` the model cannot read (13/10: it saw no
            # origin for "tens 45 anys" and took it back). No date: no phrase.
            buckets[key].append(r.text + _stated_on(metadata, server_lang))
            continue
        source = metadata.get('source', 'unknown')
        buckets[key].append(f"[Font: {source}]\n{r.text}")
    # Memory first: if the budget has to cut the block, it cuts from the end,
    # and who the user is must outlive the documentation.
    sections = [
        f"[{labels[key]}]\n" + ("\n".join(buckets[key]) if key == "memory" else "\n\n".join(buckets[key]))
        for key in ("memory", "docs", "knowledge") if buckets[key]
    ]
    return "\n\n".join(sections)


_STATED_ON = {
    "ca": " (t'ho va dir l'usuari el {d})",
    "es": " (te lo dijo el usuario el {d})",
    "en": " (the user told you on {d})",
}


def _stated_on(metadata: dict, lang: str) -> str:
    """" (the user told you on 02/10/2026)" from the fact's own `created_at`,
    or "" when it has none or it is not a date. Never a guess."""
    raw = metadata.get("created_at") or metadata.get("saved_at")
    if not isinstance(raw, str):
        return ""
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        # Stored in UTC; the day the user lived it is the local one (00:30 CEST on the 3rd is the 2nd in UTC).
        day = (moment.astimezone() if moment.tzinfo else moment).date()
    except ValueError:
        return ""
    code = (lang or "en").split("-")[0].lower()
    shown = day.isoformat() if code not in ("ca", "es") else day.strftime("%d/%m/%Y")
    return _STATED_ON.get(code, _STATED_ON["en"]).format(d=shown)
