#!/usr/bin/env python3
"""
────────────────────────────────────
dev-tools/smoke_test.py
Smoke Test via API HTTP — Nexe Server

Tests the live server (localhost:9119) after installation.
Does NOT use pytest or TestClient — makes real HTTP requests.

Usage:
  python3 dev-tools/smoke_test.py
  python3 dev-tools/smoke_test.py --host localhost --port 9119
  python3 dev-tools/smoke_test.py --skip-gpu     # skips chat tests
  python3 dev-tools/smoke_test.py --verbose

Requires:
  - Nexe server running (./nexe go)
  - NEXE_PRIMARY_API_KEY in .env or environment variable
────────────────────────────────────
"""
import sys
import os
import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Colors ──────────────────────────────────────────────────
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
NC     = "\033[0m"

def ok(msg):    print(f"  {GREEN}✓{NC}  {msg}")
def fail(msg):  print(f"  {RED}✗{NC}  {msg}")
def warn(msg):  print(f"  {YELLOW}!{NC}  {msg}")
def info(msg):  print(f"  {CYAN}·{NC}  {msg}")
def section(t): print(f"\n{BOLD}{CYAN}── {t} ──{NC}")

# ── Global results ────────────────────────────────────────
PASSED = []
FAILED = []

def record(name, success, detail=""):
    if success:
        PASSED.append(name)
        ok(f"{name}{f'  ({detail})' if detail else ''}")
    else:
        FAILED.append(name)
        fail(f"{name}{f'  → {detail}' if detail else ''}")

# ── HTTP helper ──────────────────────────────────────────────
def request(method, url, headers=None, body=None, timeout=30):
    data = json.dumps(body).encode() if body else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310: dev smoke-test against operator-provided localhost server URL, no untrusted input
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}

def get(url, headers=None, timeout=10):
    return request("GET", url, headers=headers, timeout=timeout)

def post(url, headers=None, body=None, timeout=30):
    return request("POST", url, headers=headers, body=body, timeout=timeout)

def delete(url, headers=None, timeout=10):
    return request("DELETE", url, headers=headers, timeout=timeout)

# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Nexe API Smoke Test")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9119)
    parser.add_argument("--skip-gpu", action="store_true", help="Skip chat tests (GPU)")
    parser.add_argument("--skip-memory", action="store_true", help="Skip memory tests (Qdrant)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    BASE = f"http://{args.host}:{args.port}"

    # Read API key
    api_key = os.environ.get("NEXE_PRIMARY_API_KEY") or \
              os.environ.get("NEXE_ADMIN_API_KEY") or \
              _read_env_file()

    if not api_key:
        print(f"{RED}ERROR:{NC} NEXE_PRIMARY_API_KEY not found")
        print("  Define it in .env or: export NEXE_PRIMARY_API_KEY=your-key")
        sys.exit(1)

    H = {"X-API-Key": api_key}

    print(f"\n{BOLD}{GREEN}")
    print("  ╔══════════════════════════════════════╗")
    print("  ║   NEXE API SMOKE TEST                ║")
    print(f"  ║   {BASE:<38}║")
    print(f"  ║   {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<38}║")
    print("  ╚══════════════════════════════════════╝")
    print(NC)

    # ────────────────────────────────────────────────────────
    # 1. BASIC CONNECTIVITY
    # ────────────────────────────────────────────────────────
    section("1. Connectivity")

    status, body = get(f"{BASE}/health", headers=H)
    record("GET /health → 200", status == 200, f"status={status}")

    if status != 200:
        fail("Server not responding. Check that ./nexe go is running.")
        _print_summary()
        sys.exit(1)

    # Version
    version = body.get("version", "?")
    info(f"Server version: {version}")

    # Without API key → 401
    status_unauth, _ = get(f"{BASE}/health")
    # /health may be public — do not force 401 here
    info(f"Without API key → {status_unauth}")

    # ────────────────────────────────────────────────────────
    # 2. SECURITY
    # ────────────────────────────────────────────────────────
    section("2. Security")

    status, _ = get(f"{BASE}/security/report", headers=H)
    record("GET /security/report authenticated", status == 200, f"status={status}")

    status, _ = get(f"{BASE}/security/report", headers={"X-API-Key": "wrong-key"})
    record("GET /security/report wrong key → 401", status == 401, f"status={status}")

    # Path traversal
    status, _ = get(f"{BASE}/ui/static/../../../etc/passwd", headers=H)
    record("Path traversal blocked", status in [400, 403, 404], f"status={status}")

    # ────────────────────────────────────────────────────────
    # 3. WEB UI — SESSIONS
    # ────────────────────────────────────────────────────────
    section("3. Web UI Sessions")

    status, body = post(f"{BASE}/ui/session/new", headers=H)
    record("POST /ui/session/new", status == 200, f"status={status}")
    session_id = body.get("session_id", "") if status == 200 else ""

    if session_id:
        status, body = get(f"{BASE}/ui/session/{session_id}", headers=H)
        record("GET /ui/session/{id}", status == 200 and body.get("id") == session_id)

        status, body = get(f"{BASE}/ui/session/{session_id}/history", headers=H)
        record("GET /ui/session/{id}/history", status == 200 and "messages" in body)

        status, _ = delete(f"{BASE}/ui/session/{session_id}", headers=H)
        record("DELETE /ui/session/{id}", status == 200)

        status, _ = get(f"{BASE}/ui/session/{session_id}", headers=H)
        record("Session deleted → 404", status == 404)

    status, _ = get(f"{BASE}/ui/session/inexistent-xyz", headers=H)
    record("Non-existent session → 404", status == 404)

    status, body = get(f"{BASE}/ui/sessions", headers=H)
    record("GET /ui/sessions", status == 200 and "sessions" in body)

    # ────────────────────────────────────────────────────────
    # 4. RAG
    # ────────────────────────────────────────────────────────
    section("4. RAG / Semantic search")

    status, body = get(f"{BASE}/rag/health", headers=H)
    record("GET /rag/health", status == 200, f"status={status}")

    status, body = get(f"{BASE}/rag/info", headers=H)
    record("GET /rag/info", status == 200, f"status={status}")
    if args.verbose and status == 200:
        info(f"RAG info: {json.dumps(body, indent=2)[:200]}")

    # Semantic search (requires prior ingestion)
    status, body = post(f"{BASE}/rag/search", headers=H,
                        body={"query": "quin port fa servir NEXE", "top_k": 3})
    record("POST /rag/search → 200", status == 200, f"status={status}")

    if status == 200:
        results = body.get("results", body.get("documents", []))
        has_results = len(results) > 0
        record("RAG search finds results", has_results, f"{len(results)} results")

        if has_results:
            combined = " ".join(
                (r.get("content") or r.get("text") or r.get("page_content") or "")
                for r in results
            )
            has_port = "9119" in combined
            record("RAG finds port 9119 in docs", has_port,
                   "content OK" if has_port else f"content: {combined[:100]}")

    # ────────────────────────────────────────────────────────
    # 5. MEMORY (Qdrant)
    # ────────────────────────────────────────────────────────
    if not args.skip_memory:
        section("5. Persistent memory (Qdrant)")

        unique = f"smoke_test_{int(time.time())}"
        status, body = post(f"{BASE}/ui/memory/save", headers=H,
                            body={"content": f"Informació de prova: {unique}",
                                  "session_id": "smoke-test",
                                  "metadata": {"type": "fact"}})
        record("POST /ui/memory/save", status == 200, f"status={status}")
        save_ok = status == 200 and body.get("success")
        record("Memory save successful", bool(save_ok), body.get("message", ""))

        if save_ok:
            time.sleep(0.5)  # let Qdrant index
            status, body = post(f"{BASE}/ui/memory/recall", headers=H,
                                body={"query": unique, "limit": 3})
            record("POST /ui/memory/recall", status == 200, f"status={status}")

            if status == 200:
                results = body.get("results", [])
                found = any(unique in (r.get("content", "") or "") for r in results)
                record("Memory recall finds saved content", found,
                       f"{len(results)} results")

        # Validation: empty content → 400
        status, _ = post(f"{BASE}/ui/memory/save", headers=H,
                         body={"content": "", "session_id": "test"})
        record("Memory save without content → 400", status == 400, f"status={status}")
    else:
        warn("Memory: skip (--skip-memory)")

    # ────────────────────────────────────────────────────────
    # 6. CHAT (GPU required)
    # ────────────────────────────────────────────────────────
    if not args.skip_gpu:
        section("6. Chat (GPU + model)")

        # Create chat session
        status, body = post(f"{BASE}/ui/session/new", headers=H)
        chat_sid = body.get("session_id", "") if status == 200 else ""

        if not chat_sid:
            warn("Could not create chat session")
        else:
            # Empty message → 400
            status, _ = post(f"{BASE}/ui/chat", headers=H,
                             body={"message": "", "session_id": chat_sid})
            record("Chat empty message → 400", status == 400, f"status={status}")

            # Factual question about RAG docs
            print(f"\n  {CYAN}·{NC}  Sending question to model (may take 30-120s)...")
            t0 = time.time()
            status, body = post(f"{BASE}/ui/chat", headers=H,
                                body={"message": "Quin port fa servir el servidor NEXE per defecte? Respon en una sola línia.",
                                      "session_id": chat_sid},
                                timeout=120)
            elapsed = round(time.time() - t0, 1)
            record("POST /ui/chat → 200", status == 200, f"status={status}, {elapsed}s")

            if status == 200:
                response_text = (body.get("response") or body.get("message") or
                                 body.get("text") or str(body))
                has_port = "9119" in response_text
                record("Response contains '9119' (RAG works)", has_port,
                       f"{response_text[:150]}" if args.verbose else "")
                info(f"Response: {response_text[:200]}")

                # Intent to save to memory
                status2, body2 = post(f"{BASE}/ui/chat", headers=H,
                                      body={"message": "El meu nom de prova és SmokeUser_123, ho pots guardar?",
                                            "session_id": chat_sid},
                                      timeout=90)
                record("Chat intent save → 200", status2 == 200)
                if status2 == 200:
                    mem_action = body2.get("memory_action")
                    record("memory_action == 'save'", mem_action == "save",
                           f"memory_action={mem_action}")

            # Cleanup
            delete(f"{BASE}/ui/session/{chat_sid}", headers=H)
    else:
        warn("Chat GPU: skip (--skip-gpu)")

    # ────────────────────────────────────────────────────────
    # 7. UPLOAD (no GPU required)
    # ────────────────────────────────────────────────────────
    section("7. File upload")

    # Invalid extension
    boundary = "----SmokeTestBoundary"
    body_bytes = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test.exe"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
        f"MZ\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"{BASE}/ui/upload",
        data=body_bytes,
        headers={**H, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # nosec B310: dev smoke-test against operator-provided localhost server URL, no untrusted input
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    record("Upload .exe rejected → 400", status == 400, f"status={status}")

    # List files
    status, body = get(f"{BASE}/ui/files", headers=H)
    record("GET /ui/files", status == 200 and "files" in body, f"status={status}")

    # ────────────────────────────────────────────────────────
    # FINAL SUMMARY
    # ────────────────────────────────────────────────────────
    _print_summary()
    sys.exit(0 if not FAILED else 1)


def _read_env_file():
    """Read NEXE_PRIMARY_API_KEY from the local .env file."""
    env_path = Path(__file__).parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("NEXE_PRIMARY_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("NEXE_ADMIN_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _print_summary():
    total = len(PASSED) + len(FAILED)
    print(f"\n{BOLD}{'═'*50}{NC}")
    print(f"{BOLD}  SMOKE TEST SUMMARY{NC}")
    print(f"{'═'*50}")
    print(f"  {GREEN}Passed:{NC}  {len(PASSED)}/{total}")
    if FAILED:
        print(f"  {RED}Failed:{NC}  {len(FAILED)}/{total}")
        for f in FAILED:
            print(f"    {RED}✗{NC} {f}")
    else:
        print(f"\n  {GREEN}{BOLD}All correct ✓{NC}")
    print(f"{'═'*50}\n")


if __name__ == "__main__":
    main()
