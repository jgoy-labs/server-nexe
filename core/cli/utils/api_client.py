"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/cli/utils/api_client.py
Description: Simple HTTP client for CLI communication with Server Nexe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import logging
import codecs
import re
import httpx
from typing import Dict, Any, AsyncGenerator, Optional, Union
from pathlib import Path

logger = logging.getLogger(__name__)

# Configurable CLI timeout via environment variable
CLI_HEALTH_TIMEOUT = float(os.getenv('NEXE_CLI_HEALTH_TIMEOUT', '5.0'))


_SAVE_RE = re.compile(r"\[(?:MEM_SAVE|MEMORIA):\s*([^\]]+)\]", re.IGNORECASE)


class UiStreamReader:
    """/ui/chat's wire, read the way the web client reads it.

    Sentinels (\x00[NAME]\x00, \x00[NAME:value]\x00) become metadata even when
    a read splits them; the model's <think> block becomes reasoning (the core's
    one splitter, ADR-010); memory tags and section labels leave the answer
    (the core's one filter) and the saved facts are reported apart.
    """

    def __init__(self) -> None:
        from core.turn.reasoning import ReasoningSplitter
        from core.turn.text.tags import TagStreamFilter

        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""
        self._split = ReasoningSplitter()
        self._tags = TagStreamFilter(memory=True, labels=True)

    def _sentinels(self, text: str) -> "tuple[str, list[dict]]":
        buf, self._pending = self._pending + text, ""
        plain: list[str] = []
        metas: list[dict] = []
        i = 0
        while True:
            j = buf.find("\x00[", i)
            if j < 0:
                rest = buf[i:]
                if rest.endswith("\x00"):  # maybe the start of a sentinel
                    self._pending, rest = "\x00", rest[:-1]
                plain.append(rest)
                break
            plain.append(buf[i:j])
            k = buf.find("]\x00", j)
            if k < 0:
                self._pending = buf[j:]
                break
            name, _, value = buf[j + 2:k].partition(":")
            metas.append({"type": "metadata", name: value if _ else "1"})
            i = k + 2
        return "".join(plain).replace("\x00", ""), metas

    def _items(self, reasoning: str, answer: str, final: bool = False) -> list:
        items: list = []
        if reasoning:
            items.append({"type": "reasoning", "text": reasoning})
        clean = self._tags.feed(answer) + (self._tags.flush() if final else "")
        if clean:
            items.append(clean)
        return items

    def feed(self, chunk: bytes) -> list:
        plain, metas = self._sentinels(self._decoder.decode(chunk))
        return metas + self._items(*self._split.feed(plain))

    def close(self) -> list:
        plain, metas = self._sentinels(self._decoder.decode(b"", final=True))
        plain += self._pending.replace("\x00", "")
        self._pending = ""
        r1, a1 = self._split.feed(plain)
        r2, a2 = self._split.flush()
        items = metas + self._items(r1 + r2, a1 + a2, final=True)
        saved = [m.group(1).strip() for t in self._tags.dropped for m in _SAVE_RE.finditer(t)]
        if saved:
            items.append({"type": "memory_tags", "saved": saved})
        return items

