#!/bin/bash
# ────────────────────────────────────────────────────────
# Server Nexe — Docker entrypoint
# Starts Qdrant (embedded) + Nexe server
# ────────────────────────────────────────────────────────

set -e

echo "[nexe] Starting Qdrant (embedded)..."
./qdrant --storage-path /app/storage/qdrant --disable-telemetry &
QDRANT_PID=$!

# Wait for Qdrant to be ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:6333/healthz > /dev/null 2>&1; then
        echo "[nexe] Qdrant ready (PID $QDRANT_PID)"
        break
    fi
    sleep 0.5
done

echo "[nexe] Starting server on port 9119..."
exec python -m core.app
