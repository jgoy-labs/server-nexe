"""
────────────────────────────────────
Server Nexe
Location: plugins/security/core/auth_rate_limit.py
Description: Per-IP failed-auth window used by BOTH conversation paths (D-I / #883).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os
import time

# Single-worker server (uvicorn workers=1) — no lock.
auth_failures: dict[str, list[float]] = {}
AUTH_FAILURE_LIMIT: int = int(os.getenv("NEXE_UI_RATE_LIMIT", "20"))
AUTH_FAILURE_WINDOW: float = float(os.getenv("NEXE_UI_RATE_WINDOW", "60.0"))


def client_ip(request) -> str:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return str(host) if host else "unknown"


def check_auth_failure_rate_limit(ip: str) -> bool:
    """True if this IP has already used up the failure window."""
    now = time.monotonic()
    cutoff = now - AUTH_FAILURE_WINDOW
    stamps = [t for t in auth_failures.get(ip, []) if t > cutoff]
    auth_failures[ip] = stamps
    return len(stamps) >= AUTH_FAILURE_LIMIT


def record_auth_failure_attempt(ip: str) -> None:
    now = time.monotonic()
    cutoff = now - AUTH_FAILURE_WINDOW
    stamps = [t for t in auth_failures.get(ip, []) if t > cutoff]
    stamps.append(now)
    auth_failures[ip] = stamps
