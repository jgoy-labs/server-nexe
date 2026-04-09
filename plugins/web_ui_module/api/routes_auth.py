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
from fastapi import APIRouter, HTTPException, Depends, Header, Request

from plugins.security.core.auth_config import get_admin_api_key
from plugins.web_ui_module.messages import get_message, get_i18n

logger = logging.getLogger(__name__)

# Idioma del servidor — mutable via UI
_server_lang = _os.getenv("NEXE_LANG", "ca").split("-")[0].lower()

def get_server_lang() -> str:
    return _server_lang


def make_require_ui_auth():
    """Crea la dependencia FastAPI d'autenticacio per a la Web UI.

    FAIL CLOSED: si no hi ha API key configurada al servidor, totes les
    peticions UI son rebutjades amb 503. Mai mode permissive (que era el
    bug Codex P1: si NEXE_PRIMARY_API_KEY/NEXE_ADMIN_API_KEY estaven
    buides, les rutes UI quedaven obertes a tothom).
    """
    async def _require_ui_auth(
        request: Request,
        x_api_key: Optional[str] = Header(None),
    ):
        """Valida API key per a endpoints de la Web UI (FAIL CLOSED)"""
        expected = get_admin_api_key()
        if not expected:
            # FAIL CLOSED: no key configured = no UI access
            logger.error("UI auth requested but no admin API key configured (FAIL CLOSED)")
            raise HTTPException(
                status_code=503,
                detail=get_message(get_i18n(request), "webui.auth.no_key_configured")
            )
        if not secrets.compare_digest(x_api_key or "", expected):
            raise HTTPException(
                status_code=401,
                detail=get_message(get_i18n(request), "webui.auth.invalid_key"),
            )
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
    async def set_language(
        body: dict,
        _auth=Depends(require_ui_auth),
        i18n=Depends(get_i18n),
    ):
        """Canvia l'idioma del servidor"""
        global _server_lang
        lang = body.get("lang", "").strip().lower()
        if lang not in ("ca", "es", "en"):
            raise HTTPException(status_code=400, detail=get_message(i18n, "webui.auth.supported_languages"))
        _server_lang = lang
        _os.environ["NEXE_LANG"] = lang
        if i18n is not None:
            i18n.set_language(lang)
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
            version = state.config.get('meta', {}).get('version', '0.9')
            # Detectar backend real (com /status)
            modules = getattr(state, 'modules', {}) or {}
            if configured_backend in ("mlx", "auto"):
                mlx_mod = modules.get("mlx_module")
                mlx_ok = mlx_mod and hasattr(mlx_mod, '_node') and mlx_mod._node is not None
                if configured_backend == "mlx" and not mlx_ok:
                    backend = "ollama"
        except Exception:
            version = "0.9"
        lang = get_server_lang()
        # RAG collections info
        rag_collections = []
        try:
            from memory.memory.api.v1 import get_memory_api
            mem = await get_memory_api()
            for coll_name in ("nexe_documentation", "personal_memory", "user_knowledge"):
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

    # Bug 27 (2026-04-06) — normalització de noms de backend. El catàleg i
    # els `.env` antics poden usar `llama_cpp`/`llama-cpp`/`llama_cpp_module`
    # mentre que l'API esperava `llamacpp`. Acceptem tots aquests i els
    # traduïm al nom canònic sense trencar backwards-compat.
    _BACKEND_ALIASES = {
        "ollama": "ollama",
        "ollama_module": "ollama",
        "mlx": "mlx",
        "mlx_module": "mlx",
        "llamacpp": "llamacpp",
        "llama_cpp": "llamacpp",
        "llama-cpp": "llamacpp",
        "llama_cpp_module": "llamacpp",
        "auto": "auto",
    }

    def _normalize_backend_name(name: str) -> str:
        """Retorna el nom canònic del backend o '' si és invàlid."""
        return _BACKEND_ALIASES.get((name or "").lower().strip(), "")

    async def _backend_model_exists(canonical_backend: str, model_name: str) -> bool:
        """Verifica best-effort que el model existeix per al backend indicat.

        Bug 26 (2026-04-06) — abans s'acceptava qualsevol model sense
        verificar i l'error només apareixia al primer chat. Ara, com a
        mínim per Ollama (que té un endpoint de listing), comprovem que
        el model existeix abans d'acceptar el canvi.

        Per MLX/llamacpp la verificació exhaustiva requereix tocar el
        plugin corresponent: acceptem sempre (best-effort) i ja fallarà
        al primer ús si el model no existeix.

        ⚠️ Dev D (Consultor passada 1): si Ollama no és accessible o tornem
        abans de la verificació per timeout/error, acceptem optimisticament
        (retornem True) per no bloquejar el canvi de backend durant downtime
        d'Ollama. Això és un **mitigant parcial** del bug: quan Ollama cau,
        podem acceptar un model inexistent. Loguem explícitament el cas per
        traçabilitat.
        """
        if not model_name:
            return True  # permetre canvi de backend sense model
        if canonical_backend == "ollama":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get("http://localhost:11434/api/tags")
                    if resp.status_code != 200:
                        # Ollama no accessible — no podem verificar, accepta
                        logger.warning(
                            "Bug 26 mitigant: Ollama returned %d en verificar "
                            "model %r; acceptant optimisticament",
                            resp.status_code, model_name,
                        )
                        return True
                    data = resp.json()
                    available = [m.get("name", "") for m in data.get("models", [])]
                    # Acceptem match exacte o amb sufix :latest
                    if model_name in available or f"{model_name}:latest" in available:
                        return True
                    # Partial match: mateixa família (ex. "qwen3.5:4b" → "qwen3.5")
                    base = model_name.split(":")[0]
                    return any(base == a.split(":")[0] for a in available)
            except Exception as e:
                logger.warning(
                    "Bug 26 mitigant: no es pot verificar el model %r contra "
                    "Ollama (%s); acceptant optimisticament",
                    model_name, e,
                )
                return True  # no es pot verificar → acceptem
        # MLX / llamacpp / auto: best-effort, acceptem
        return True

    @router.post("/backend")
    async def set_backend(request: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Canvia el backend i/o model actiu en runtime. Arrenca Ollama si cal."""
        import os
        import subprocess
        import shutil
        raw_backend = request.get("backend", "")
        model = request.get("model", "")
        ollama_started = False

        # Bug 27 — normalitzem abans de validar
        canonical = _normalize_backend_name(raw_backend)
        if raw_backend and not canonical:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid backend '{raw_backend}'. Valid backends: "
                    f"ollama, mlx, llamacpp, llama_cpp, auto"
                ),
            )

        if canonical == "ollama":
            # Comprovar si Ollama corre, si no, intentar arrencar-lo
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get("http://localhost:11434/api/tags")
                    if resp.status_code != 200:
                        raise ConnectionError()
            except Exception:
                # Ollama no corre — intentar arrencar headless (Bug Ollama GUI 2026-04-06)
                # Prioritzem `ollama serve` directe (sense GUI). Fallback al binari del
                # bundle Ollama.app (també en mode headless — NO fem `open -a Ollama`
                # perquè això llançaria la GUI completa al Dock i la finestra).
                if shutil.which("ollama"):
                    try:
                        subprocess.Popen(
                            ["ollama", "serve"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                        logger.info("Ollama service started automatically")
                        ollama_started = True
                    except Exception as e:
                        logger.warning(f"Could not start Ollama: {e}")
                elif _os.path.exists("/Applications/Ollama.app/Contents/Resources/ollama"):
                    try:
                        subprocess.Popen(
                            ["/Applications/Ollama.app/Contents/Resources/ollama", "serve"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                        logger.info("ollama serve started headless from Ollama.app bundle")
                        ollama_started = True
                    except Exception as e:
                        logger.warning(f"Could not start ollama serve from bundle: {e}")

        # Bug 26 — abans d'acceptar el canvi, validar que el model existeix
        # per al backend escollit. Si el canvi només afecta el backend (sense
        # model), ho permetem. Si hi ha model explicit i sabem comprovar-lo,
        # llancem 400 si no existeix.
        if canonical and model:
            if not await _backend_model_exists(canonical, model):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Model '{model}' not found for backend '{canonical}'. "
                        f"Verify the model is installed before switching."
                    ),
                )

        if canonical:
            os.environ["NEXE_MODEL_ENGINE"] = canonical
            logger.info(f"Backend changed to: {canonical}")
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
