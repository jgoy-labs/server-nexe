"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/session_manager.py
Description: Chat session manager for the web UI (RAM memory)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
import uuid
import json
import asyncio
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ChatSession:
    """Individual chat session with message history and automatic compaction."""

    # Compacting: cada COMPACT_EVERY missatges, resumeix els antics
    COMPACT_EVERY = 10          # Fallback: per nombre de missatges
    COMPACT_KEEP = 6
    MAX_CONTEXT_CHARS = 12000   # ~3000 tokens, safe per 4K-8K context models

    def __init__(self, session_id: str = None):
        self.id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now(timezone.utc)
        self.last_activity = datetime.now(timezone.utc)
        self.messages: List[Dict[str, str]] = []
        self.context_files: List[str] = []
        self.attached_document: Optional[Dict[str, str]] = None  # {"filename": "...", "content": "..."}
        self.context_summary: Optional[str] = None  # Resum dels missatges compactats
        self.compaction_count: int = 0  # Quantes vegades s'ha compactat
        self.custom_name: Optional[str] = None  # User-defined session name
        self.thinking_enabled: bool = False  # Per-session thinking toggle (default OFF)
        self._recently_deleted_facts: list = []  # Transient, not persisted to disk

    def add_message(self, role: str, content: str, stats: dict = None,
                    image_b64: str = None):
        """Afegir missatge a l'historial.

        `image_b64` (bug #19c): si l'usuari adjunta una imatge al missatge,
        es persisteix al mateix dict que el text per tal que reapareixi en
        recarregar la sessió. Es guarda NOMÉS si té valor — missatges de
        només text mantenen el format original al disc (backward compat).
        """
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if stats:
            msg["stats"] = stats
        if image_b64:
            msg["image_b64"] = image_b64
        self.messages.append(msg)
        self.last_activity = datetime.now(timezone.utc)

    def add_context_file(self, filename: str):
        """Add a file to the session context."""
        if filename not in self.context_files:
            self.context_files.append(filename)

    def attach_document(self, filename: str, content: str, chunks: List[str] = None, total_chunks: int = None):
        """Attach a document to the session.

        The document persists for the entire session for follow-up questions.
        Not indexed in any collection — available only within this chat.
        """
        all_chunks = chunks or [content]
        self.attached_document = {
            "filename": filename,
            "content": content[:3000],  # Preview
            "chunks": all_chunks,
            "total_chunks": total_chunks or len(all_chunks),  # Total real (pot diferir de len(chunks))
            "total_chars": len(content),
            "current_chunk": 0
        }
        self.last_activity = datetime.now(timezone.utc)

    def get_next_chunk(self) -> Optional[Dict[str, any]]:
        """Get the next chunk from the attached document"""
        if not self.attached_document:
            return None

        chunks = self.attached_document.get("chunks", [])
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

    def get_and_clear_attached_document(self) -> Optional[Dict[str, str]]:
        """Get the attached document (persists in the session for follow-up questions)."""
        return self.attached_document

    def has_attached_document(self) -> bool:
        """Comprovar si hi ha document adjuntat"""
        return self.attached_document is not None

    def clear_context_files(self):
        """Netejar tots els fitxers del context"""
        self.context_files.clear()
        self.attached_document = None

    def _estimate_context_chars(self) -> int:
        """Estimate total chars in context (rough proxy for tokens)."""
        total = len(self.context_summary or "")
        total += sum(len(m.get("content") or "") for m in self.messages)
        return total

    def needs_compaction(self) -> bool:
        """Return True if the session needs compaction (by token count or message count)."""
        if self._estimate_context_chars() > self.MAX_CONTEXT_CHARS:
            return True
        return len(self.messages) >= self.COMPACT_EVERY

    def get_messages_to_compact(self) -> List[Dict[str, str]]:
        """Return the older messages to be summarised (all except the last COMPACT_KEEP)."""
        if len(self.messages) <= self.COMPACT_KEEP:
            return []
        return self.messages[:-self.COMPACT_KEEP]

    def apply_compaction(self, summary: str):
        """Aplica compacting: guarda resum i elimina missatges antics"""
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
        """Obtenir missatges per enviar al model (amb resum si existeix).
        Garanteix que la seqüència de rols alterna user/assistant correctament.
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
        # Sanity check: drop consecutive duplicate roles to prevent VLM errors
        cleaned = []
        for m in msgs:
            if cleaned and cleaned[-1]["role"] == m["role"]:
                continue  # skip duplicate role
            cleaned.append(m)
        return cleaned

    def get_history(self) -> List[Dict[str, str]]:
        """Obtenir historial complet de missatges (per UI)"""
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
        if self.context_summary:
            d["context_summary"] = self.context_summary
            d["compaction_count"] = self.compaction_count
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'ChatSession':
        """Create a session from a dict."""
        session = cls(session_id=data.get("id"))
        session.created_at = datetime.fromisoformat(data.get("created_at"))
        session.last_activity = datetime.fromisoformat(data.get("last_activity"))
        session.messages = data.get("messages", [])
        session.context_files = data.get("context_files", [])
        session.attached_document = data.get("attached_document")
        session.custom_name = data.get("custom_name")
        session.thinking_enabled = data.get("thinking_enabled", False)
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
        # Bug 16: protegir accessos concurrents al dict _sessions.
        # Usem RLock (reentrant) perque alguns metodes en criden d'altres
        # tambe protegits (e.g. get_or_create_session -> create_session)
        # i aixi evitem deadlock per re-acquisicio.
        # Tot i que els metodes son sincrons, varies coroutines poden
        # cridar-los des de threadpools (FastAPI run_in_threadpool) i el
        # GIL no garanteix atomicity entre check + mutate (e.g.
        # `if id in dict: del dict[id]`).
        self._sessions_lock = threading.RLock()
        # Lock asyncio lazy: instanciat el primer cop que es necessita
        # (al __init__ pot no haver-hi loop encara, e.g. tests sync).
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
        """Lazy-init de l'asyncio.Lock per evitar requerir un loop al __init__."""
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
                        data_bytes = self._crypto.decrypt(file_path.read_bytes())
                        data = json.loads(data_bytes)
                        session = ChatSession.from_dict(data)
                        self._sessions[session.id] = session
                        count += 1
                    except Exception as e:
                        # Bug #19b: this is user data becoming invisible,
                        # not a routine warning. Escalate to ERROR and
                        # keep a counter for health observability.
                        self._corrupted_sessions_count += 1
                        logger.error(
                            "Error loading encrypted session %s: %s "
                            "(MEK mismatch or file corruption)",
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
        """Save session to disk (encrypted if crypto available, plain otherwise)."""
        self._validate_session_id(session.id)
        try:
            if self._crypto:
                file_path = self._storage_path / f"{session.id}.enc"
                plaintext = json.dumps(session.to_dict(), ensure_ascii=False).encode('utf-8')
                file_path.write_bytes(self._crypto.encrypt(plaintext))
            else:
                file_path = self._storage_path / f"{session.id}.json"
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save session %s: %s", session.id, e)

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

    def create_session(self, session_id: str = None) -> ChatSession:
        """Create a new chat session. (Bug 16: protegit per RLock)"""
        if session_id:
            self._validate_session_id(session_id)
        session = ChatSession(session_id)
        with self._sessions_lock:
            self._sessions[session.id] = session
            self._save_session_to_disk(session)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get an existing session. (Bug 16: protegit per RLock)"""
        self._validate_session_id(session_id)
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def save_session(self, session_id: str):
        """Persist a session to disk. (Bug 16: protegit per RLock)"""
        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session:
                self._save_session_to_disk(session)

    def get_or_create_session(self, session_id: str = None) -> ChatSession:
        """Get an existing session or create a new one.

        Bug 16: tot el check + create dins el mateix RLock per evitar
        race condition entre dues peticions concurrents que crearien
        dues sessions amb el mateix id.
        """
        if session_id:
            self._validate_session_id(session_id)
        with self._sessions_lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            # create_session reentra el lock (RLock) sense problema
            return self.create_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. (Bug 16: protegit per RLock)"""
        self._validate_session_id(session_id)
        with self._sessions_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self._delete_session_from_disk(session_id)
                return True
            return False

    def list_sessions(self) -> List[dict]:
        """List all sessions (metadata only). (Bug 16: snapshot dins RLock)"""
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
                "first_message": s.custom_name or (first_user[:60] if first_user else None)
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
