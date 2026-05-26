"""Minimal FastAPI sidecar for POC — validates PBS + uv packaging approach.

/shutdown actually stops uvicorn (returns JSON then triggers process exit) so
graceful_quit (Rust) can flush state cleanly before SIGKILL.

Security: Bearer token read from stdin at startup. All endpoints require
Authorization: Bearer <token> — any other caller (local or not) gets 401.
"""

import asyncio
import os
import sys

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="nexe-sidecar-poc", version="0.1.0")

# CORS: allow Tauri webview origins (tauri://localhost in prod, http://localhost:1420
# in Vite dev mode). Required so the web UI can call the sidecar directly from JS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420", "http://tauri.localhost"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "HEAD"],
    allow_headers=["*"],
)

# C25: token flow — Rust writes "<token>\n" to the launcher's stdin.
# The launcher (build-sidecar.sh) reads it via `read -r` and exports it as
# NEXE_TOKEN_INTERNAL. We read it here and immediately remove it from the
# environment so it does not persist in /proc/<pid>/environ after startup.
_BEARER_TOKEN: str = os.environ.pop("NEXE_TOKEN_INTERNAL", "")
if not _BEARER_TOKEN:
    sys.stderr.write("sidecar: NEXE_TOKEN_INTERNAL not set — aborting\n")
    os._exit(1)


def _require_auth(authorization: str | None) -> None:
    """Raise 401 if the Bearer token is missing or wrong."""
    if authorization != f"Bearer {_BEARER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/api/v1/system/health")
async def health(authorization: str | None = Header(default=None)):
    """Return system info (Python version, platform, pid) for health checks."""
    _require_auth(authorization)
    return JSONResponse(
        {
            "status": "ok",
            "python": sys.version,
            "executable": sys.executable,
            "prefix": sys.prefix,
            "platform": sys.platform,
            "pid": os.getpid(),
        }
    )


@app.get("/health/ready")
async def health_ready():
    """Public readiness probe — no auth required.

    Called directly from the web UI JS (not through the Rust fetch_from_sidecar
    proxy). Standard practice: readiness/liveness endpoints are public so that
    orchestrators, load balancers, and UI health overlays can poll without credentials.
    """
    # Web UI checks for status == "healthy" (server-nexe convention).
    return JSONResponse({"status": "healthy"})


async def _exit_after_response():
    """Schedule os._exit(0) AFTER the response is flushed.

    A short sleep yields control back to uvicorn so the JSON response gets
    written to the wire; then os._exit kills the process. We use os._exit (not
    sys.exit) to skip Python's atexit machinery — uvicorn workers may otherwise
    hang waiting on orphan tasks during teardown.
    """
    await asyncio.sleep(0.05)
    os._exit(0)


@app.post("/api/v1/system/shutdown")
async def shutdown(authorization: str | None = Header(default=None)):
    """Graceful shutdown — return 'shutting_down' then exit the process.

    The graceful_quit handler in lifecycle.rs POSTs here with a short timeout
    BEFORE falling back to child.kill(). This gives the process a chance to
    flush state. The POC has no state to flush, but the contract is in place
    for when the real server-nexe lives in this sidecar.
    """
    _require_auth(authorization)
    asyncio.create_task(_exit_after_response())
    return JSONResponse({"status": "shutting_down"})


@app.get("/")
async def root(authorization: str | None = Header(default=None)):
    """Root endpoint — confirms the sidecar is alive."""
    _require_auth(authorization)
    return JSONResponse({"message": "nexe-sidecar-poc running"})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("NEXE_PORT", "8765"))
    host = os.environ.get("NEXE_HOST", "")
    if not host:
        sys.stderr.write("sidecar: NEXE_HOST not set — aborting\n")
        os._exit(1)
    uvicorn.run(app, host=host, port=port)
