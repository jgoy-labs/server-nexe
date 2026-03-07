"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/utils/api_client.py
Description: Client HTTP simple per comunicar CLI amb Server Nexe.

www.jgoy.net
────────────────────────────────────
"""

import os
import json
import logging
import httpx
from typing import Dict, Any, AsyncGenerator, Optional
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
             self.api_key = "unconfigured"

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
            "X-Client-ID": "nexe-cli-0.8"
        }
        
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
        
        # Endpoint unificat de chat (TODO: confirmar ruta exacte a core.endpoints)
        # Assumim /v1/chat/completions compatible amb OpenAI o /v1/chat/generate
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
