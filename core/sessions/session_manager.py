"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/sessions/session_manager.py
Description: Chat session manager — conversation threads live in core, not in any UI plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import re
import uuid
import json
import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.chat_history import merge_consecutive_same_role

logger = logging.getLogger(__name__)

#: C2.3 (ADR-007 §9): how long a granted lease is valid without a renewal —
#: until C2.5 measures a real per-engine deadline, at which point this
#: should become a function of it (2x, per the pla). A user turn releases its
#: lease at `emit` well before this could matter; the TTL exists for the
#: pathological case (a crashed worker, a process killed mid-turn) so a
#: session is never locked out forever.
DEFAULT_LEASE_TTL_S = 600.0

@dataclass
class LeaseResult:
    """Outcome of `SessionManager.acquire_lease`. `lease` is set whether
    granted (the lease just written) or refused (the one blocking it)."""

    granted: bool
    lease: Optional[Dict[str, str]]


class ChatSession:
    """Individual chat session with message history and automatic compaction."""

    # Compacting is decided by SIZE against the engine's real context window
    # (see needs_compaction). #965: it used to be decided by message COUNT —
    # COMPACT_EVERY = 10, i.e. five turns — with a 12000-char size check that in
    # practice never fired, because ten short messages are ~50 chars. So a
    # conversation of one-liners compacted every five turns on a machine whose
    # model could hold 32768 tokens.
    COMPACT_EVERY = 200         # Hard guard only, never the trigger
    COMPACT_KEEP = 6
    # Fraction of the window the history may take before we summarise. The rest
    # is the answer, the system prompt, RAG and any attached document — none of
    # which _estimate_context_chars() counts.
    #
    # MUST stay clearly below context_budget.PROMPT_BUDGET_RATIO, which caps the
    # whole prompt. Both were 0.7 at first: the history was then allowed to grow
    # to the entire prompt budget, so `available_chars` turned negative exactly
    # when a conversation reached compaction size and RAG and attached documents
    # were silently dropped — on every engine, at every window size. The gap
    # between the two ratios is what pays for the system prompt (~4700 chars),
    # the retrieved context and the user message.
    COMPACT_AT_RATIO = 0.45

    def __init__(self, session_id: str = None):  # type: ignore[assignment]  # no_implicit_optional
        self.id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now(timezone.utc)
        self.last_activity = datetime.now(timezone.utc)
        self.messages: List[Dict[str, str]] = []
        self.context_files: List[str] = []
        self.attached_document: Optional[Dict[str, Any]] = None  # {"filename": "...", "content": "..."}
        self.context_summary: Optional[str] = None  # Summary of compacted messages
        self.compaction_count: int = 0  # How many times it has been compacted
        self.custom_name: Optional[str] = None  # User-defined session name
        self.thinking_enabled: bool = False  # Per-session thinking toggle (default OFF)
        self.lang: Optional[str] = None  # #850: sticky reply language (seeded on 1st real detection)
        self.lang_pending: Optional[str] = None  # #850 hysteresis: candidate awaiting 2nd confirmation (transient)
        self.rag_collections: Optional[list] = None  # #851: last turn's toggles — continue has no body copy
        self._recently_deleted_facts: list = []  # Transient, not persisted to disk
        # C2.3 (ADR-007 §9, I9): the session's one live writer, if any —
        # {"holder", "turn_id", "where", "since", "expires"}. In-memory only,
        # NEVER read back by from_dict (see there): a lease that outlived the
        # process that granted it would be a lock nobody can ever release.
        self.lease: Optional[Dict[str, str]] = None

    def add_message(self, role: str, content: str, stats: dict = None,  # type: ignore[assignment]  # no_implicit_optional
                    image_b64: str = None, image_type: str = None,  # type: ignore[assignment]  # no_implicit_optional
                    partial: bool = False):
        """Add message to the history.

        `image_b64` (bug #19c): if the user attaches an image to the message,
        it is persisted in the same dict as the text so that it reappears when
        reloading the session. Saved ONLY if it has a value — text-only
        messages keep the original format on disk (backward compat).

        `image_type` (fix 2026-04-22): the MIME (`image/jpeg`, `image/png`…)
        is needed to reconstruct a valid `data:<mime>;base64,<b64>`
        in the frontend when the session is reloaded. Without it, Safari
        and some browsers cannot infer the format from the b64 and the
        image is not rendered.

        `partial` (#1040, C2.4): the reply broke mid-generation — the text
        saved is whatever reached the client before the error, not the
        model's complete answer. Saved ONLY if true, same backward-compat
        rule as `stats`/`image_b64`.
        """
        msg: Dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if stats:
            msg["stats"] = stats
        if image_b64:
            msg["image_b64"] = image_b64
            if image_type:
                msg["image_type"] = image_type
        if partial:
            msg["partial"] = True
        self.messages.append(msg)
        self.last_activity = datetime.now(timezone.utc)

    def add_context_file(self, filename: str):
        """Add a file to the session context."""
        if filename not in self.context_files:
            self.context_files.append(filename)

    def attach_document(self, filename: str, content: str, chunks: List[str] = None, total_chunks: int = None):  # type: ignore[assignment]  # no_implicit_optional
        """Attach a document to the session.

        The document persists for the entire session for follow-up questions.
        Not indexed in any collection — available only within this chat.
        """
        all_chunks = chunks or [content]
        self.attached_document = {
            "filename": filename,
            "content": content[:3000],  # Preview
            "chunks": all_chunks,
            "total_chunks": total_chunks or len(all_chunks),  # Real total (may differ from len(chunks))
            "total_chars": len(content),
            "current_chunk": 0
        }
        self.last_activity = datetime.now(timezone.utc)

    def get_next_chunk(self) -> Optional[Dict[str, Any]]:
        """Get the next chunk from the attached document"""
        if not self.attached_document:
            return None

        chunks: List[str] = self.attached_document.get("chunks", [])
        current = self.attached_document.get("current_chunk", 0)

        if current >= len(chunks):
            return None

        self.attached_document["current_chunk"] = current + 1
        return {
            "filename": self.attached_document["filename"],
            "chunk": chunks[current],
            "chunk_num": current + 1,
            "total_chunks": len(chunks),
            "is_last": current + 1 >= len(chunks)
        }

    def get_attached_document(self) -> Optional[Dict[str, str]]:
        """The document attached to this session, or None.

        C4.3: this used to be called `get_and_clear_attached_document` and it
        never cleared anything — the document persists for the whole session on
        purpose (see `attach_document`), so that follow-up questions can reach
        it. The name cost one analysis before it was renamed; `clear_context_files`
        is, and always was, the one that clears.
        """
        return self.attached_document

    def has_attached_document(self) -> bool:
        """Check if there is an attached document"""
        return self.attached_document is not None

    def clear_context_files(self):
        """Clear all files from the context"""
        self.context_files.clear()
        self.attached_document = None

    def _estimate_context_chars(self) -> int:
        """Estimate total chars in context (rough proxy for tokens)."""
        total = len(self.context_summary or "")
        total += sum(len(m.get("content") or "") for m in self.messages)
        return total

    def _estimate_context_tokens(self) -> int:
        """Rough token count of what the history will cost the model."""
        from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE
        return self._estimate_context_chars() // CHARS_PER_TOKEN_ESTIMATE

    def compaction_threshold_tokens(self, max_context_tokens: int = None) -> int:  # type: ignore[assignment]  # no_implicit_optional
        """Token count at which this session starts summarising its history.

        `NEXE_COMPACT_AT_TOKENS` overrides everything, for when you want to pin
        the number regardless of the engine.
        """
        explicit = os.environ.get("NEXE_COMPACT_AT_TOKENS")
        if explicit:
            try:
                value = int(explicit)
                if value > 0:
                    return value
                # 0 would mean "compact on every single turn", and compaction is
                # a full LLM summarisation in the critical path (~100 s on 8 GB).
                logger.warning(
                    "NEXE_COMPACT_AT_TOKENS=%r must be positive, sizing from the engine", explicit
                )
            except ValueError:
                logger.warning(
                    "NEXE_COMPACT_AT_TOKENS=%r is not a number, sizing from the engine instead",
                    explicit,
                )
        if not max_context_tokens or max_context_tokens <= 0:
            from core.endpoints.chat_sanitization import DEFAULT_CONTEXT_WINDOW
            max_context_tokens = DEFAULT_CONTEXT_WINDOW
        return int(max_context_tokens * self.COMPACT_AT_RATIO)

    def needs_compaction(self, max_context_tokens: int = None) -> bool:  # type: ignore[assignment]  # no_implicit_optional
        """Return True if the history should be summarised before the next turn.

        #965: decided by SIZE against the serving engine's real context window,
        not by message count. `max_context_tokens` is what that engine reported;
        without it the documented default window is used.

        The COMPACT_KEEP guard comes FIRST and is not a detail. `compact_session`
        summarises `get_messages_to_compact()`, which is empty at or below
        COMPACT_KEEP — so a session that is over the size threshold with six or
        fewer messages (one big pasted document, say) would answer True here
        forever, emit [WILL_COMPACT:1] on every single turn, and show the user
        "I am summarising the conversation" before a compaction that never
        happens. Saying True while there is nothing to compact is crying wolf.
        """
        if len(self.messages) <= self.COMPACT_KEEP:
            return False
        if self._estimate_context_tokens() > self.compaction_threshold_tokens(max_context_tokens):
            return True
        # Hard guard for the pathological case the size check cannot see: a very
        # long tail of tiny messages, each costing almost nothing but all of them
        # together making the history unwieldy.
        return len(self.messages) >= self.COMPACT_EVERY

    def get_messages_to_compact(self) -> List[Dict[str, str]]:
        """Return the older messages to be summarised (all except the last COMPACT_KEEP)."""
        if len(self.messages) <= self.COMPACT_KEEP:
            return []
        return self.messages[:-self.COMPACT_KEEP]

    def apply_compaction(self, summary: str, compacted_count: Optional[int] = None):
        """Apply compacting: save summary and remove old messages.

        `compacted_count` (C2.2): the exact number of leading messages the
        summary actually covers, from the caller's `get_messages_to_compact()`
        snapshot BEFORE its (possibly slow) LLM call. Compaction now runs in
        the background, off the critical path — a user turn can append a new
        message while the summarisation is in flight, and `self.messages` at
        apply time is no longer the same list that was measured. Keeping
        everything from `compacted_count` onward (instead of always "the last
        COMPACT_KEEP") is what keeps that new message from being silently
        dropped. `None` keeps the old behaviour (inline, synchronous callers,
        if any remain)."""
        if compacted_count is not None:
            keep = self.messages[compacted_count:]
        else:
            keep = self.messages[-self.COMPACT_KEEP:]
        # Ensure keep starts with user (summary prepend adds user+assistant, so
        # if keep[0] is assistant we'd get two consecutive assistant → VLM error)
        while keep and keep[0].get("role") != "user":
            keep = keep[1:]
        old_count = len(self.messages) - len(keep)
        self.context_summary = summary
        self.messages = keep
        self.compaction_count += 1
        logger.info(
            "Session %s: compacted %d messages (kept %d, compaction #%d)",
            self.id[:8], old_count, len(keep), self.compaction_count
        )

    def get_context_messages(self) -> List[Dict[str, str]]:
        """Get messages to send to the model (with summary if it exists).
        Guarantees that the role sequence alternates user/assistant correctly.
        """
        msgs = []
        if self.context_summary:
            msgs.append({
                "role": "user",
                "content": f"[Summary of previous conversation]\n{self.context_summary}"
            })
            msgs.append({
                "role": "assistant",
                "content": "Understood, I have the context from the previous conversation."
            })
        msgs.extend(self.messages)
        # Collapse consecutive duplicate roles (prevents VLM errors) using the
        # ONE canonical policy — #963: this layer used to keep the latest and
        # drop the rest (MC-116) while the engine merged them, two answers to
        # the same question with nothing saying which won. Merging is now the
        # decision, so no user text is lost on either path.
        return merge_consecutive_same_role(msgs)

    def get_history(self) -> List[Dict[str, str]]:
        """Get complete message history (for UI)"""
        return self.messages.copy()

    def to_dict(self) -> dict:
        """Serialise session to a dict."""
        d = {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "message_count": len(self.messages),
            "context_files": self.context_files,
            "messages": self.messages,
            "attached_document": self.attached_document,
        }
        if self.custom_name is not None:
            d["custom_name"] = self.custom_name
        d["thinking_enabled"] = self.thinking_enabled
        if self.lang is not None:
            d["lang"] = self.lang
        if self.rag_collections is not None:
            d["rag_collections"] = self.rag_collections
        if self.context_summary:
            d["context_summary"] = self.context_summary
            d["compaction_count"] = self.compaction_count
        if self.lease is not None:
            d["lease"] = self.lease
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'ChatSession':
        """Create a session from a dict.

        Deliberately does NOT read back `lease` even if a stray one made it
        to disk (this dict is also what `_save_session_to_disk` writes): a
        lease means "a writer is live right now, in THIS process" — one that
        outlived the process that granted it would be a lock nobody still
        running can ever release. Every session loads with `lease=None`.
        """
        session = cls(session_id=data.get("id"))  # type: ignore[arg-type]  # Any|None; session_id=None → UUID autogenerat (L34)
        _ca = data.get("created_at")
        session.created_at = datetime.fromisoformat(_ca) if _ca else datetime.now(timezone.utc)
        _la = data.get("last_activity")
        session.last_activity = datetime.fromisoformat(_la) if _la else datetime.now(timezone.utc)
        session.messages = data.get("messages", [])
        session.context_files = data.get("context_files", [])
        session.attached_document = data.get("attached_document")
        session.custom_name = data.get("custom_name")
        session.thinking_enabled = data.get("thinking_enabled", False)
        session.lang = data.get("lang")  # legacy .enc sense lang → None (re-seed al 1r torn)
        session.rag_collections = data.get("rag_collections")
        session.context_summary = data.get("context_summary")
        session.compaction_count = data.get("compaction_count", 0)
        return session


