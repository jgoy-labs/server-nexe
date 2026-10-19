"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_auth.py
Description: Authentication, info, backends, and health endpoints.
             Extracted from routes.py during tech debt refactoring.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from pathlib import Path
from typing import Dict, Any, Optional
import os as _os
import logging
from fastapi import APIRouter, HTTPException, Depends, Header, Request

# Runtime override singleton (replaces os.environ writes).
from core.runtime_state import get_with_env_fallback  # noqa: E402

# R6-15 v1.0.4: tolerate absent security plugin so the web UI can serve its
# public surface (HTML, static, health) even when the user has disabled the
# security plugin. Protected endpoints fail closed via _SECURITY_AVAILABLE
# below — they return 503, never 200 without auth.
try:
    from core.security.auth_config import get_admin_api_key
    _SECURITY_AVAILABLE = True
except ImportError:
    _SECURITY_AVAILABLE = False

    def get_admin_api_key() -> Optional[str]:  # type: ignore[misc, no-redef]
        """Stub: degraded mode — protected endpoints return 503 via require_ui_auth."""
        return None

from plugins.web_ui_module.messages import get_message, get_i18n
try:
    from plugins.ollama_module.core.client import resolve_base_url
except ImportError:
    def resolve_base_url() -> str:  # type: ignore[misc]
        import os as _os
        base = _os.getenv("NEXE_OLLAMA_HOST") or _os.getenv("OLLAMA_HOST") or ("http://localhost:" "11434")
        return base.rstrip("/")

logger = logging.getLogger(__name__)

# Server language — mutable via UI.
# Resolution order (2026-05-22):
#   1. NEXE_LANG env var (set by the launcher / Tauri parent — explicit override)
#   2. OnboardingState.lang persisted by the wizard at /installer/finalize
#   3. "en" — neutral OSS default (was "ca" before, which silently forced
#      Catalan on every fresh install regardless of the user's choice)
# The UI langSelect at /ui/lang still overrides this at runtime via
# set_server_lang(); persistence across restarts happens through the
# OnboardingState.
_VALID_LANGS = {"ca", "es", "en"}


def _initial_server_lang() -> str:
    env_lang = _os.getenv("NEXE_LANG", "").split("-")[0].lower()
    if env_lang in _VALID_LANGS:
        return env_lang
    try:
        # Local import to avoid circular dependency at module load time
        # (core.onboarding_state imports nothing from plugins.web_ui_module).
        from core.onboarding_state import OnboardingState
        state = OnboardingState.load()
        if state is not None and state.lang in _VALID_LANGS:
            return state.lang
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_server_lang: onboarding_state lookup failed: %s", exc)
    return "en"


_server_lang = _initial_server_lang()


def get_server_lang() -> str:
    return _server_lang


def make_require_ui_auth():
    """Creates the FastAPI authentication dependency for the Web UI.

    FAIL CLOSED: if no API key is configured on the server, all
    UI requests are rejected with 503. Never permissive mode (which was
    the original bug: if NEXE_PRIMARY_API_KEY/NEXE_ADMIN_API_KEY were
    empty, the UI routes were open to everyone).

    D-I / #883: key check is authenticate_ui_request (same dual-key, expiry,
    Bearer and 429 window as /chat/completions).

    R6-15 v1.0.4: same FAIL CLOSED behaviour applies when the security plugin
    itself is absent — protected endpoints return 503, never 200 unauthorized.
    """
    async def _require_ui_auth(
        request: Request,
        x_api_key: Optional[str] = Header(None),
        authorization: Optional[str] = Header(None),
    ):
        """Validates API key for Web UI endpoints (FAIL CLOSED)"""
        if not _SECURITY_AVAILABLE:
            # Degraded mode: security plugin missing. Public endpoints (UI
            # static, /health) bypass this dependency; protected endpoints
            # land here and must fail closed.
            raise HTTPException(
                status_code=503,
                detail="security plugin missing — protected endpoints unavailable",
            )
        from core.security.auth_dependencies import authenticate_ui_request
        await authenticate_ui_request(request, x_api_key, authorization)
    return _require_ui_auth


