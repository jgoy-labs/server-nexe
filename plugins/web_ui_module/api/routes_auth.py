"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_auth.py
Description: Endpoints d'autenticacio, info, backends i health.
             Extret de routes.py durant refactoring de tech debt.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from pathlib import Path
from typing import Dict, Any, Optional
import logging
import secrets
from fastapi import APIRouter, HTTPException, Depends, Header

from plugins.security.core.auth_config import get_admin_api_key
from plugins.web_ui_module.messages import get_message

logger = logging.getLogger(__name__)


def make_require_ui_auth():
    """Crea la dependencia FastAPI d'autenticacio per a la Web UI."""
    async def _require_ui_auth(x_api_key: Optional[str] = Header(None)):
        """Valida API key per a endpoints de la Web UI"""
        expected = get_admin_api_key()
        if expected and not secrets.compare_digest(x_api_key or "", expected):
            raise HTTPException(status_code=401, detail=get_message(None, "webui.auth.invalid_key"))
    return _require_ui_auth


def register_auth_routes(router: APIRouter, *, require_ui_auth, session_mgr):
    """Registra endpoints: /auth, /info, /backends, /backend, /health"""

    # -- GET /auth --

    @router.get("/auth")
    async def verify_auth(_auth=Depends(require_ui_auth)):
        """Verificar API key"""
        return {"status": "ok"}

    # -- GET /info --

    @router.get("/info")
    async def get_ui_info(_auth=Depends(require_ui_auth)):
        """Info del model i backend actiu"""
        import os
        model_name = os.getenv("NEXE_DEFAULT_MODEL", "unknown")
        backend = os.getenv("NEXE_MODEL_ENGINE", "auto")
        try:
            from core.lifespan import get_server_state
            version = get_server_state().config.get('meta', {}).get('version', '0.8')
        except Exception:
            version = "0.8"
        try:
            from core.lifespan import get_server_state
            lang = get_server_state().config.get('personality', {}).get('i18n', {}).get('default_language', 'en-US')
        except Exception:
            lang = "en-US"
        return {
            "model": model_name,
            "backend": backend,
            "version": version,
            "lang": lang.split('-')[0]
        }

    # -- GET /backends --

    @router.get("/backends")
    async def list_backends(_auth=Depends(require_ui_auth)):
        """Llista backends disponibles amb els seus models"""
        import os
        from core.lifespan import get_server_state

        module_manager = get_server_state().module_manager
        backends = []

        # Directori de models local
        models_dir = Path(os.getenv("NEXE_STORAGE_PATH", "storage")) / "models"
        if not models_dir.is_absolute():
            from core.lifespan import get_server_state
            root = Path(get_server_state().project_root)
            models_dir = root / models_dir

        # Ollama
        try:
            reg = module_manager.registry.get_module("ollama_module")
            if reg and reg.instance:
                engine = reg.instance
                if hasattr(engine, "get_module_instance"):
                    engine = engine.get_module_instance()
                if hasattr(engine, "list_models"):
                    models = await engine.list_models()
                    model_list = []
                    for m in models:
                        name = m.get("name", m.get("model", "?"))
                        size_bytes = m.get("size", 0)
                        size_gb = round(size_bytes / (1024**3), 1) if size_bytes else 0
                        model_list.append({"name": name, "size_gb": size_gb})
                    backends.append({"id": "ollama", "name": "Ollama", "models": model_list, "active": False})
        except Exception as e:
            logger.debug(f"Ollama backend scan failed: {e}")

        # MLX
        try:
            if models_dir.exists():
                mlx_list = []
                for d in models_dir.iterdir():
                    if d.is_dir():
                        # Sumar fitxers .safetensors per estimar mida
                        size = sum(f.stat().st_size for f in d.rglob("*.safetensors") if f.is_file())
                        mlx_list.append({"name": d.name, "size_gb": round(size / (1024**3), 1) if size else 0})
                if mlx_list:
                    backends.append({"id": "mlx", "name": "MLX", "models": mlx_list, "active": False})
        except Exception as e:
            logger.debug(f"MLX backend scan failed: {e}")

        # Llama.cpp - nomes mostrar si hi ha fitxers .gguf disponibles
        try:
            reg = module_manager.registry.get_module("llama_cpp_module")
            if reg and reg.instance:
                gguf_list = []
                if models_dir.exists():
                    for f in models_dir.iterdir():
                        if f.suffix == ".gguf":
                            size = f.stat().st_size
                            gguf_list.append({"name": f.name, "size_gb": round(size / (1024**3), 1) if size else 0})
                if gguf_list:
                    backends.append({"id": "llamacpp", "name": "Llama.cpp", "models": gguf_list, "active": False})
        except Exception as e:
            logger.debug(f"Llama.cpp backend scan failed: {e}")

        # Marcar actiu
        current_backend = os.getenv("NEXE_MODEL_ENGINE", "auto").lower()
        current_model = os.getenv("NEXE_DEFAULT_MODEL", "")
        for b in backends:
            if current_backend == b["id"] or (current_backend == "auto" and b == backends[0]):
                b["active"] = True
                break

        return {"backends": backends, "current_backend": current_backend, "current_model": current_model}

    # -- POST /backend --

    @router.post("/backend")
    async def set_backend(request: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Canvia el backend i/o model actiu en runtime"""
        import os
        backend = request.get("backend", "").lower()
        model = request.get("model", "")

        if backend:
            os.environ["NEXE_MODEL_ENGINE"] = backend
            logger.info(f"Backend canviat a: {backend}")
        if model:
            os.environ["NEXE_DEFAULT_MODEL"] = model
            logger.info(f"Model canviat a: {model}")

        return {"status": "ok", "backend": os.getenv("NEXE_MODEL_ENGINE", "auto"), "model": os.getenv("NEXE_DEFAULT_MODEL", "")}

    # -- GET /health --

    @router.get("/health")
    async def health():
        """Health check del plugin"""
        return {
            "status": "healthy",
            "initialized": True,
            "sessions": len(session_mgr.list_sessions())
        }
