"""
REAL availability probe of the Ollama API (finding #833).

A `socket.create_connection` that accepts does NOT mean the API is serving:
during startup the port can accept while the API returns 500 or hangs.
The right criterion is `GET /api/tags` == HTTP 200 — the same one the
app's canonical source uses (`plugins/ollama_module/core/ollama_runtime.py`,
`is_ollama_running`/`wait_ollama_ready`, async/httpx). This module is the
synchronous stdlib-only version for the standalone installer, which cannot
import `plugins/` (no precedent; the installer only imports `core.*`).
"""
import os
import time
import urllib.request

# Proxy-free opener (review #833): the default urlopen goes through
# HTTP_PROXY/the Windows registry even for 127.0.0.1 → a healthy Ollama
# showed up dead on corporate networks. The old socket.create_connection
# did not; we keep that immunity.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _resolve_base_url() -> str:
    """Stdlib mirror of the app's resolve_base_url() (review #833).

    The daemon we start (`ollama serve`) and `ollama pull` honor
    OLLAMA_HOST — the probe has to point at the SAME daemon or it will refuse
    installs with a custom host/port that used to work.
    """
    raw = (os.getenv("NEXE_OLLAMA_HOST") or os.getenv("OLLAMA_HOST") or "").strip()
    if not raw:
        return "http://127.0.0.1:11434"
    if "://" not in raw:
        raw = "http://" + raw
    scheme, _, rest = raw.partition("://")
    host_port = rest.split("/")[0]
    host, _, port = host_port.partition(":")
    if host in ("0.0.0.0", "::", "[::]"):  # nosec B104: normalization, not a bind
        host = "127.0.0.1"  # nosemgrep: hardcode.ip_address — deliberate loopback (normalization), not config
    return f"{scheme}://{host}:{port or '11434'}"


def ollama_api_alive(base_url: str | None = None, *, probe_timeout: float = 2.0) -> bool:
    """One probe: True only if GET /api/tags returns HTTP 200."""
    url = f"{base_url or _resolve_base_url()}/api/tags"
    try:
        with _OPENER.open(url, timeout=probe_timeout) as resp:  # nosec B310: local/internal-env host, fixed http scheme
            return getattr(resp, "status", None) == 200
    except Exception:  # nosec B110: any failure = "not ready" (best-effort probe)
        return False


def wait_ollama_api_ready(
    base_url: str | None = None,
    *,
    timeout: float = 60.0,
    interval: float = 1.0,
) -> bool:
    """Poll GET /api/tags until 200 or ``timeout`` seconds run out.

    Returns True when the API answers; False on timeout. Never raises.
    """
    base_url = base_url or _resolve_base_url()
    deadline = time.monotonic() + timeout
    while True:
        if ollama_api_alive(base_url):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)