def _persist_env_vars(updates: dict, env_path: Path = None) -> None:  # type: ignore[assignment]  # no_implicit_optional
    """Writes/updates key=value pairs in the project's .env file.

    - If the key already exists, replaces the value on the same line.
    - If it doesn't exist, appends the line at the end.
    - Does not touch comment lines or other keys.
    - If the .env file doesn't exist (installation without file), silences.
    - `env_path` is overridable for tests (default: project .env).

    MC-076: refuses any key/value containing a newline (CR/LF) so an
    attacker-controlled value (e.g. the `model` field of POST /backend) can
    never inject arbitrary lines into the .env. Fail-closed: raises ValueError.
    """
    for _k, _v in updates.items():
        # MC-076: reject ANY line break that splitlines() recognizes
        # (not only \n/\r, but also \v \f and the Unicode separators U+2028/U+2029):
        # the re-read of this function uses splitlines(), which would split a value with
        # non-ASCII separators and corrupt/inject the .env.
        if any(s != "".join(s.splitlines()) for s in (str(_k), str(_v))):
            raise ValueError("refusing to persist .env entry containing a line break (MC-076)")
    if env_path is None:
        env_path = Path(__file__).parents[3] / ".env"
    if not env_path.exists():
        logger.debug("_persist_env_vars: .env not found at %s, skipping persist", env_path)
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        remaining = dict(updates)
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}\n")
            else:
                new_lines.append(line)
        for key, val in remaining.items():
            new_lines.append(f"{key}={val}\n")
        env_path.write_text("".join(new_lines), encoding="utf-8")
        logger.debug("_persist_env_vars: persisted %s to %s", list(updates.keys()), env_path)
    except Exception as exc:
        logger.warning("_persist_env_vars: could not write .env (%s)", exc)


def _resolve_backend_version(configured_backend: str) -> tuple:
    """Return (backend, version) by inspecting server state modules.

    Falls back to (configured_backend, '0.0.0-unknown') on error.
    """
    try:
        from core.lifespan import get_server_state
        state = get_server_state()
        version = state.config.get('meta', {}).get('version', '0.9')
        modules = getattr(state, 'modules', {}) or {}
        backend = configured_backend
        if configured_backend in ("mlx", "auto"):
            mlx_mod = modules.get("mlx_module")
            mlx_ok = mlx_mod and hasattr(mlx_mod, '_node') and mlx_mod._node is not None
            if configured_backend == "mlx" and not mlx_ok:
                backend = "ollama"
        return backend, version
    except Exception:
        return configured_backend, "0.0.0-unknown"


def _resolve_model_name(model_name: str, backend: str, configured_backend: str) -> str:
    """Return effective model name, falling back through backend-specific env vars."""
    import os
    if model_name:
        return model_name
    effective_backend = backend or configured_backend
    if effective_backend in ("ollama", "auto"):
        model_name = os.getenv("NEXE_OLLAMA_MODEL", "")
    elif effective_backend == "mlx":
        model_name = get_with_env_fallback("NEXE_MLX_MODEL", "")
    elif effective_backend == "llama_cpp":
        model_name = get_with_env_fallback("NEXE_LLAMA_CPP_MODEL", "")
    return model_name or "nexe"


def _resolve_models_dir() -> "Path":
    """Return absolute Path to the models directory.

    Delegated to core.paths.helpers.get_models_dir() so the lookup
    chain (NEXE_STORAGE_PATH → NEXE_DATA_DIR/models → cwd → repo root) is
    centralised and the same across mlx_module, llama_cpp_module and the
    web UI. The previous local logic appended "/models" to NEXE_STORAGE_PATH,
    which broke for the common case where the env var already points to
    the models directory itself (e.g. NEXE_STORAGE_PATH=~/models).
    """
    from core.paths.helpers import get_models_dir
    return get_models_dir()


