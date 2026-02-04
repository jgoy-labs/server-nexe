"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/session_manager.py
Description: Gestor de sessions de xat per la UI web (memòria en RAM)

www.jgoy.net
────────────────────────────────────
"""

import uuid
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ChatSession:
    """Sessió de xat individual amb historial"""

    def __init__(self, session_id: str = None):
        self.id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.messages: List[Dict[str, str]] = []
        self.context_files: List[str] = []
        self.attached_document: Optional[Dict[str, str]] = None  # {"filename": "...", "content": "..."}

    def add_message(self, role: str, content: str):
        """Afegir missatge a l'historial"""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.last_activity = datetime.now()

    def add_context_file(self, filename: str):
        """Afegir fitxer al context de la sessió"""
        if filename not in self.context_files:
            self.context_files.append(filename)

    def attach_document(self, filename: str, content: str, chunks: List[str] = None):
        """Adjuntar document per al proper missatge (amb chunks si és gran)"""
        self.attached_document = {
            "filename": filename,
            "content": content[:3000],  # Primer tros per preview
            "chunks": chunks or [content],  # Tots els chunks
            "total_chars": len(content),
            "current_chunk": 0
        }
        self.last_activity = datetime.now()

    def get_next_chunk(self) -> Optional[Dict[str, any]]:
        """Obtenir el següent chunk del document adjuntat"""
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
        """Obtenir i netejar document adjuntat"""
        doc = self.attached_document
        self.attached_document = None
        return doc

    def has_attached_document(self) -> bool:
        """Comprovar si hi ha document adjuntat"""
        return self.attached_document is not None

    def clear_context_files(self):
        """Netejar tots els fitxers del context"""
        self.context_files.clear()
        self.attached_document = None

    def get_history(self) -> List[Dict[str, str]]:
        """Obtenir historial complet de missatges"""
        return self.messages.copy()

    def to_dict(self) -> dict:
        """Serialitzar sessió a dict"""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "message_count": len(self.messages),
            "context_files": self.context_files,
            "messages": self.messages,
            "attached_document": self.attached_document
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ChatSession':
        """Crear sessió des de dict"""
        session = cls(session_id=data.get("id"))
        session.created_at = datetime.fromisoformat(data.get("created_at"))
        session.last_activity = datetime.fromisoformat(data.get("last_activity"))
        session.messages = data.get("messages", [])
        session.context_files = data.get("context_files", [])
        session.attached_document = data.get("attached_document")
        return session


class SessionManager:
    """
    Gestor de sessions de xat.

    Característiques:
    - Múltiples sessions simultànies (memòria RAM)
    - Historial per sessió
    - Context de fitxers per sessió
    - Cleanup automàtic de sessions inactives (futur)
    """

    def __init__(self, storage_path: str = "storage/sessions"):
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, ChatSession] = {}
        self._load_sessions()

    def _load_sessions(self):
        """Carregar sessions del disc"""
        try:
            count = 0
            for file_path in self._storage_path.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        session = ChatSession.from_dict(data)
                        self._sessions[session.id] = session
                        count += 1
                except Exception as e:
                    logger.warning(f"Error loading session {file_path}: {e}")
            logger.info(f"Loaded {count} sessions from disk")
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    def _save_session_to_disk(self, session: ChatSession):
        """Guardar sessió a disc"""
        try:
            file_path = self._storage_path / f"{session.id}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save session {session.id}: {e}")

    def _delete_session_from_disk(self, session_id: str):
        """Eliminar sessió del disc"""
        try:
            file_path = self._storage_path / f"{session_id}.json"
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.error(f"Failed to delete session file {session_id}: {e}")

    def create_session(self, session_id: str = None) -> ChatSession:
        """Crear nova sessió de xat"""
        session = ChatSession(session_id)
        self._sessions[session.id] = session
        self._save_session_to_disk(session)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Obtenir sessió existent"""
        return self._sessions.get(session_id)

    def get_or_create_session(self, session_id: str = None) -> ChatSession:
        """Obtenir sessió o crear-ne una de nova"""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        return self.create_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Eliminar sessió"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._delete_session_from_disk(session_id)
            return True
        return False

    def list_sessions(self) -> List[dict]:
        """Llistar totes les sessions (metadata només)"""
        return [
            {
                "id": s.id,
                "created_at": s.created_at.isoformat(),
                "last_activity": s.last_activity.isoformat(),
                "message_count": len(s.messages),
                "context_files": s.context_files
            }
            for s in self._sessions.values()
        ]

    def cleanup_inactive(self, max_age_hours: int = 24) -> int:
        """
        Netejar sessions inactives (no implementat encara)

        Args:
            max_age_hours: Màxim temps d'inactivitat en hores

        Returns:
            Nombre de sessions eliminades
        """
        # TODO: Implementar si cal
        return 0


__all__ = ["SessionManager", "ChatSession"]
