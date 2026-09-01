"""
HTTP endpoints for the onboarding wizard.

All endpoints are intentionally unauthenticated — the user has no API key
yet when running through the wizard. The wizard is only reachable from the
local WebView (same-machine, loopback only) so the risk is minimal.

Endpoints:
  GET  /installer/download   — SSE stream: model download progress
  POST /installer/ollama     — SSE stream: Ollama install check
  POST /installer/finalize   — JSON: {api_key, status} + persists onboarding state
  GET  /installer/finalize   — JSON: {api_key, status} — legacy, no state persisted
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.endpoints import (
    installer_embedder,
    installer_gguf,
    installer_hf,
    installer_mlx,
    installer_ollama,
    installer_shared,
)
# _sse/_SSE_HEADERS are pure formatting — nothing substitutes them, so they
# come in by name. Everything else in installer_shared is reached through the
# module (`installer_shared._models_dir()`), so it has exactly ONE place to be
# patched. Importing those by name would bind a second alias here, and a test
# patching this module's copy would go green while the real call site — the
# one inside installer_shared — kept the original. Green, and testing nothing.
from core.endpoints.installer_shared import _SSE_HEADERS, _sse
from core.installer_constants import VALID_ENGINES as _VALID_ENGINES
from core.onboarding_state import (
    OnboardingState,
    _store_hf_token_in_keychain,
)

# cleanup: import DownloadIntegrityError at top to
# avoid pyright `reportPossiblyUnboundVariable` when the lazy import inside
# the SHA256 verification block is re-used in the except clause. The lazy
# import is kept below (for verify_download_integrity which has heavier
# transitive deps); the class itself is small and import-safe.
try:
    from installer.download_verify import DownloadIntegrityError  # type: ignore[import]
except ImportError:  # pragma: no cover - PBS bundle resilience
    class DownloadIntegrityError(Exception):  # type: ignore[no-redef]
        """Fallback if installer.download_verify is not importable (PBS bundle)."""

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/installer", tags=["installer"])

# canonical fastembed model id for the wizard. Kept here (not
# imported from memory.embeddings.constants) so the installer remains
# import-safe in PBS bundles where memory/structlog chains can fail —
# see memory `feedback_dmg_structlog_import.md`.
_EMBEDDER_MODEL_ID = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"













































# ──────────────────────────────────────────────────────────────────────────────
# Gated-model detection + dry_run preflight
# ──────────────────────────────────────────────────────────────────────────────










@router.get("/preflight", operation_id="installer_preflight")
async def preflight(engine: str, model_id: str) -> JSONResponse:
    """Probe a model BEFORE downloading: gated status + total bytes.

    Exposed so the wizard can show the user
    a meaningful summary ("Will download 4.5 GB in 12 files, 1.2 GB
    already cached") and surface gated-model errors before the user
    commits to a download.

    For engine="ollama" we skip the HF lookup entirely (Ollama models are
    pulled via the ollama daemon, no HF concept of gated/private applies).
    """
    if engine not in _VALID_ENGINES:
        return JSONResponse({"error": f"Unknown engine: {engine!r}"}, status_code=400)
    if engine == "ollama":
        return JSONResponse({
            "engine": "ollama",
            "access": {"status": "ok"},
            "plan": {"total_bytes": 0, "cached_bytes": 0, "files_count": 0},
        })

    # if the user has stored an HF token, the access check
    # and dry-run plan use it so gated repos the user has access to are
    # reported as "ok" instead of "gated_no_access". Falls back to the Keychain
    # so a token handed over before a mid-flow sidecar restart is not lost (B253).
    # gguf model_ids are raw .gguf URLs; HF probes need the repo_id (B257). A
    # gguf URL on a non-HF host has no HF gated/size concept → report ok/empty.
    repo_id = installer_hf._preflight_repo_id(model_id)
    if repo_id is None:
        return JSONResponse({
            "engine": engine,
            "access": {"status": "ok"},
            "plan": {"total_bytes": 0, "cached_bytes": 0, "files_count": 0},
        })
    token = await installer_hf._ensure_hf_token_in_env()
    # Run blocking HF calls in the executor so we don't block the event loop.
    loop = asyncio.get_event_loop()
    access = await loop.run_in_executor(installer_shared._dl_executor, installer_hf._check_model_access, repo_id, token)
    plan = await loop.run_in_executor(installer_shared._dl_executor, installer_hf._dry_run_plan, repo_id, token)
    return JSONResponse({
        "engine": engine,
        "access": access,
        "plan": plan,
    })




async def _sha256_check(engine: str, model_id: str) -> "dict | None":
    """Run SHA256 integrity check.

    Returns:
      - ``None`` when the weights were verified against a pinned digest.
      - a ``{"type": "warning", "code": "SHA256_NOT_PINNED", ...}`` event when
        the model has no pin in the catalog (INST-002: the GUI/SSE path must
        surface the same ⚠️ notice the CLI already prints, per the
        download_verify contract — the caller yields it but does NOT abort).
      - a ``{"type": "error", "code": "SHA256_FAIL", ...}`` event on a digest
        mismatch or an unexpected verification error (fail-closed, INST-003).
    """
    try:
        from installer.download_verify import verify_download_integrity  # type: ignore[import]
        loop = asyncio.get_event_loop()
        if engine == "ollama":
            # ADR B251: Ollama integrity is delegated to its content-addressed
            # pull; verify_download_integrity short-circuits to True (the target
            # path is unused for Ollama).
            matched = await loop.run_in_executor(
                None, verify_download_integrity, engine, model_id, Path("."),
            )
        else:
            target_path = Path(installer_shared._resolve_model_path(engine, model_id))
            matched = await loop.run_in_executor(None, verify_download_integrity, engine, model_id, target_path)
        if not matched:
            logger.info("installer: SHA256 not pinned for %s/%s — install continues", engine, model_id)
            # INST-002: surface the missing-pin condition to the user instead of
            # only logging it. The CLI prints a yellow ⚠️ and the download_verify
            # contract requires the caller to make it visible. This is a warning,
            # not an error: the install continues (the caller does not abort).
            return {
                "type": "warning",
                "code": "SHA256_NOT_PINNED",
                "message": (
                    f"{model_id}: installed without weight verification "
                    "(no SHA256 pin in the catalog)."
                ),
            }
        return None
    except DownloadIntegrityError as exc:
        logger.error("installer: SHA256 mismatch for %s/%s: %s", engine, model_id, exc)
        return {"type": "error", "code": "SHA256_FAIL", "message": f"Integrity check failed: {exc}"}
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        logger.error("installer: SHA256 verify hard error for %s/%s: %s", engine, model_id, exc)
        return {"type": "error", "code": "SHA256_FAIL", "message": f"Integrity check error: {exc}"}
    except Exception as exc:  # noqa: BLE001
        # Fail-CLOSED. This is a security check: an unexpected error in the
        # verification path (a bug in the hashing chain, an unforeseen runtime
        # error) must NOT be silently treated as "skip → continue". Doing so
        # would disable integrity enforcement without anyone noticing. The
        # download library already returns None/False for legitimate
        # infrastructure conditions (digest not pinned, ollama unavailable,
        # older daemon) — those reach the `if not matched` branch above and
        # continue. Anything that reaches HERE is genuinely unexpected, so we
        # abort the install rather than ship an unverified model.
        logger.error("installer: SHA256 verify unexpected error for %s/%s: %s", engine, model_id, exc)
        return {"type": "error", "code": "SHA256_FAIL", "message": f"Integrity check error: {exc}"}


@router.get("/download", operation_id="installer_download_model")
async def download_model(engine: str, model_id: str, request: Request) -> StreamingResponse:
    """Stream model download progress as SSE events.

    Query params:
      engine   — one of: mlx, ollama, gguf
      model_id — e.g. "mlx-community/gemma-3-4b-it-4bit" or "gemma3:4b"
    """
    if engine not in _VALID_ENGINES:
        async def _err() -> AsyncIterator[str]:
            yield await _sse({"type": "error", "message": f"Unknown engine: {engine!r}"})
        return StreamingResponse(_err(), media_type="text/event-stream", headers=_SSE_HEADERS)

    # Reject pathological model_id values up front so the streamers below
    # never see a basename of "..", "." or "" that would escape models_dir.
    # Ollama identifiers ("gemma3:4b") are not file paths so the basename
    # rule does not apply.
    if engine in ("mlx", "gguf"):
        try:
            installer_shared._safe_model_basename(model_id)
        except ValueError as exc:
            err_msg = str(exc)
            async def _err_basename() -> AsyncIterator[str]:
                yield await _sse({"type": "error", "code": "INVALID_MODEL_ID", "message": err_msg})
            return StreamingResponse(_err_basename(), media_type="text/event-stream", headers=_SSE_HEADERS)

    async def generate() -> AsyncIterator[str]:
        try:
            # Pre-flight gated/not-found check for HF-hosted engines (mlx/gguf).
            preflight_err = await installer_hf._preflight_hf_access(engine, model_id)
            if preflight_err is not None:
                yield await _sse(preflight_err)
                return

            if engine == "mlx":
                async for ev in installer_mlx._stream_mlx(model_id, request):
                    yield await _sse(ev)
            elif engine == "ollama":
                async for ev in installer_ollama._stream_ollama(model_id, request):
                    yield await _sse(ev)
            elif engine == "embedder":
                # download the fastembed embedding model. The
                # wizard supplies model_id explicitly (or the default
                # constant via _EMBEDDER_MODEL_ID).
                effective_id = model_id or _EMBEDDER_MODEL_ID
                async for ev in installer_embedder._stream_embedder(effective_id, request):
                    yield await _sse(ev)
            else:
                async for ev in installer_gguf._stream_gguf(model_id, request):
                    yield await _sse(ev)

            # SHA256 integrity check post-download (mlx/ollama/gguf only, not embedder).
            if engine in ("mlx", "ollama", "gguf"):
                ev = await _sha256_check(engine, model_id)
                if ev is not None:
                    yield await _sse(ev)
                    # INST-002: only a hard integrity failure aborts the install.
                    # A SHA256_NOT_PINNED warning is surfaced but the download
                    # still completes (then falls through to the done event).
                    if ev.get("type") == "error":
                        return

            yield await _sse({"type": "done", "model_id": model_id})
        except Exception as exc:
            logger.exception("installer: download error for %s/%s", engine, model_id)
            yield await _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


class HfTokenBody(BaseModel):
    """Body for POST /installer/hf-token.

    Carries the Hugging Face access token the user pasted in the model-
    selection step so a GATED model can be downloaded in the SAME onboarding
    run. The token travels in a POST body (never a query param), so — unlike
    the GET /installer/download — it stays out of the uvicorn access log.
    Length capped like FinalizeBody (HF tokens are ~40 chars; the cap guards
    against an accidental paste of a huge blob).

    Caveat (B054 follow-up E): a paste OVER ``max_length`` raises a Pydantic
    validation error whose payload echoes the offending value, which the
    shared validation handler logs + returns in the 422 body. Real HF tokens
    are far under the cap, so this needs a deliberate oversized paste; the
    global redaction fix is tracked as a follow-up.
    """

    token: str = Field(..., min_length=1, max_length=200)


@router.post("/hf-token", operation_id="installer_set_hf_token")
async def set_hf_token(body: HfTokenBody) -> JSONResponse:
    """Load the HF token into the live sidecar env so a gated-model download
    in this same onboarding run can authenticate.

    Why this exists (B054): the token input previously lived only in the
    Advanced zone (which skips the catalog download), and the only path that
    persisted the token — POST /installer/finalize (step 5) — runs AFTER the
    download (step 3). So a first-run user could never download a gated MLX
    model. This endpoint lets step 3 hand the token over BEFORE the download:
    it sets ``os.environ['HF_TOKEN']`` (read by ``installer_hf._preflight_hf_access`` and
    ``snapshot_download``) and best-effort persists it to the Keychain so a
    restart between step 3 and step 5 does not lose it. The token value is
    never logged.
    """
    token = body.token.strip()
    if not token:
        return JSONResponse(status_code=400, content={"detail": "empty token"})
    # The env var is what the gated preflight + snapshot_download read, and it is
    # set synchronously — that is the part the download needs right now.
    os.environ["HF_TOKEN"] = token
    # Keychain persistence is best-effort AND must never block the event loop nor
    # hang the wizard: a headless keyring access can trigger a blocking macOS
    # authorization dialog the sidecar cannot answer (precedent CRY-01). Run it
    # off-thread with a short timeout; on timeout/failure the token still lives
    # in the env for this run's download, and finalize (step 5) persists it later.
    persisted = False
    try:
        loop = asyncio.get_event_loop()
        persisted = await asyncio.wait_for(
            loop.run_in_executor(installer_shared._dl_executor, _store_hf_token_in_keychain, token),
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001 — timeout or keyring error: never fatal
        logger.warning("installer/hf-token: Keychain persist skipped (%s)", type(exc).__name__)
    logger.info("installer/hf-token: HF_TOKEN loaded into env (persisted=%s)", persisted)
    return JSONResponse({"ok": True, "persisted": persisted})


# #855: WebKit (the Tauri WebView on macOS) drops EventSource/fetch streams
# that go silent for >~30 s. The install waits on real work — since #833 an
# API probe of 30-60 s — so the SSE body must not stay mute until done/error.
# Same reason as the model-download keepalive above, tighter period because
# here a single silent stretch already crosses the WebKit threshold.
_OLLAMA_INSTALL_KEEPALIVE_S = 10.0


@router.post("/ollama", operation_id="installer_ollama_install")
async def install_ollama_endpoint(request: Request) -> StreamingResponse:
    """Install Ollama if not present, streaming status as SSE.

    Replaces the placeholder "already_installed: False"
    per una crida real a ensure_ollama_installed(headless=True). Mateixes
    correccions C1-C5 de l'auditoria agèntica que installer_ollama._stream_ollama (cancel detection,
    lock concurrent, error UX-friendly per platform, logger.exception).
    """

    async def generate() -> AsyncIterator[str]:
        binary = installer_ollama._find_ollama_bin()
        if binary:
            yield await _sse({"type": "done", "already_installed": True})
            return
        # Check disconnect before starting.
        if await request.is_disconnected():
            return
        yield await _sse({"type": "progress", "stage": "Instal.lant Ollama...", "percent": 0})
        # Non-blocking lock to prevent two concurrent installations.
        if not installer_shared._ollama_install_lock.acquire(blocking=False):
            yield await _sse({"type": "error", "message": "Ja s'esta instal.lant Ollama en un altre proces"})
            return
        try:
            # MC-031: share the install→locate machine with
            # installer_ollama._install_ollama_if_needed so the bundle fallback (CLI installed
            # but not yet on PATH) can never diverge between the two paths.
            # #855: run it as a task so the stream can breathe while it works.
            _install = asyncio.ensure_future(installer_ollama._install_ollama_and_locate())
            while True:
                _finished, _ = await asyncio.wait(
                    {_install}, timeout=_OLLAMA_INSTALL_KEEPALIVE_S
                )
                if _finished:
                    break
                yield await _sse({"type": "keepalive", "ts": time.monotonic()})
            binary = _install.result()
        except RuntimeError as exc:
            yield await _sse({"type": "error", "message": str(exc)})
            return
        finally:
            installer_shared._ollama_install_lock.release()
        yield await _sse({"type": "done", "already_installed": False, "binary": binary})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


class FinalizeBody(BaseModel):
    """Body for the POST /installer/finalize endpoint.

    Validated server-side so the wizard cannot smuggle in arbitrary engines
    or oversized model identifiers (defense in depth — same allowlist as
    `_VALID_ENGINES` for /installer/download).

    optional ``hf_token`` field. When provided (non-empty),
    OnboardingState.save() stores it to the macOS Keychain — never to disk.
    Length capped at 200 chars (HF tokens are ~40 chars; the cap protects
    against accidental paste of huge blobs).
    """

    # "local" = user picked a local models folder; model_id carries the
    # absolute folder path (no fixed model — the chat UI selector chooses).
    engine: str = Field(..., pattern="^(mlx|ollama|gguf|local)$")
    # 512 chars: model ids are short, but a "local" folder path can be long.
    model_id: str = Field(..., min_length=1, max_length=512)
    hf_token: str | None = Field(default=None, max_length=200)
    # 2026-05-22: BCP-47 language code chosen at the wizard welcome step.
    # Allowlist matches the UI locales (Català/Español/English). When None
    # the OnboardingState.save() helper preserves the previous lang (or
    # falls back to "en") so a wizard variant that omits the field still
    # works.
    lang: str | None = Field(default=None, pattern="^(ca|es|en)$")








@router.post("/finalize", operation_id="installer_finalize_post")
async def finalize_post(body: FinalizeBody, request: Request) -> JSONResponse:
    """Persist onboarding state and return the local API key and server status.

    the wizard calls this after a successful download. The model_path
    is derived from `model_id` (same logic as the download streamers). The
    state is written atomically to `$NEXE_DATA_DIR/onboarding.json`; the next
    sidecar restart will pick it up and configure the right engine.
    """
    # WS1-01: the primary key is only ever served to loopback clients.
    if not installer_shared._client_is_loopback(request):
        return JSONResponse(status_code=403, content={"detail": "Forbidden: loopback only"})
    # Symmetric guard with GET /finalize (INST-001): once onboarding has
    # completed, this unauthenticated, repeatable endpoint must not keep
    # re-serving NEXE_PRIMARY_API_KEY to any local process. A clean re-install
    # wipes the data dir, which resets is_completed().
    if OnboardingState.is_completed():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    try:
        model_path = installer_shared._resolve_model_path(body.engine, body.model_id)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )
    # if the wizard supplied an HF token, pass it to the
    # Keychain-aware save() — the token never lands on disk, only a
    # has_token=True marker in onboarding.json.
    # For "local", model_id is the folder path; persist a clear sentinel
    # instead (the chat UI selector chooses the real model). model_path keeps
    # the resolved folder so apply_to_env can set NEXE_STORAGE_PATH.
    saved_model_id = "local" if body.engine == "local" else body.model_id
    OnboardingState.save(
        engine=body.engine,
        model_id=saved_model_id,
        model_path=model_path,
        hf_token=body.hf_token,
        lang=body.lang,
    )
    # Clear runtime_state overrides for model env vars
    # for the model env vars so the freshly-saved OnboardingState is what
    # the next sidecar restart sees. Without this, a stale UI override from
    # an earlier session (set by routes_chat._switch_*_model) would shadow
    # the env var that apply_to_env() injects at startup.
    try:
        from core import runtime_state
        runtime_state.set_override("NEXE_MLX_MODEL", None)
        runtime_state.set_override("NEXE_LLAMA_CPP_MODEL", None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("installer/finalize: runtime_state cleanup failed: %s", exc)
    api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    return JSONResponse({"api_key": api_key, "status": "ready"})




@router.get("/finalize", operation_id="installer_finalize_get")
async def finalize_get(request: Request) -> JSONResponse:
    """Legacy GET endpoint — returns api_key + status without persisting state.

    The Advanced wizard flow (`engine === "local"` in step5-apikey.js) calls
    this exactly once: there is no engine/model_id to POST, so the wizard
    just fetches the api_key. Once onboarding has completed (either via the
    POST persisting OnboardingState or via this GET having been called once
    already), subsequent GETs return 404 — leaving the endpoint open would
    let any local process read NEXE_PRIMARY_API_KEY without authentication.

    The "first caller wins" race between marker check and write is resolved
    via O_CREAT | O_EXCL: only one concurrent invocation can create the
    marker; the rest receive FileExistsError and return 404. This closes
    the TOCTOU window that a simple ``exists() + touch()`` would leave open.
    """
    # WS1-01: the primary key is only ever served to loopback clients.
    if not installer_shared._client_is_loopback(request):
        return JSONResponse(status_code=403, content={"detail": "Forbidden: loopback only"})
    if OnboardingState.is_completed():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    marker = installer_shared._finalize_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        # Another (or this same) caller already consumed the legacy endpoint.
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    except OSError as exc:
        # Could not create the marker (e.g. read-only filesystem). Log and
        # still serve the key — the next request will hit the same OSError
        # and re-serve, which is no worse than the pre-fix behaviour and
        # avoids breaking the wizard if the data dir is misconfigured.
        logger.warning(
            "installer/finalize: failed to write idempotency marker: %s", exc
        )

    api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    return JSONResponse({"api_key": api_key, "status": "ready"})


@router.get("/check-metal", operation_id="installer_check_metal")
async def check_metal() -> JSONResponse:
    """Check if Apple Metal/MLX is available on this system.

    El wizard usa aquest endpoint per saber si pot oferir MLX com a backend.
    A Macs Intel (sense Metal) o Linux/Windows, mlx no s'ha d'oferir.
    Validat amb agentic audit 2026-05-20 (thread executor suficient,
    no cal subprocess). Memory pressure ~200-500 MB del MLX framework
    s'acceptarà perquè el sidecar ja el carregara per chat.
    """
    def _check() -> bool:
        try:
            import mlx.core as mx  # type: ignore[import]
            return bool(mx.metal.is_available())
        except Exception:
            return False
    loop = asyncio.get_event_loop()
    metal = await loop.run_in_executor(None, _check)
    return JSONResponse({
        "metal_available": metal,
        "platform": platform.system().lower(),
    })


@router.get("/state", operation_id="installer_state")
async def installer_state() -> JSONResponse:
    """Return the current onboarding state.

    El frontend Tauri usa aquest endpoint per saber si l'onboarding s'ha
    completat sense necessitat de llegir el fitxer JSON del disc. Util quan
    el sidecar es reinicia i el frontend vol decidir si mostrar wizard o UI.
    NO retorna api_key (sensible). Validat amb agentic audit 2026-05-20.
    """
    state = OnboardingState.load()
    if state is None:
        return JSONResponse({"completed": False})
    return JSONResponse({
        "completed": True,
        "engine": state.engine,
        "model_id": state.model_id,
        "has_token": getattr(state, "has_token", False),
    })