def _overlay_ollama_ps_sizes(model_list: list) -> None:
    """Bug #14: overlay real RAM sizes from `ollama ps` for loaded models (in-place)."""
    try:
        import urllib.request
        import json as _json
        req = urllib.request.urlopen(f"{resolve_base_url()}/api/ps", timeout=2)  # nosec B310  # nosemgrep: dynamic-urllib-use-detected — URL from resolve_base_url() uses validated NEXE_OLLAMA_HOST env var
        ps_data = _json.loads(req.read())
        for loaded in ps_data.get("models", []):
            loaded_name = loaded.get("name", "")
            loaded_size = loaded.get("size", 0)
            if loaded_name and loaded_size:
                loaded_gb = round(loaded_size / (1024 ** 3), 1)
                for entry in model_list:
                    if entry["name"] == loaded_name:
                        entry["size_gb"] = loaded_gb
                        break
    except Exception:  # nosec B110: ollama ps probe failure → keep disk-based sizes
        pass


async def _scan_ollama_backend(module_manager) -> "Optional[dict]":
    """Return Ollama backend dict or None if the module is absent."""
    try:
        reg = module_manager.registry.get_module("ollama_module")
        if not (reg and reg.instance):
            return None
        engine = reg.instance
        if hasattr(engine, "get_module_instance"):
            engine = engine.get_module_instance()
        ollama_connected = False
        model_list: list = []
        if hasattr(engine, "list_models"):
            try:
                models = await engine.list_models()
                ollama_connected = True
                for m in models:
                    name = m.get("name", m.get("model", "?"))
                    size_bytes = m.get("size", 0)
                    size_gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else 0
                    model_list.append({"name": name, "size_gb": size_gb})
                _overlay_ollama_ps_sizes(model_list)
            except Exception:
                ollama_connected = False
        return {"id": "ollama", "name": "Ollama", "models": model_list, "active": False, "connected": ollama_connected}
    except Exception as e:
        logger.debug(f"Ollama backend scan failed: {e}")
        return None


def _scan_mlx_backend(models_dir: "Path") -> "Optional[dict]":
    """Return MLX backend dict or None if no MLX models found."""
    # Deferred: a plugin must not pull core at import time (layering gate, #471).
    from core.paths.helpers import has_model_weights
    try:
        if not models_dir.exists():
            return None
        mlx_list = []
        for d in models_dir.iterdir():
            # Only REAL MLX models (config.json present). Bare directory
            # listing served grouping/residual folders as "models" — on
            # 8 GB M1 (2026-07-23) a ~/models/mlx folder reached the UI
            # dropdown, the chat sent model="mlx" and the switch chased a
            # ghost path into a raw FileNotFoundError.
            # #1154: and its weights. A directory with only the config (the
            # Qwen3.5-35B whose weights were moved out) is not a model: it
            # was offered, and the first message died on "No safetensors".
            if d.is_dir() and (d / "config.json").is_file() and has_model_weights(d):
                size = sum(f.stat().st_size for f in d.rglob("*.safetensors") if f.is_file())
                mlx_list.append({"name": d.name, "size_gb": round(size / (1024 ** 3), 1) if size else 0})
        if mlx_list:
            return {"id": "mlx", "name": "MLX", "models": mlx_list, "active": False}
    except Exception as e:
        logger.debug(f"MLX backend scan failed: {e}")
    return None


