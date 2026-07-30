"""
Probe de disponibilitat REAL de l'API d'Ollama (finding #833).

Un `socket.create_connection` que accepta NO vol dir que l'API serveixi:
durant l'arrencada el port pot acceptar i l'API respondre 500 o penjar-se.
El criteri correcte és `GET /api/tags` == HTTP 200 — el mateix que usa la
font canònica de l'app (`plugins/ollama_module/core/ollama_runtime.py`,
`is_ollama_running`/`wait_ollama_ready`, async/httpx). Aquest mòdul és la
versió síncrona i stdlib-pura per a l'installer standalone, que no pot
importar `plugins/` (cap precedent; l'installer només importa `core.*`).
"""
import os
import time
import urllib.request

# Proxy-free opener (review #833): el urlopen per defecte passa per
# HTTP_PROXY/registre de Windows fins i tot per a 127.0.0.1 → un Ollama sa
# sortia com a mort en xarxes corporatives. L'antic socket.create_connection
# no hi passava; conservem aquesta immunitat.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _resolve_base_url() -> str:
    """Mirall stdlib de resolve_base_url() de l'app (review #833).

    El daemon que engeguem (`ollama serve`) i el `ollama pull` honoren
    OLLAMA_HOST — el probe ha d'apuntar al MATEIX daemon o refusarà
    instal·lacions amb host/port custom que abans funcionaven.
    """
    raw = (os.getenv("NEXE_OLLAMA_HOST") or os.getenv("OLLAMA_HOST") or "").strip()
    if not raw:
        return "http://127.0.0.1:11434"
    if "://" not in raw:
        raw = "http://" + raw
    scheme, _, rest = raw.partition("://")
    host_port = rest.split("/")[0]
    host, _, port = host_port.partition(":")
    if host in ("0.0.0.0", "::", "[::]"):  # nosec B104: normalització, no bind
        host = "127.0.0.1"
    return f"{scheme}://{host}:{port or '11434'}"


def ollama_api_alive(base_url: str | None = None, *, probe_timeout: float = 2.0) -> bool:
    """Un sol probe: True només si GET /api/tags respon HTTP 200."""
    url = f"{base_url or _resolve_base_url()}/api/tags"
    try:
        with _OPENER.open(url, timeout=probe_timeout) as resp:  # nosec B310: host local/env intern, esquema http fix
            return getattr(resp, "status", None) == 200
    except Exception:  # nosec B110: qualsevol fallada = "no llest" (probe best-effort)
        return False


def wait_ollama_api_ready(
    base_url: str | None = None,
    *,
    timeout: float = 60.0,
    interval: float = 1.0,
) -> bool:
    """Polling de GET /api/tags fins a 200 o esgotar ``timeout`` segons.

    Retorna True quan l'API respon; False en timeout. No aixeca mai.
    """
    base_url = base_url or _resolve_base_url()
    deadline = time.monotonic() + timeout
    while True:
        if ollama_api_alive(base_url):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)