class SessionManager:
    """
    Chat session manager.

    Features:
    - Multiple simultaneous sessions (in-memory)
    - Per-session history
    - Per-session file context
    - Automatic cleanup of inactive sessions (future)
    """

    _SAFE_ID = re.compile(r'^[a-zA-Z0-9_-]+$')

    @classmethod
    def is_valid_session_id(cls, session_id) -> bool:
        """RT-10: public check for API boundaries — routes must reject bad ids
        with a clean 400 instead of letting _validate_session_id's ValueError
        bubble up as an unhandled 500."""
        return bool(session_id and isinstance(session_id, str) and cls._SAFE_ID.match(session_id))

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        """Validate session_id to prevent path traversal."""
        if not session_id or not SessionManager._SAFE_ID.match(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return session_id

    def __init__(self, storage_path: str = "storage/sessions", crypto_provider=None):
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._crypto = crypto_provider
        self._sessions: Dict[str, ChatSession] = {}
        # Bug #19b: expose count of .enc files that failed to decrypt at load.
        # Non-zero means the MEK has changed since those sessions were written
        # (Keychain reset, key rotation without migration, disk corruption).
        self._corrupted_sessions_count: int = 0
        # Bug 16: protect concurrent accesses to the _sessions dict.
        # We use RLock (reentrant) because some methods call others
        # that are also protected (e.g. get_or_create_session -> create_session)
        # and this avoids deadlock from re-acquisition.
        # Even though the methods are synchronous, multiple coroutines can
        # call them from threadpools (FastAPI run_in_threadpool) and the
        # GIL does not guarantee atomicity between check + mutate (e.g.
        # `if id in dict: del dict[id]`).
        self._sessions_lock = threading.RLock()
        # Lazy asyncio lock: instantiated the first time it is needed
        # (in __init__ there may not be a loop yet, e.g. sync tests).
        self._sessions_alock: Optional[asyncio.Lock] = None
        with self._sessions_lock:
            self._load_sessions()

    @property
    def corrupted_sessions_count(self) -> int:
        """Number of .enc files that failed to decrypt at last load.

        Exposed for /memory/health and debug endpoints — non-zero signals
        MEK divergence between a past run and the current process.
        """
        return self._corrupted_sessions_count

    def _get_async_lock(self) -> asyncio.Lock:
        """Lazy-init of the asyncio.Lock to avoid requiring a loop in __init__."""
        if self._sessions_alock is None:
            self._sessions_alock = asyncio.Lock()
        return self._sessions_alock

    def _load_sessions(self):
        """Load sessions from disk (encrypted .enc and/or plain .json)."""
        try:
            count = 0

            # Load encrypted sessions
            if self._crypto:
                for file_path in self._storage_path.glob("*.enc"):
                    try:
                        # B4 r4: AAD = filename stem binds ciphertext to its
                        # location. A swap attack (A.enc renamed to B.enc) makes
                        # the AAD passed here differ from the one used at
                        # encrypt() → AESGCM raises InvalidTag, caught below.
                        session_id = file_path.stem
                        aad = session_id.encode("utf-8")
                        data_bytes = self._crypto.decrypt(file_path.read_bytes(), aad=aad)
                        data = json.loads(data_bytes)
                        session = ChatSession.from_dict(data)
                        # Defense-in-depth: filename stem must match session.id
                        # in the payload. AAD already enforces this cryptographically
                        # for files written by 1.0.3-beta+, but the explicit check
                        # protects against future call-sites that forget to pass AAD.
                        if session.id != session_id:
                            self._corrupted_sessions_count += 1
                            logger.error(
                                "Session file %s contains session.id %s "
                                "(filename↔payload mismatch — possible swap attack)",
                                file_path.name, session.id,
                            )
                            continue
                        self._sessions[session.id] = session
                        count += 1
                    except Exception as e:
                        # Bug #19b: this is user data becoming invisible,
                        # not a routine warning. Escalate to ERROR and
                        # keep a counter for health observability.
                        # B4 r4: also catches AAD mismatch (swap attack or
                        # pre-1.0.3-beta sessions encrypted without AAD).
                        self._corrupted_sessions_count += 1
                        logger.error(
                            "Error loading encrypted session %s: %s "
                            "(MEK mismatch, AAD mismatch, or file corruption)",
                            file_path.name, e,
                        )

                # Migrate plain .json to .enc
                for file_path in self._storage_path.glob("*.json"):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        session = ChatSession.from_dict(data)
                        self._sessions[session.id] = session
                        self._save_session_to_disk(session)  # saves as .enc
                        file_path.unlink()  # remove plain .json
                        count += 1
                        logger.info("Migrated session %s from .json to .enc", session.id)
                    except Exception as e:
                        logger.warning("Error migrating session %s: %s", file_path.name, e)
            else:
                # Plain mode: load .json only
                for file_path in self._storage_path.glob("*.json"):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            session = ChatSession.from_dict(data)
                            self._sessions[session.id] = session
                            count += 1
                    except Exception as e:
                        logger.warning("Error loading session %s: %s", file_path.name, e)

            logger.info("Loaded %d sessions from disk", count)
        except Exception as e:
            logger.error("Failed to load sessions: %s", e)

    def _save_session_to_disk(self, session: ChatSession):
        """Save session to disk (encrypted if crypto available, plain otherwise).

        Production safety contract (added 2026-05-13 after empirical incident
        where 80 plaintext .json sessions appeared in storage/sessions/ on a
        production server because the SessionManager was constructed with
        crypto_provider=None — see core/sessions/attach.py and
        tests/plugins/web_ui_module/test_session_manager_proxy.py for the
        related regression chain).

        In production (NEXE_ENV=production, the default), refusing to silently
        write plaintext is the only correct behaviour: the operator opted in
        to encryption-at-rest at startup and the .json fallback would leak
        chat content to disk unencrypted.

        MC-014 — note on error handling: the production RuntimeError raised
        below is INTENTIONALLY caught by this method's own outer `except` and
        logged (critical for the refusal marker, error for the catch); it does
        NOT propagate to the caller. This is a redundant defense-in-depth
        barrier: the primary guard is attach_session_manager (called from
        lifespan after encryption), which aborts startup in production without
        crypto, so this branch is normally unreachable in production. The
        contract (logged + no plaintext file on disk, no exception bubbling up)
        is asserted by tests/.../test_session_manager_production_safety.py. The
        in-memory session is preserved either way (the dict assignment in
        create_session/update_session already happened by the time we get here).

        In development/test, keep the .json fallback so existing test fixtures
        and crypto-less local runs still work.
        """
        self._validate_session_id(session.id)
        try:
            if self._crypto:
                file_path = self._storage_path / f"{session.id}.enc"
                plaintext = json.dumps(session.to_dict(), ensure_ascii=False).encode('utf-8')
                # B4 r4: AAD = session.id binds the ciphertext to its filename.
                # _load_sessions() supplies file_path.stem as AAD; mismatch (swap
                # attack) raises InvalidTag and is logged as corrupted.
                aad = session.id.encode("utf-8")
                ciphertext = self._crypto.encrypt(plaintext, aad=aad)
                # Atomic write (MC-081): a crash/disk-full mid-write must NOT
                # truncate the .enc file. It's authenticated ciphertext — a
                # partial write makes the WHOLE session unrecoverable (InvalidTag)
                # at next load. chmod the tmp BEFORE the rename so no laxer-
                # permission window is ever exposed.
                self._atomic_write_bytes(file_path, ciphertext, chmod=0o600)
            else:
                import os as _os
                _env = _os.environ.get("NEXE_ENV", "production").lower()
                if _env == "production":
                    logger.critical(
                        "Refusing to write plaintext .json session %s in production "
                        "(crypto_provider missing). Encryption-at-rest is mandatory; "
                        "see core.lifespan_crypto and core.sessions.attach.",
                        session.id,
                    )
                    raise RuntimeError(
                        "SessionManager in production mode requires crypto_provider; "
                        "refusing to write plaintext session file."
                    )
                file_path = self._storage_path / f"{session.id}.json"
                # Atomic write (MC-081): same tmp+rename guard for the dev/test
                # plaintext fallback so a crash can't leave a zero-byte .json.
                self._atomic_write_bytes(
                    file_path,
                    json.dumps(session.to_dict(), indent=2, ensure_ascii=False).encode("utf-8"),
                )
        except Exception as e:
            logger.error("Failed to save session %s: %s", session.id, e)

    def _atomic_write_bytes(self, file_path: Path, data: bytes, *, chmod: Optional[int] = None) -> None:
        """Write *data* to *file_path* atomically (MC-081).

        Writes to a tmp file in the SAME directory, fsyncs it, then os.replace.
        A crash/kill/disk-full mid-write leaves the PREVIOUS file intact instead
        of a truncated one. Same-dir tmp makes the rename atomic on POSIX (no
        cross-device copy). On any failure the tmp is cleaned up.
        """
        import os as _os
        import tempfile as _tempfile

        tmp_path: Optional[Path] = None
        try:
            with _tempfile.NamedTemporaryFile(
                mode="wb",
                dir=file_path.parent,
                prefix=".session.",
                suffix=".tmp",
                delete=False,
            ) as fh:
                tmp_path = Path(fh.name)
                fh.write(data)
                fh.flush()
                _os.fsync(fh.fileno())
            if chmod is not None:
                try:
                    tmp_path.chmod(chmod)
                except OSError:
                    logger.warning("chmod %o failed on session tmp %s", chmod, tmp_path)
            _os.replace(tmp_path, file_path)
            tmp_path = None
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _delete_session_from_disk(self, session_id: str):
        """Delete session file from disk (.enc or .json)."""
        self._validate_session_id(session_id)
        try:
            for ext in (".enc", ".json"):
                file_path = self._storage_path / f"{session_id}{ext}"
                if file_path.exists():
                    file_path.unlink()
        except Exception as e:
            logger.error("Failed to delete session file %s: %s", session_id, e)

    def create_session(self, session_id: str = None) -> ChatSession:  # type: ignore[assignment]  # no_implicit_optional
        """Create a new chat session. (Bug 16: protected by RLock)"""
        if session_id:
            self._validate_session_id(session_id)
        session = ChatSession(session_id)
        with self._sessions_lock:
            self._sessions[session.id] = session
            self._save_session_to_disk(session)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get an existing session. (Bug 16: protected by RLock)"""
        self._validate_session_id(session_id)
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def save_session(self, session_id: str):
        """Persist a session to disk. (Bug 16: protected by RLock)"""
        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session:
                self._save_session_to_disk(session)

    def get_or_create_session(self, session_id: str = None) -> ChatSession:  # type: ignore[assignment]  # no_implicit_optional
        """Get an existing session or create a new one.

        Bug 16: all the check + create within the same RLock to avoid
        race condition between two concurrent requests that would create
        two sessions with the same id.
        """
        if session_id:
            self._validate_session_id(session_id)
        with self._sessions_lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            # create_session re-enters the lock (RLock) without problems
            return self.create_session(session_id)

    def acquire_lease(
        self, session_id: str, *, holder: str, turn_id: str, where: str,
        ttl_s: float = DEFAULT_LEASE_TTL_S, force: bool = False,
    ) -> LeaseResult:
        """One live writer per session (ADR-007 §9, I9, C2.3) — for USER
        holders only ("ui"/"api"). Atomic under the same RLock every other
        check-then-act on `_sessions` uses (#992).

        A background job (compact/memory.write) never calls this: it is
        already serialised against user turns by the `EngineGate` (C2.1/
        C2.2), and the caller checks `PostCommitQueue.running(session_id)`
        directly to decide whether to preempt one. This lease exists to stop
        TWO PEOPLE writing the same session at once, not to track background
        work — asymmetric rules for a holder that never competes for it
        would be complexity this minimal version does not need.

        - No session, or no current lease, or the current one expired, or
          it's a renewal (same `turn_id`): granted outright.
        - A live lease from a DIFFERENT turn: refused, with a copy of the
          lease that is blocking it (the caller needs `where`/`since` to
          tell the person) — UNLESS `force=True` (the explicit takeover a
          door asks for on the user's behalf after showing them the lease
          above: never automatic, never a side effect of a plain retry).
        """
        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session is None:
                # An id nobody has created yet — nothing to contend for; the
                # door that resolves/creates the session runs this check
                # right after, under the same lock (re-entrant).
                return LeaseResult(granted=True, lease=None)
            now = datetime.now(timezone.utc)
            current = session.lease
            if current is not None and not force:
                expires = datetime.fromisoformat(current["expires"])
                if expires > now and current["turn_id"] != turn_id:
                    return LeaseResult(granted=False, lease=dict(current))
            lease = {
                "holder": holder, "turn_id": turn_id, "where": where,
                "since": now.isoformat(),
                "expires": (now + timedelta(seconds=ttl_s)).isoformat(),
            }
            session.lease = lease
            return LeaseResult(granted=True, lease=dict(lease))

    def release_lease(self, session_id: str, turn_id: str) -> None:
        """Release the lease — only if `turn_id` is the one that holds it
        (a stale caller releasing after being preempted must not clear the
        NEW holder's lease). Silently a no-op otherwise: every release site
        (emit, the cancel path, a finished background job) calls this
        unconditionally, including when nothing was ever granted."""
        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session is None or session.lease is None:
                return
            if session.lease.get("turn_id") == turn_id:
                session.lease = None

    def renew_lease(self, session_id: str, turn_id: str, ttl_s: float = DEFAULT_LEASE_TTL_S) -> bool:
        """Push a live lease's expiry out — for a turn (or background job)
        that is taking longer than the default TTL. Returns whether `turn_id`
        actually held it; renewing a lease you do not hold is a no-op."""
        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session is None or session.lease is None or session.lease.get("turn_id") != turn_id:
                return False
            session.lease["expires"] = (datetime.now(timezone.utc) + timedelta(seconds=ttl_s)).isoformat()
            return True

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. (Bug 16: protected by RLock)

        Manual deletion (this method) had no log trail while the automatic
        cleanup_inactive() below does — an operator could not tell a session
        vanished by user action from one that was silently lost. Logged
        outside the lock: same reasoning as cleanup_inactive.
        """
        self._validate_session_id(session_id)
        with self._sessions_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self._delete_session_from_disk(session_id)
                deleted = True
            else:
                deleted = False
        if deleted:
            logger.info("Session %s deleted", session_id)
        return deleted

    def list_sessions(self) -> List[dict]:
        """List all sessions (metadata only). (Bug 16: snapshot within RLock)"""
        sessions = []
        with self._sessions_lock:
            sessions_snapshot = list(self._sessions.values())
        for s in sessions_snapshot:
            first_user = next(
                (m["content"] for m in s.messages if m.get("role") == "user"),
                None
            )
            sessions.append({
                "id": s.id,
                "created_at": s.created_at.isoformat(),
                "last_activity": s.last_activity.isoformat(),
                "message_count": len(s.messages),
                "context_files": s.context_files,
                "first_message": s.custom_name or (first_user[:60] if first_user else None),
                # C2.3: so a session list can show "open elsewhere" without a
                # second round-trip per session.
                "lease_holder": s.lease.get("holder") if s.lease else None,
                "lease_where": s.lease.get("where") if s.lease else None,
            })
        return sessions

    def cleanup_inactive(self, max_age_hours: int = 24) -> int:
        """
        Clean up inactive sessions.

        Args:
            max_age_hours: Maximum inactivity time in hours

        Returns:
            Number of removed sessions
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        with self._sessions_lock:
            expired_ids = [
                sid for sid, session in self._sessions.items()
                if session.last_activity < cutoff
            ]
            for sid in expired_ids:
                del self._sessions[sid]
                self._delete_session_from_disk(sid)
        if expired_ids:
            logger.info(
                "Cleaned %d inactive session(s) older than %dh",
                len(expired_ids), max_age_hours
            )
        return len(expired_ids)


__all__ = ["SessionManager", "ChatSession"]