def _scan_llamacpp_backend(module_manager, models_dir: "Path") -> "Optional[dict]":
    """Return Llama.cpp backend dict or None if module absent or no .gguf files.

    Discovery sources (any-of, deduplicated by resolved real path so a
    symlink and its target don't double-count):

      1. ``NEXE_LLAMA_CPP_MODEL`` env var — the canonical contract of the
         llama_cpp module itself (``plugins/llama_cpp_module/core/config.py``
         reads this same env var to decide which model to load). If the
         operator has the env var pointing at a real .gguf file anywhere
         on disk, that model MUST appear in the dropdown — otherwise the
         user has a working backend that they cannot select from the UI.
         This is the bug fix added 2026-05-13: previously this scan only
         looked at ``storage/models/`` so removing a stale symlink there
         hid the entire Llama.cpp backend even though the engine kept
         working via the env var path.

      2. ``storage/models/*.gguf`` — convenience for users who want
         multiple .gguf files exposed as a list. Adds any .gguf in the
         models dir that is not already covered by source 1.

    The module-presence check (registry has llama_cpp_module loaded) is a
    hard precondition. Without it the backend would be selectable but no
    code path could serve a request.
    """
    try:
        reg = module_manager.registry.get_module("llama_cpp_module")
        if not reg or not reg.instance:
            return None
        gguf_list = _collect_llamacpp_gguf_paths(models_dir)
        if gguf_list:
            return {"id": "llamacpp", "name": "Llama.cpp", "models": gguf_list, "active": False}
    except Exception as e:
        logger.debug(f"Llama.cpp backend scan failed: {e}")
    return None


def _collect_llamacpp_gguf_paths(models_dir: "Path") -> "list[dict]":
    """Collect deduplicated GGUF model entries from both discovery sources.

    Sources: NEXE_LLAMA_CPP_MODEL env var + storage/models/*.gguf.
    Dedup via resolved real path (symlinks and their targets don't double-count).
    """
    seen_real: "set[str]" = set()
    gguf_list: "list[dict]" = []

    def _add(path: "Path") -> None:
        try:
            real = str(path.resolve())
        except OSError:
            return
        if real in seen_real or not path.is_file():
            return
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        seen_real.add(real)
        gguf_list.append({
            "name": path.name,
            "size_gb": round(size / (1024 ** 3), 1) if size else 0,
        })

    # Source 1: NEXE_LLAMA_CPP_MODEL — the engine's own contract.
    env_path_str = get_with_env_fallback("NEXE_LLAMA_CPP_MODEL", "").strip()
    if env_path_str:
        env_path = Path(env_path_str).expanduser()
        if env_path.is_file() and env_path.suffix == ".gguf":
            _add(env_path)

    # Source 2: storage/models/*.gguf — user-curated dropdown additions.
    if models_dir.exists():
        for f in models_dir.iterdir():
            if f.suffix == ".gguf":
                _add(f)

    return gguf_list


def _scan_api_backend(module_manager=None) -> "Optional[dict]":
    """The "API" group of the selector, or None.

    Present only when the global switch is on, the API engine module is
    loaded (otherwise nothing could serve a request) and at least one
    provider has its key configured. The key is never read here beyond "is it
    there": a model carries its provider's name and whether it sees images
    (the selector's heuristic cannot know that for a hosted model).
    """
    from core.providers.cloud import cloud_engines_allowed
    from core.providers.registry import PROVIDERS, is_configured, model_can_see_images

    if not cloud_engines_allowed():
        return None
    try:
        if module_manager is not None:
            reg = module_manager.registry.get_module("api_module")
            if not (reg and reg.instance):
                return None
        models = [
            {"name": model, "size_gb": 0, "provider": p.key, "provider_name": p.name,
             "vision": model_can_see_images(p, model)}
            for p in PROVIDERS if is_configured(p) for model in p.suggested_models
        ]
    except Exception as e:
        logger.debug(f"API backend scan failed: {e}")
        return None
    if not models:
        return None
    return {"id": "api", "name": "API", "models": models, "active": False, "connected": True, "cloud": True}


def _cloud_state() -> dict:
    """What the selector needs to draw the switch: whether it is on and, per
    provider, whether its key is configured. Presence only, never a key."""
    from core.providers.cloud import cloud_engines_allowed
    from core.providers.registry import PROVIDERS, is_configured

    return {
        "allowed": cloud_engines_allowed(),
        "providers": [{"key": p.key, "name": p.name, "configured": is_configured(p)} for p in PROVIDERS],
    }


