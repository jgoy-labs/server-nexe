"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/utils/api_client.py
Description: Client HTTP simple per comunicar CLI amb Server Nexe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import json
import logging
import re
import httpx
from typing import Dict, Any, AsyncGenerator, Optional, Union
from pathlib import Path

logger = logging.getLogger(__name__)

# Configurable CLI timeout via environment variable
CLI_HEALTH_TIMEOUT = float(os.getenv('NEXE_CLI_HEALTH_TIMEOUT', '5.0'))

class NexeAPIClient:
    """Client per interactuar amb la API de Nexe Server."""
    
    
    def __init__(self, base_url: str = None):
        if base_url is None:
            base_url = os.environ.get("NEXE_API_BASE_URL", "http://127.0.0.1:9119")
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
            "X-Client-ID": "nexe-cli-0.8"
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            self.headers["x-api-key"] = self.api_key
        
    async def is_server_running(self) -> bool:
        """Comprova si el servidor està actiu."""
        try:
            async with httpx.AsyncClient(timeout=CLI_HEALTH_TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def chat_stream(
        self, 
        messages: list, 
        engine: str, 
        rag: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Fa request a /chat/completions amb streaming.
        
        Nota: Normalment OpenAI format usa /v1/chat/completions.
        Aquí assumim que Nexe exposa un endpoint similar o el router de xat unificat.
        """
        
        # OpenAI-compatible chat completions endpoint
        url = f"{self.base_url}/v1/chat/completions"
        
        payload = {
            "messages": messages,
            "engine": engine,
            "use_rag": rag,
            "stream": True,
            "temperature": 0.7 
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream("POST", url, json=payload, headers=self.headers) as response:
                    if response.status_code != 200:
                        error_msg = await response.aread()
                        yield f"Error del servidor ({response.status_code}): {error_msg.decode()}"
                        return

                    async for line in response.aiter_lines():
                        if not line or line.strip() == "":
                            continue
                        
                        # Format SSE: "data: {json}"
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            
                            try:
                                data = json.loads(data_str)
                                # Extreure content delta (compatible OpenAI)
                                delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield delta
                            except json.JSONDecodeError:
                                pass
            except httpx.ConnectError:
                yield "❌ Error: No s'ha pogut connectar al servidor Nexe. Assegura't que './nexe go' està corrent."

    async def upload_file(self, file_path: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Puja un fitxer a la sessió via /ui/upload (multipart form)."""
        url = f"{self.base_url}/ui/upload"
        # No Content-Type header per multipart (httpx el genera automàticament)
        headers = {k: v for k, v in self.headers.items() if k.lower() != "content-type"}
        try:
            with open(file_path, "rb") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Cannot read file {file_path}: {e}")
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
                logger.error(f"Upload error {response.status_code}: {response.text}")
                return None
            except Exception as e:
                logger.error(f"Upload request error: {e}")
                return None

    async def create_ui_session(self) -> Optional[str]:
        """Crea una nova sessió al pipeline UI del servidor."""
        url = f"{self.base_url}/ui/session/new"
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json={}, headers=self.headers)
                if response.status_code == 200:
                    return response.json().get("session_id")
            except Exception as e:
                logger.error(f"Create session error: {e}")
        return None

    # Regex for inline metadata markers: \x00[KEY:VALUE]\x00
    _MARKER_RE = re.compile(r'\x00\[(\w+):([^\]]*)\]\x00')
    _MEM_MARKER = "\x00[MEM]\x00"

    async def chat_ui_stream(self, message: str, session_id: str) -> AsyncGenerator[Union[str, dict], None]:
        """
        Fa request a /ui/chat (mateix pipeline que el UI web) amb streaming.
        Usa sessions servidor, RAG nexe_chat_memory, detecció d'intencions.

        Yields:
            str: text chunks
            dict: metadata markers (e.g. {"type": "metadata", "MODEL": "qwen3.5:2b"})
        """
        url = f"{self.base_url}/ui/chat"
        payload = {"message": message, "session_id": session_id, "stream": True}

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream("POST", url, json=payload, headers=self.headers) as response:
                    if response.status_code != 200:
                        error_msg = await response.aread()
                        yield f"Error del servidor ({response.status_code}): {error_msg.decode()}"
                        return
                    async for chunk in response.aiter_bytes():
                        text = chunk.decode("utf-8", errors="replace")

                        # Parse inline metadata markers
                        metadata = {}
                        for match in self._MARKER_RE.finditer(text):
                            metadata[match.group(1)] = match.group(2)
                        text = self._MARKER_RE.sub("", text)

                        # Parse MEM marker (no value)
                        if self._MEM_MARKER in text:
                            metadata["MEM"] = "1"
                            text = text.replace(self._MEM_MARKER, "")

                        if metadata:
                            yield {"type": "metadata", **metadata}
                        if text:
                            yield text
            except httpx.ConnectError:
                yield "❌ Error: No s'ha pogut connectar al servidor Nexe. Assegura't que './nexe go' està corrent."

    async def chat_offline(self, messages: list, engine: str) -> str:
        """Simulació offline si el server no hi és (no recomanat per CLI interactiu complex)."""
        return "❌ Offline mode not supported yet. Please run './nexe go' first."

    async def memory_store(self, content: str, metadata: Optional[Dict] = None) -> bool:
        """Guarda contingut a la memòria (RAG)."""
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
                logger.error(f"Memory store error: {e}")
                return False

    async def memory_search(self, query: str, limit: int = 3) -> list:
        """Cerca a la memòria (RAG)."""
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
                logger.error(f"Memory search error: {e}")
                return []
