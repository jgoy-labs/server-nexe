"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/module.py
Description: Plugin UI web estil Ollama per demostrar el sistema modular de Nexe

www.jgoy.net
────────────────────────────────────
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus
from plugins.security.core.auth_config import get_admin_api_key

from .session_manager import SessionManager
from .file_handler import FileHandler
from .i18n import t

logger = logging.getLogger(__name__)


class WebUIModule:
    """
    Plugin UI web per Nexe.

    Característiques:
    - Interfície web estil Ollama
    - Sessions de xat amb historial
    - Upload de fitxers (.txt, .md, .pdf)
    - Streaming de respostes
    """

    def __init__(self):
        self._initialized = False
        self._router = None
        self.session_manager = SessionManager()
        self.file_handler = None
        self.static_dir = None
        self.api_base_url = "http://127.0.0.1:9119"

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="web_ui_module",
            version="0.8.0",
            description=t(
                "web_ui.metadata.description",
                "Ollama-style web UI to demonstrate the modular system"
            ),
            author="Jordi Goy",
            module_type="web_interface",
            quadrant="demo"
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Inicialització del plugin"""
        if self._initialized:
            return True

        try:
            self.api_base_url = self._resolve_api_base_url(context)
            # Determine paths
            plugin_dir = Path(__file__).parent
            self.static_dir = plugin_dir / "static"
            upload_dir = plugin_dir / "static" / "uploads"

            # Ensure directories exist
            self.static_dir.mkdir(parents=True, exist_ok=True)
            upload_dir.mkdir(parents=True, exist_ok=True)

            # Initialize file handler
            self.file_handler = FileHandler(upload_dir)

            # Initialize router
            self._init_router()

            self._initialized = True
            logger.info("WebUIModule initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize WebUIModule: {e}")
            return False

    def _init_router(self):
        """Crear routers de FastAPI"""
        self._router = APIRouter(prefix="/ui", tags=["ui", "web", "demo"])

        # Serve main UI
        @self._router.get("/", response_class=HTMLResponse)
        async def serve_ui():
            """Servir la pàgina principal"""
            html_path = self.static_dir / "index.html"
            if html_path.exists():
                return FileResponse(html_path)
            raise HTTPException(status_code=404, detail=t("web_ui.http.ui_not_found", "UI not found"))

        # Serve static files
        @self._router.get("/static/{filename}")
        async def serve_static(filename: str):
            """Servir CSS/JS"""
            file_path = self.static_dir / filename
            if file_path.exists() and file_path.suffix in {".css", ".js"}:
                return FileResponse(file_path)
            raise HTTPException(status_code=404, detail=t("web_ui.http.file_not_found", "File not found"))

        # Session management
        @self._router.post("/session/new")
        async def create_session():
            """Crear nova sessió"""
            session = self.session_manager.create_session()
            return {"session_id": session.id, "created_at": session.created_at.isoformat()}

        @self._router.get("/session/{session_id}")
        async def get_session_info(session_id: str):
            """Obtenir info de sessió"""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail=t("web_ui.http.session_not_found", "Session not found"))
            return session.to_dict()

        @self._router.get("/session/{session_id}/history")
        async def get_session_history(session_id: str):
            """Obtenir historial de sessió"""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail=t("web_ui.http.session_not_found", "Session not found"))
            return {"messages": session.get_history()}

        @self._router.delete("/session/{session_id}")
        async def delete_session(session_id: str):
            """Eliminar sessió"""
            deleted = self.session_manager.delete_session(session_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=t("web_ui.http.session_not_found", "Session not found"))
            return {"status": t("web_ui.session.deleted", "deleted")}

        @self._router.get("/sessions")
        async def list_sessions():
            """Llistar totes les sessions"""
            return {"sessions": self.session_manager.list_sessions()}

        # File upload
        @self._router.post("/upload")
        async def upload_file(
            file: UploadFile = File(...),
            session_id: Optional[str] = Form(None)
        ):
            """Pujar fitxer i afegir al context de la sessió"""
            # Validate file
            content = await file.read()
            valid, error = self.file_handler.validate_file(file.filename, len(content))
            if not valid:
                raise HTTPException(status_code=400, detail=error)

            # Save file
            file_path = await self.file_handler.save_file(file.filename, content)

            # Extract text
            text = self.file_handler.extract_text(file_path)
            if not text:
                self.file_handler.delete_file(file_path)
                raise HTTPException(status_code=400, detail=t("web_ui.http.extract_text_failed", "Could not extract text from file"))

            # Add to session context if session_id provided
            if session_id:
                session = self.session_manager.get_session(session_id)
                if session:
                    session.add_context_file(file.filename)

            return {
                "filename": file.filename,
                "size": len(content),
                "text_length": len(text),
                "preview": text[:500] + "..." if len(text) > 500 else text
            }

        # Chat endpoint
        @self._router.post("/chat")
        async def chat(request: Dict[str, Any]):
            """
            Endpoint de xat amb streaming

            Request:
            {
                "message": "user message",
                "session_id": "optional-session-id",
                "stream": true/false
            }
            """
            if not self._initialized:
                raise HTTPException(
                    status_code=503,
                    detail=t("web_ui.http.module_not_initialized", "Module not initialized")
                )

            message = request.get("message", "")
            session_id = request.get("session_id")
            stream = request.get("stream", False)

            if not message:
                raise HTTPException(status_code=400, detail="Message is required")

            # Get or create session
            session = self.session_manager.get_or_create_session(session_id)

            # Add user message to history
            session.add_message("user", message)

            if stream:
                async def generate():
                    async for chunk in self._stream_chat_response(session, request):
                        yield chunk

                return StreamingResponse(generate(), media_type="text/plain")
            else:
                response_text = await self._fetch_chat_response(session, request)
                session.add_message("assistant", response_text)
                return {
                    "response": response_text,
                    "session_id": session.id
                }

        # Health check
        @self._router.get("/health")
        async def health():
            """Health check del plugin"""
            return {
                "status": "healthy",
                "initialized": self._initialized,
                "sessions": len(self.session_manager.list_sessions())
            }

    def get_router(self) -> APIRouter:
        """Obtenir router de FastAPI"""
        return self._router

    def get_router_prefix(self) -> str:
        """Obtenir prefix del router"""
        return "/ui"

    async def health_check(self) -> HealthResult:
        """Health check del mòdul"""
        if not self._initialized:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="Module not initialized"
            )

        return HealthResult(
            status=HealthStatus.HEALTHY,
            message="Web UI active",
            details={
                "sessions": len(self.session_manager.list_sessions()),
                "static_dir": str(self.static_dir)
            }
        )

    async def shutdown(self) -> None:
        """Cleanup logic"""
        logger.info("WebUIModule shutting down")
        self._initialized = False

    def get_info(self) -> Dict[str, Any]:
        """Info del mòdul"""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "initialized": self._initialized,
            "sessions": len(self.session_manager.list_sessions())
        }

    def _resolve_api_base_url(self, context: Dict[str, Any]) -> str:
        env_url = os.getenv("NEXE_API_BASE_URL")
        if env_url:
            return env_url.rstrip("/")

        config = (context or {}).get("config", {}) or {}
        server_config = config.get("core", {}).get("server", {})
        host = server_config.get("host", "127.0.0.1")
        port = server_config.get("port", 9119)
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{port}"

    def _get_api_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = get_admin_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["x-api-key"] = api_key
        return headers

    def _build_chat_payload(self, session: "ChatSession", request: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "messages": [
                {"role": msg.get("role"), "content": msg.get("content")}
                for msg in session.get_history()
            ],
            "stream": bool(request.get("stream", False)),
            "use_rag": bool(request.get("use_rag", True)),
        }

        if request.get("engine"):
            payload["engine"] = request.get("engine")
        if request.get("model"):
            payload["model"] = request.get("model")
        if request.get("temperature") is not None:
            payload["temperature"] = request.get("temperature")
        if request.get("max_tokens") is not None:
            payload["max_tokens"] = request.get("max_tokens")

        return payload

    async def _fetch_chat_response(self, session: "ChatSession", request: Dict[str, Any]) -> str:
        payload = self._build_chat_payload(session, request)
        url = f"{self.api_base_url}/v1/chat/completions"
        headers = self._get_api_headers()

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("detail")
                except Exception:
                    detail = resp.text
                raise HTTPException(status_code=resp.status_code, detail=detail or "Chat request failed")

            data = resp.json()
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

    async def _stream_chat_response(self, session: "ChatSession", request: Dict[str, Any]):
        payload = self._build_chat_payload(session, request)
        payload["stream"] = True
        url = f"{self.api_base_url}/v1/chat/completions"
        headers = self._get_api_headers()
        full_response = ""

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    message = error_text.decode(errors="ignore")
                    yield f"❌ Error: {message}"
                    return

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        full_response += delta
                        yield delta

        if full_response:
            session.add_message("assistant", full_response)