# The dropdown answers a different question from the chat — which backend to
# show as active, judged on what the scan listed and whether it is connected,
# not on whether a module has a live node — but the ORDER is the same order, and
# it was a third hand-aligned copy of it (its comment still pointed at
# routes_chat._resolve_engines, deleted in F-D block 5). Derived now, so the day
# the cascade changes it changes here too.
# Backend ids (dropdown spelling), not canonical engine names: read off the
# engine table (`chat_engines/routing.py`), where the spelling is a field.
def _backend_ids() -> dict:
    from core.endpoints.chat_engines.routing import ENGINE_TABLE

    return {entry.name: entry.ui_id for entry in ENGINE_TABLE}


def _backend_aliases() -> dict:
    """Every spelling the dropdown's `POST /backend` accepts → its backend id."""
    from core.endpoints.chat_engines.routing import ENGINE_TABLE

    out = {"auto": "auto"}
    for entry in ENGINE_TABLE:
        for spelling in (entry.name, entry.module_key, entry.ui_id, *entry.aliases):
            out[spelling] = entry.ui_id
    return out


def _auto_backend_cascade() -> tuple:
    from core.endpoints.chat_engines.routing import ENGINE_CASCADE

    ids = _backend_ids()
    return tuple(ids[name] for name in ENGINE_CASCADE if name in ids)


def _mark_active_backend(backends: list, current_backend: str) -> str:
    """Mark the active backend in-place; falls back to first connected backend.

    ``auto`` follows the core cascade (mlx → llama.cpp → ollama) and only
    marks a backend that is actually listed. MLX is skipped when the scan
    found no models (typical non-Mac). Does not rewrite NEXE_MODEL_ENGINE:
    auto stays auto.
    """
    if current_backend == "auto":
        by_id = {b["id"]: b for b in backends}
        for bid in _auto_backend_cascade():
            b = by_id.get(bid)
            if b and b.get("connected", True) and b.get("models"):
                b["active"] = True
                return current_backend
        return current_backend

    requested = "ollama" if current_backend == "ollama_module" else current_backend
    for b in backends:
        if requested == b["id"]:
            if b.get("connected", True):
                b["active"] = True
                return current_backend
    # Fallback: activate first connected backend with models
    for b in backends:
        if b.get("connected", True) and b["models"]:
            b["active"] = True
            from core.runtime_state import set_override
            set_override("NEXE_MODEL_ENGINE", b["id"])
            logger.info(f"Backend fallback: {b['id']} (configured backend unavailable)")
            return b["id"]
    return current_backend


async def _fetch_rag_collections(app_state) -> list:
    """Return list of RAG collection dicts {name, count}. Returns [] on error."""
    try:
        import core.memory_facts as memory_facts
        mem = await memory_facts.helper_for(app_state).get_memory_api()
        if not mem:
            return []
        names = await mem.visible_names()
        result = []
        for coll_name in names:
            try:
                count = await mem.count(coll_name) if await mem.collection_exists(coll_name) else -1
                result.append({"name": coll_name, "count": count})
            except Exception:
                result.append({"name": coll_name, "count": -1})
        return result
    except Exception as e:
        logger.warning("Could not fetch RAG collections: %s", e)
        return []