class NexeAPIClient:
    """Client to interact with the Nexe Server API."""
    
    
    def __init__(self, base_url: Optional[str] = None):
        if base_url is None:
            from core.config import get_server_url
            base_url = os.environ.get("NEXE_API_BASE_URL", get_server_url())
        self.base_url = base_url.rstrip("/")
        
        # Load environment variables
        from dotenv import load_dotenv
        load_dotenv()
        
        # Get Key (Support new dual-key or legacy)
        self.api_key = os.getenv("NEXE_PRIMARY_API_KEY") or os.getenv("NEXE_ADMIN_API_KEY")
        
        if not self.api_key:
             # Fallback warning but don't crash yet
             logging.warning("No API Key found involved. CLI might fail.")

        self.headers = {
            "Content-Type": "application/json",
            "X-Client-ID": "nexe-cli-0.9"
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            self.headers["x-api-key"] = self.api_key
        
    async def is_server_running(self) -> bool:
        """Check whether the server is running."""
        try:
            async with httpx.AsyncClient(timeout=CLI_HEALTH_TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


    async def upload_file(self, file_path: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Upload a file to the session via /ui/upload (multipart form)."""
        url = f"{self.base_url}/ui/upload"
        # No Content-Type header for multipart (httpx generates it automatically)
        headers = {k: v for k, v in self.headers.items() if k.lower() != "content-type"}
        try:
            with open(file_path, "rb") as f:
                content = f.read()
        except Exception as e:
            logger.error("Cannot read file %s: %s", file_path, e)
            return None

        filename = Path(file_path).name
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    url,
                    data={"session_id": session_id},
                    files={"file": (filename, content)},
                    headers=headers,
                )
                if response.status_code == 200:
                    return response.json()
                logger.error("Upload error %s: %s", response.status_code, response.text)
                return None
            except Exception as e:
                logger.error("Upload request error: %s", e)
                return None

    async def create_ui_session(self) -> Optional[str]:
        """Create a new session in the server UI pipeline."""
        url = f"{self.base_url}/ui/session/new"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json={}, headers=self.headers)
                if response.status_code == 200:
                    return response.json().get("session_id")
            except Exception as e:
                logger.error("Create session error: %s", e)
        return None

    async def chat_ui_stream(self, message: str, session_id: str, *,
                             rag_threshold: Optional[float] = None,
                             rag_collections: Optional[list] = None) -> AsyncGenerator[Union[str, dict], None]:
        """
        Send a streaming request to /ui/chat (same pipeline as the web UI).
        Uses server sessions, personal_memory RAG, and intent detection.

        Yields:
            str: the answer's text, clean — no <think>, memory tags or section
                labels (the web client strips the same things before painting)
            dict: {"type": "metadata", NAME: value} for every \x00[NAME:value]\x00
                sentinel (a sentinel without value gives "1"), even split
                across reads; {"type": "reasoning", "text": ...} for the model's
                reasoning; {"type": "memory_tags", "saved": [...]} at the end,
                the facts the model marked to remember.
        """
        url = f"{self.base_url}/ui/chat"
        payload = {"message": message, "session_id": session_id, "stream": True}
        if rag_threshold is not None:
            payload["rag_threshold"] = rag_threshold
        if rag_collections is not None:
            payload["rag_collections"] = rag_collections

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream("POST", url, json=payload, headers=self.headers) as response:
                    if response.status_code != 200:
                        error_msg = await response.aread()
                        yield f"Server error ({response.status_code}): {error_msg.decode()}"
                        return
                    reader = UiStreamReader()
                    async for chunk in response.aiter_bytes():
                        for item in reader.feed(chunk):
                            yield item
                    for item in reader.close():
                        yield item
            except httpx.ConnectError:
                yield "❌ Error: Could not connect to Nexe server. Make sure './nexe go' is running."

    async def memory_confirm_delete(self, fact: str, session_id: str) -> Dict[str, Any]:
        """Confirm the forget this session has pending — the web UI's dialog does
        the same POST. Since C4.5 the server deletes THE pending entry, by id;
        `fact` is the text it showed, the reference the confirmation names."""
        url = f"{self.base_url}/ui/memory/confirm-delete"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    url, json={"fact": fact, "session_id": session_id}, headers=self.headers,
                )
                if response.status_code == 200:
                    return response.json()
                logger.error("confirm-delete failed: HTTP %s", response.status_code)
            except Exception as e:
                logger.error("confirm-delete error: %s", e)
        return {}

    async def memory_cancel_delete(self, session_id: str) -> bool:
        """Refuse the forget this session has pending (#1136) — the web UI's
        «Cancel·la» does the same POST. Without it the delete stayed armed and
        a bare "sí" next turn still ran it. Returns whether one was pending."""
        url = f"{self.base_url}/ui/memory/cancel-delete"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, json={"session_id": session_id}, headers=self.headers)
                if response.status_code == 200:
                    return bool(response.json().get("cancelled"))
                logger.error("cancel-delete failed: HTTP %s", response.status_code)
            except Exception as e:
                logger.error("cancel-delete error: %s", e)
        return False

    async def memory_store(self, content: str, metadata: Optional[Dict] = None) -> bool:
        """Store content in RAG memory."""
        url = f"{self.base_url}/v1/memory/store"
        payload = {
            "content": content,
            "metadata": metadata or {"source": "chat-cli"}
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers)
                return response.status_code in (200, 201)
            except Exception as e:
                logger.error("Memory store error: %s", e)
                return False

    async def memory_search(self, query: str, limit: int = 3) -> list:
        """Search RAG memory."""
        url = f"{self.base_url}/v1/memory/search"
        payload = {
            "query": query,
            "limit": limit
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload, headers=self.headers)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("results", [])
                return []
            except Exception as e:
                logger.error("Memory search error: %s", e)
                return []
