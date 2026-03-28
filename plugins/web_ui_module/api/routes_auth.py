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
import os as _os
import logging
import secrets
from fastapi import APIRouter, HTTPException, Depends, Header

from plugins.security.core.auth_config import get_admin_api_key
from plugins.web_ui_module.messages import get_message

logger = logging.getLogger(__name__)

# Idioma del servidor — mutable via UI
_server_lang = _os.getenv("NEXE_LANG", "ca").split("-")[0].lower()

def get_server_lang() -> str:
    return _server_lang


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

    # -- POST /lang --

    @router.post("/lang")
    async def set_language(body: dict, _auth=Depends(require_ui_auth)):
        """Canvia l'idioma del servidor"""
        global _server_lang
        lang = body.get("lang", "").strip().lower()
        if lang not in ("ca", "es", "en"):
            raise HTTPException(status_code=400, detail="Supported languages: ca, es, en")
        _server_lang = lang
        _os.environ["NEXE_LANG"] = lang
        logger.info("Server language changed to: %s", lang)
        return {"status": "ok", "lang": lang}

    # -- GET /info --

    @router.get("/info")
    async def get_ui_info(_auth=Depends(require_ui_auth)):
        """Info del model i backend actiu"""
        import os
        model_name = os.getenv("NEXE_DEFAULT_MODEL", "unknown")
        configured_backend = os.getenv("NEXE_MODEL_ENGINE", "auto")
        backend = configured_backend
        try:
            from core.lifespan import get_server_state
            state = get_server_state()
            version = state.config.get('meta', {}).get('version', '0.8')
            # Detectar backend real (com /status)
            modules = getattr(state, 'modules', {}) or {}
            if configured_backend in ("mlx", "auto"):
                mlx_mod = modules.get("mlx_module")
                mlx_ok = mlx_mod and hasattr(mlx_mod, '_node') and mlx_mod._node is not None
                if configured_backend == "mlx" and not mlx_ok:
                    backend = "ollama"
        except Exception:
            version = "0.8"
        lang = get_server_lang()
        # RAG collections info
        rag_collections = []
        try:
            from memory.memory.api.v1 import get_memory_api
            mem = await get_memory_api()
            for coll_name in ("nexe_documentation", "nexe_web_ui", "user_knowledge"):
                try:
                    if await mem.collection_exists(coll_name):
                        count = await mem.count(coll_name)
                        rag_collections.append({"name": coll_name, "count": count})
                    else:
                        rag_collections.append({"name": coll_name, "count": -1})
                except Exception:
                    rag_collections.append({"name": coll_name, "count": -1})
        except Exception as e:
            logger.warning("Could not fetch RAG collections: %s", e)

        return {
            "model": model_name,
            "backend": backend,
            "configured_backend": configured_backend,
            "version": version,
            "lang": lang,
            "rag_collections": rag_collections
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

        # Ollama (always show if the module exists, mark as disconnected if unreachable)
        try:
            reg = module_manager.registry.get_module("ollama_module")
            if reg and reg.instance:
                engine = reg.instance
                if hasattr(engine, "get_module_instance"):
                    engine = engine.get_module_instance()
                ollama_connected = False
                model_list = []
                if hasattr(engine, "list_models"):
                    try:
                        models = await engine.list_models()
                        ollama_connected = True
                        for m in models:
                            name = m.get("name", m.get("model", "?"))
                            size_bytes = m.get("size", 0)
                            size_gb = round(size_bytes / (1024**3), 1) if size_bytes else 0
                            model_list.append({"name": name, "size_gb": size_gb})
                    except Exception:
                        ollama_connected = False
                backends.append({
                    "id": "ollama", "name": "Ollama", "models": model_list,
                    "active": False, "connected": ollama_connected
                })
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

        # Mark active — if the configured backend is disconnected, fall back to the first connected one
        current_backend = os.getenv("NEXE_MODEL_ENGINE", "auto").lower()
        current_model = os.getenv("NEXE_DEFAULT_MODEL", "")
        active_set = False
        for b in backends:
            if current_backend == b["id"] or (current_backend in ("auto", "ollama_module") and b["id"] == "ollama"):
                if b.get("connected", True):
                    b["active"] = True
                    active_set = True
                    break
        # Fallback: activar primer backend connectat
        if not active_set:
            for b in backends:
                if b.get("connected", True) and b["models"]:
                    b["active"] = True
                    current_backend = b["id"]
                    os.environ["NEXE_MODEL_ENGINE"] = b["id"]
                    logger.info(f"Backend fallback: {b['id']} (configured backend unavailable)")
                    break

        return {"backends": backends, "current_backend": current_backend, "current_model": current_model}

    # -- POST /backend --

    @router.post("/backend")
    async def set_backend(request: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Canvia el backend i/o model actiu en runtime. Arrenca Ollama si cal."""
        import os
        import subprocess
        import shutil
        backend = request.get("backend", "").lower()
        model = request.get("model", "")
        ollama_started = False

        if backend in ("ollama", "ollama_module"):
            # Comprovar si Ollama corre, si no, intentar arrencar-lo
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get("http://localhost:11434/api/tags")
                    if resp.status_code != 200:
                        raise ConnectionError()
            except Exception:
                # Ollama no corre — intentar arrencar
                if shutil.which("ollama"):
                    try:
                        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        logger.info("Ollama service started automatically")
                        ollama_started = True
                    except Exception as e:
                        logger.warning(f"Could not start Ollama: {e}")
                elif _os.path.exists("/Applications/Ollama.app"):
                    try:
                        subprocess.Popen(["open", "-g", "-a", "Ollama"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        logger.info("Ollama.app started automatically")
                        ollama_started = True
                    except Exception as e:
                        logger.warning(f"Could not start Ollama.app: {e}")

        if backend:
            # Validate backend exists before accepting switch
            valid_backends = {"ollama", "ollama_module", "mlx", "mlx_module", "llamacpp", "llama_cpp_module", "auto"}
            if backend not in valid_backends:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid backend '{backend}'. Valid backends: ollama, mlx, llamacpp, auto"
                )
            os.environ["NEXE_MODEL_ENGINE"] = backend
            logger.info(f"Backend changed to: {backend}")
        if model:
            os.environ["NEXE_DEFAULT_MODEL"] = model
            logger.info(f"Model canviat a: {model}")

        return {
            "status": "ok",
            "backend": os.getenv("NEXE_MODEL_ENGINE", "auto"),
            "model": os.getenv("NEXE_DEFAULT_MODEL", ""),
            "ollama_started": ollama_started
        }

    # -- GET /health --

    @router.get("/health")
    async def health():
        """Health check del plugin"""
        return {
            "status": "healthy",
            "initialized": True,
            "sessions": len(session_mgr.list_sessions())
        }