def register_auth_routes(router: APIRouter, *, require_ui_auth, session_mgr):
    """Registers endpoints: /auth, /info, /backends, /backend, /health"""

    # -- GET /auth --

    @router.get("/auth", operation_id="webui_verify_auth")
    async def verify_auth(_auth=Depends(require_ui_auth)):
        """Verify API key"""
        return {"status": "ok"}

    # -- POST /lang --

    @router.post("/lang", operation_id="webui_set_language")
    async def set_language(
        body: dict,
        _auth=Depends(require_ui_auth),
        i18n=Depends(get_i18n),
    ):
        """Change the server language"""
        global _server_lang
        lang = body.get("lang", "").strip().lower()
        if lang not in ("ca", "es", "en"):
            raise HTTPException(status_code=400, detail=get_message(i18n, "webui.auth.supported_languages"))
        _server_lang = lang
        # Drop `os.environ["NEXE_LANG"] = lang`. The only consumer
        # of this env var is the module-level `_server_lang` initialiser (line 46),
        # which runs once at import. Mutating process env after start was a no-op
        # for in-process readers and contaminated any subprocess spawned later.
        # The `_server_lang` global plus `_persist_env_vars` (if added on persist
        # paths) is sufficient for live reads and restart-time defaults.
        if i18n is not None:
            lang_map = {"ca": "ca-ES", "es": "es-ES", "en": "en-US"}
            i18n.current_language = lang_map.get(lang, lang)
        logger.info("Server language changed to: %s", lang)
        return {"status": "ok", "lang": lang}

    # -- GET /info --

    @router.get("/info", operation_id="webui_info")
    async def get_ui_info(request: Request, _auth=Depends(require_ui_auth)):
        """Active model and backend info"""
        model_name = get_with_env_fallback("NEXE_DEFAULT_MODEL", "")
        configured_backend = get_with_env_fallback("NEXE_MODEL_ENGINE", "auto")
        backend, version = _resolve_backend_version(configured_backend)
        model_name = _resolve_model_name(model_name, backend, configured_backend)
        lang = get_server_lang()
        rag_collections = await _fetch_rag_collections(request.app.state)
        return {
            "model": model_name,
            "backend": backend,
            "configured_backend": configured_backend,
            "version": version,
            "lang": lang,
            "rag_collections": rag_collections,
        }

    # -- GET /backends --

    @router.get("/backends", operation_id="webui_list_backends")
    async def list_backends(_auth=Depends(require_ui_auth)):
        """List available backends with their models"""
        from core.lifespan import get_server_state

        module_manager = get_server_state().module_manager
        models_dir = _resolve_models_dir()
        backends = []

        ollama = await _scan_ollama_backend(module_manager)
        if ollama:
            backends.append(ollama)
        mlx = _scan_mlx_backend(models_dir)
        if mlx:
            backends.append(mlx)
        llamacpp = _scan_llamacpp_backend(module_manager, models_dir)
        if llamacpp:
            backends.append(llamacpp)

        current_backend = get_with_env_fallback("NEXE_MODEL_ENGINE", "auto").lower()
        current_model = get_with_env_fallback("NEXE_DEFAULT_MODEL", "")
        current_backend = _mark_active_backend(backends, current_backend)

        # After the active mark, never before: `_mark_active_backend` falls back
        # to "the first connected backend with models" and persists it — the API
        # group must not be a candidate for that, or a dead local engine would
        # make the cloud the default.
        api = _scan_api_backend(module_manager)
        if api:
            backends.append(api)

        return {
            "backends": backends, "current_backend": current_backend, "current_model": current_model,
            "cloud": _cloud_state(),
        }

    # -- POST /backend --

    # Bug 27 (2026-04-06) — backend name normalization. The catalog and
    # old `.env` files may use `llama_cpp`/`llama-cpp`/`llama_cpp_module`
    # while the API expected `llamacpp`. We accept all of these and
    # translate them to the canonical name without breaking backwards-compat.
    def _normalize_backend_name(name: str) -> str:
        """Returns the canonical backend name or '' if invalid."""
        return _backend_aliases().get((name or "").lower().strip(), "")

    async def _backend_model_exists(canonical_backend: str, model_name: str) -> bool:
        """Best-effort verification that the model exists for the indicated backend.

        Bug 26 (2026-04-06) — previously any model was accepted without
        verification and the error only appeared on the first chat. Now, at
        least for Ollama (which has a listing endpoint), we check that
        the model exists before accepting the change.

        For MLX/llamacpp exhaustive verification requires touching the
        corresponding plugin: we always accept (best-effort) and it will fail
        on first use if the model doesn't exist.

        ⚠️ If Ollama is not accessible or we return
        before verification due to timeout/error, we accept optimistically
        (return True) to avoid blocking backend switches during Ollama downtime.
        This is a **partial mitigation** of the bug: when Ollama is down,
        we may accept a non-existent model. We log explicitly for traceability.
        """
        if not model_name:
            return True  # allow backend change without model
        if canonical_backend == "ollama":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{resolve_base_url()}/api/tags")
                    if resp.status_code != 200:
                        # Ollama not reachable — cannot verify, accept optimistically
                        logger.warning(
                            "Bug 26 mitigant: Ollama returned %d en verificar "
                            "model %r; acceptant optimisticament",
                            resp.status_code, model_name,
                        )
                        return True
                    data = resp.json()
                    available = [m.get("name", "") for m in data.get("models", [])]
                    # Accept exact match or with :latest suffix
                    if model_name in available or f"{model_name}:latest" in available:
                        return True
                    # Partial match: same family (e.g. "qwen3.5:4b" → "qwen3.5")
                    base = model_name.split(":")[0]
                    return any(base == a.split(":")[0] for a in available)
            except Exception as e:
                logger.warning(
                    "Bug 26 mitigant: no es pot verificar el model %r contra "
                    "Ollama (%s); acceptant optimisticament",
                    model_name, e,
                )
                return True  # cannot verify → accept
        # MLX / llamacpp: verify locally (cheap, no network) so set_backend
        # never persists a ghost model to .env — the 8 GB M1 model="mlx"
        # ghost re-appeared on every app restart precisely because it had
        # been persisted as NEXE_DEFAULT_MODEL. `auto`: best-effort, accept.
        if canonical_backend == "mlx":
            from core.paths.helpers import get_models_dir, has_model_weights
            _p = get_models_dir() / model_name
            # #1154: weights too — a config alone is a ghost, as in the dropdown.
            if not ((_p / "config.json").is_file() and has_model_weights(_p)):
                logger.warning(
                    "set_backend: refusing ghost MLX model %r (no config.json or no weights)",
                    model_name,
                )
                return False
            return True
        # llamacpp: best-effort accept — its scan discovers GGUFs from several
        # sources beyond models_dir (env path, bundle), so a local-path check
        # here would reject legitimate models. `auto` too.
        return True

    async def _ensure_ollama_running() -> bool:
        """Check if Ollama is reachable; if not, start it headlessly. Returns True if started.

        MC-028: delegates to the centralised :func:`ollama_runtime.ensure_ollama_running`
        (single read point for NEXE_OLLAMA_BIN + the headless bundle binary).
        ``wait=False`` preserves this call site's fire-and-forget contract: it
        starts Ollama and returns immediately, WITHOUT waiting for readiness.
        """
        from plugins.ollama_module.core.ollama_runtime import ensure_ollama_running
        process = await ensure_ollama_running(resolve_base_url(), wait=False)
        return process is not None

    async def _unload_previous_ollama_model(old_model: str, new_model: str, old_backend: str) -> None:
        """Unload previous Ollama model from VRAM when switching models."""
        if not (old_model and new_model and old_model != new_model and old_backend in ("ollama", "auto")):
            return
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=5.0) as _uc:
                await _uc.post(f"{resolve_base_url()}/api/chat", json={"model": old_model, "keep_alive": 0})
                logger.info(f"Unloaded previous model from Ollama VRAM: {old_model}")
        except Exception as _ue:
            logger.debug(f"Could not unload previous model {old_model}: {_ue}")

    def _apply_and_persist_backend(canonical: str, model: str) -> None:
        """Set runtime overrides for backend/model and persist them to .env.

        Overrides go through core.runtime_state instead
        of mutating os.environ; persistence to .env is still needed so the
        next process start picks the same selection up via NEXE_* env reading.
        """
        from core.runtime_state import set_override
        if canonical:
            set_override("NEXE_MODEL_ENGINE", canonical)
            logger.info(f"Backend changed to: {canonical}")
        if model:
            set_override("NEXE_DEFAULT_MODEL", model)
            logger.info(f"Model changed to: {model}")
        persist = {}
        if canonical:
            persist["NEXE_MODEL_ENGINE"] = canonical
        if model:
            persist["NEXE_DEFAULT_MODEL"] = model
        if persist:
            _persist_env_vars(persist)

    def _select_api_backend(model: str) -> dict:
        """Picking the API in the selector. The choice is the browser's, per
        chat, and is NOT persisted: nothing is written to `NEXE_MODEL_ENGINE`
        or `NEXE_DEFAULT_MODEL`, because a persisted "api" would make the
        cloud the engine of every request that names none. The server only
        says whether the choice can work; consent is asked at the first turn."""
        from core.providers.cloud import CloudRefusal, require_cloud_selection

        try:
            provider = require_cloud_selection(model)
        except CloudRefusal as refusal:
            raise HTTPException(status_code=refusal.status, detail=refusal.detail()) from None
        return {
            "status": "ok", "backend": "api", "model": model, "provider": provider.key,
            "provider_name": provider.name, "persisted": False, "ollama_started": False,
        }

    @router.post("/cloud-engines", operation_id="webui_set_cloud_engines")
    async def set_cloud_engines(request: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Turn "Allow cloud engines" on or off (`NEXE_ALLOW_CLOUD_ENGINES`).

        Strictly a boolean: a string like "false" is refused instead of read as
        truthy. Runtime override + persisted like the other UI parameters."""
        from core.providers.cloud import ALLOW_CLOUD_ENV, cloud_engines_allowed
        from core.runtime_state import set_override

        enabled = request.get("enabled")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="'enabled' must be true or false")
        value = "1" if enabled else "0"
        set_override(ALLOW_CLOUD_ENV, value)
        _persist_env_vars({ALLOW_CLOUD_ENV: value})
        logger.info("Cloud engines %s", "allowed" if enabled else "not allowed")
        return {"status": "ok", "allowed": cloud_engines_allowed()}

    @router.post("/backend", operation_id="webui_set_backend")
    async def set_backend(request: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Change the active backend and/or model at runtime. Starts Ollama if needed."""
        raw_backend = request.get("backend", "")
        model = request.get("model", "")

        # MC-076: reject models with line breaks / control characters before
        # persisting them to the .env (input defense; the writer also rejects them).
        if model and ((model != "".join(model.splitlines())) or any(ord(c) < 32 for c in model)):
            raise HTTPException(status_code=400, detail="Invalid model name")

        # Bug 27 — normalize before validating
        canonical = _normalize_backend_name(raw_backend)
        if raw_backend and not canonical:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid backend '{raw_backend}'. Valid backends: ollama, mlx, llamacpp, llama_cpp, auto, api",
            )

        if canonical == "api":
            return _select_api_backend(model)

        ollama_started = False
        if canonical == "ollama":
            ollama_started = await _ensure_ollama_running()

        # Bug 26 — validate model exists before accepting the change
        if canonical and model:
            if not await _backend_model_exists(canonical, model):
                raise HTTPException(
                    status_code=400,
                    detail=f"Model '{model}' not found for backend '{canonical}'. Verify the model is installed before switching.",
                )

        old_model = get_with_env_fallback("NEXE_DEFAULT_MODEL", "")
        old_backend = get_with_env_fallback("NEXE_MODEL_ENGINE", "auto")
        await _unload_previous_ollama_model(old_model, model, old_backend)
        _apply_and_persist_backend(canonical, model)

        return {
            "status": "ok",
            "backend": get_with_env_fallback("NEXE_MODEL_ENGINE", "auto"),
            "model": get_with_env_fallback("NEXE_DEFAULT_MODEL", ""),
            "ollama_started": ollama_started,
        }

    # -- GET /health --

    @router.get("/health", operation_id="webui_auth_health")
    async def health():
        """Plugin health check"""
        return {
            "status": "healthy",
            "initialized": True,
            "sessions": len(session_mgr.list_sessions())
        }
