"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/api/routes.py
Description: Endpoints FastAPI del modul Ollama.
             Separat de manifest.py durant normalitzacio.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

from plugins.security.core.validators import validate_safe_path
from plugins.security.core.auth import require_api_key

logger = logging.getLogger(__name__)


class PullModelRequest(BaseModel):
    """Request per descarregar model"""
    name: str


def create_router(module_instance) -> APIRouter:
    """
    Crea el router FastAPI amb tots els endpoints d'Ollama.

    Args:
        module_instance: OllamaModule instance
    """
    router = APIRouter(prefix="/ollama")
    ui_path = Path(__file__).parent.parent / "ui"

    def _get_module():
        if module_instance is None:
            raise HTTPException(status_code=503, detail="OllamaModule not initialized")
        return module_instance

    # --- UI ---

    @router.get("/ui", response_class=HTMLResponse)
    async def serve_ui():
        """Serveix interficie web del chatbot Ollama."""
        index_path = ui_path / "index.html"
        if not index_path.exists():
            return HTMLResponse(content="<h1>Ollama UI not found</h1>", status_code=404)
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content)

    @router.get("/ui/assets/css/{path:path}")
    async def serve_css(path: str):
        """Serveix fitxers CSS"""
        css_base = ui_path / "assets" / "css"
        safe_path = validate_safe_path(css_base / path, css_base)
        return FileResponse(safe_path, media_type="text/css")

    @router.get("/ui/js/{path:path}")
    async def serve_js(path: str):
        """Serveix fitxers JavaScript"""
        js_base = ui_path / "js"
        safe_path = validate_safe_path(js_base / path, js_base)
        return FileResponse(safe_path, media_type="application/javascript")

    # --- Models ---

    @router.get("/api/models", dependencies=[Depends(require_api_key)])
    async def list_models():
        """Llista models locals d'Ollama."""
        module = _get_module()
        try:
            models = await module.list_models()
            return {"status": "ok", "total": len(models), "models": models}
        except Exception as e:
            logger.error("Failed to list Ollama models: %s", e)
            raise HTTPException(status_code=503, detail=f"Ollama connection failed: {str(e)}")

    @router.post("/api/pull")
    async def pull_model(request: PullModelRequest, _: str = Depends(require_api_key)):
        """Download Ollama model with streaming progress. Requires API key."""
        module = _get_module()

        async def progress_stream():
            try:
                async for progress in module.pull_model(request.name):
                    data = json.dumps(progress)
                    yield f"data: {data}\n\n"
            except Exception as e:
                logger.error("Pull model failed: %s", e)
                yield f"data: {json.dumps({'error': str(e), 'status': 'error'})}\n\n"

        return StreamingResponse(
            progress_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    @router.get("/api/models/{model_name}/info", dependencies=[Depends(require_api_key)])
    async def get_model_info(model_name: str):
        """Get detailed information about a model."""
        module = _get_module()
        try:
            info = await module.get_model_info(model_name)
            return {"status": "ok", "model": model_name, "info": info}
        except Exception as e:
            logger.error("Failed to get model info: %s", e)
            raise HTTPException(status_code=404, detail=f"Model not found or error: {str(e)}")

    @router.delete("/api/models/{model_name}")
    async def delete_model(model_name: str, _: str = Depends(require_api_key)):
        """Delete a local model. Requires API key."""
        module = _get_module()
        try:
            await module.delete_model(model_name)
            return {"status": "ok", "message": f"Model {model_name} deleted successfully"}
        except Exception as e:
            logger.error("Failed to delete model: %s", e)
            raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

    # --- Health & Info ---

    @router.get("/health", dependencies=[Depends(require_api_key)])
    async def health():
        """Health check del modul Ollama."""
        module = _get_module()
        result = await module.health_check()
        return result.to_dict()

    @router.get("/info", dependencies=[Depends(require_api_key)])
    async def info():
        """Informacio del modul Ollama."""
        module = _get_module()
        return module.get_info()

    return router
