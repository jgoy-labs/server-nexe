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
QDRANT_READY=false
for i in $(seq 1 30); do
    if curl -sf http://localhost:6333/health > /dev/null 2>&1; then
        echo "[nexe] Qdrant ready (PID $QDRANT_PID)"
        QDRANT_READY=true
        break
    fi
    sleep 0.5
done

if [ "$QDRANT_READY" = "false" ]; then
    echo "[nexe] WARNING: Qdrant did not start within 15s — RAG/memory may be unavailable"
fi

echo "[nexe] Starting server on port 9119..."
exec python -m core.app
