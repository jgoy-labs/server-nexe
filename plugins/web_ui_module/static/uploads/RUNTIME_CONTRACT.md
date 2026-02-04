# Runtime Contract - NAT v7.0

**Version:** 1.0
**Date:** 5 December 2025
**Status:** APPROVED

---

## 1. Overview

This document defines the **runtime contract** of NAT v7.0:
- System states
- Component failure behavior
- Recovery procedures
- Consistency guarantees

---

## 2. System States

### 2.1 State Diagram

```
                    ┌──────────────┐
         ┌─────────►│   HEALTHY    │◄─────────┐
         │          │  (100% ops)  │          │
         │          └──────┬───────┘          │
         │                 │                  │
         │            Partial                 │
         │            failure             Full
         │                 │              recovery
         │                 ▼                  │
         │          ┌──────────────┐          │
         │          │   DEGRADED   │──────────┤
         │          │  (50-99% ops)│          │
         │          └──────┬───────┘          │
         │                 │                  │
    Auto-recovery     Critical           Partial
         │            failure           recovery
         │                 │                  │
         │                 ▼                  │
         │          ┌──────────────┐          │
         └──────────│   MINIMUM    │──────────┘
                    │  (Core only) │
                    └──────┬───────┘
                           │
                      Total
                      failure
                           │
                           ▼
                    ┌──────────────┐
                    │    FAILED    │
                    │  (No service)│
                    └──────┬───────┘
                           │
                      Manual
                      intervention
                           │
                           ▼
                    ┌──────────────┐
                    │  REPAIRING   │
                    │ (Recovering) │
                    └──────────────┘
```

### 2.2 State Definitions

| State | % Operative | Description | Available Services |
|-------|-------------|-------------|-------------------|
| **HEALTHY** | 100% | All functioning | All |
| **DEGRADED** | 50-99% | Partial failure | Core + some modules |
| **MINIMUM** | 10-49% | Survival mode | Core API only |
| **FAILED** | 0% | System down | None |
| **REPAIRING** | Variable | Recovering | Progressive |

---

## 3. Component Failure Behavior

### 3.1 Failure Matrix

| Component Down | Resulting State | Affected Services | Recovery |
|----------------|-----------------|-------------------|----------|
| **Ollama** | DEGRADED | Chat, LLM inference | Auto (Circuit Breaker) |
| **Qdrant** | DEGRADED | RAG, Memory search | Auto (Circuit Breaker) |
| **SQLite** | MINIMUM | Persistence | Manual (backup restore) |
| **Doctor** | DEGRADED | Diagnostics | Auto (module restart) |
| **ModuleManager** | MINIMUM | All modules | Manual (restart NAT) |
| **NEXE (API)** | FAILED | Everything | Manual (restart process) |

### 3.2 Component Details

#### 3.2.1 When Ollama Falls

```python
class OllamaFailure:
    detection_time: "< 3 seconds"  # Circuit breaker detects
    state_transition: "HEALTHY -> DEGRADED"
    affected_endpoints: [
        "POST /api/v1/chat/send",
        "POST /api/v1/llm/generate",
        "POST /api/v1/embeddings/encode",  # If using Ollama
    ]
    unaffected_endpoints: [
        "GET /health",
        "GET /api/v1/rag/search",  # Uses cached embeddings
        "GET /api/v1/modules/status",
        "GET /api/v1/doctor/status",
    ]
    recovery: "Automatic when Ollama returns"
    user_message: "LLM temporarily unavailable. RAG and search work."
```

#### 3.2.2 When Qdrant Falls

```python
class QdrantFailure:
    detection_time: "< 5 seconds"
    state_transition: "HEALTHY -> DEGRADED"
    affected_endpoints: [
        "POST /api/v1/rag/search",
        "POST /api/v1/rag/upload",
        "POST /api/v1/memory/recall",
    ]
    unaffected_endpoints: [
        "GET /health",
        "POST /api/v1/chat/send",  # Works without RAG
        "GET /api/v1/doctor/status",
    ]
    recovery: "Automatic when Qdrant returns"
    user_message: "Semantic search unavailable. Basic chat works."
```

#### 3.2.3 When SQLite Corrupts

```python
class SQLiteFailure:
    detection_time: "< 1 second"
    state_transition: "HEALTHY -> MINIMUM"
    affected_endpoints: "All write operations"
    recovery: "MANUAL - Restore backup"
    procedure: [
        "1. Stop NAT",
        "2. cp silici/backup/latest.db silici/nat.db",
        "3. Verify integrity: sqlite3 silici/nat.db 'PRAGMA integrity_check'",
        "4. Restart NAT",
    ]
```

---

## 4. Consistency Guarantees

### 4.1 Atomicity

| Operation | Guarantee | Mechanism |
|-----------|-----------|-----------|
| Upload document | Atomic | SQLite transaction + rollback |
| Store memory | Atomic | Dual-write (SQLite + Qdrant) with compensation |
| Config change | Atomic | TOML atomic write |

### 4.2 Durability

| Component | Durability | Backup |
|-----------|------------|--------|
| SQLite | WAL + fsync | Every 5 min automatic |
| Qdrant | Segments + WAL | Every 15 min |
| Config TOML | Immediate | Git-tracked |

### 4.3 Idempotency

All write operations are idempotent:
- Re-upload same document -> Updates, doesn't duplicate
- Re-store same memory -> Updates timestamp
- Re-run workflow -> Same result

---

## 5. Recovery Procedures

### 5.1 Automatic Recovery

```
Trigger: Circuit Breaker detects service recovered
Action: Transition DEGRADED -> HEALTHY
Time: < 30 seconds after recovery
```

### 5.2 Manual Recovery

#### 5.2.1 Full Restart

```bash
# 1. Stop NAT
pkill -f "nexe.core.server_nexe"

# 2. Verify external services
curl http://localhost:11434/api/tags  # Ollama
curl http://localhost:6333/health     # Qdrant

# 3. Restart NAT
python -m nexe.core.server_nexe

# 4. Verify health
curl http://localhost:8123/health
python -m crom.core.doctor --quick
```

#### 5.2.2 Backup Restore

```bash
# 1. Stop NAT
pkill -f "nexe.core.server_nexe"

# 2. List available backups
ls -la silici/backup/

# 3. Restore
cp silici/backup/nat_YYYYMMDD_HHMMSS.db silici/nat.db

# 4. Verify integrity
sqlite3 silici/nat.db "PRAGMA integrity_check"

# 5. Restart and verify
python -m nexe.core.server_nexe &
sleep 5
curl http://localhost:8123/health
```

---

## 6. Monitoring

### 6.1 Health Endpoints

| Endpoint | Purpose | Recommended Frequency |
|----------|---------|----------------------|
| `GET /health` | General health | Every 10s |
| `GET /health/circuits` | Circuit Breakers state | Every 30s |
| `GET /api/v1/doctor/status` | Full diagnostics | Every 5 min |
| `GET /api/v1/modules/status` | Modules state | Every 1 min |

### 6.2 Recommended Alerts

| Condition | Severity | Action |
|-----------|----------|--------|
| `state == DEGRADED` > 5 min | WARNING | Investigate |
| `state == MINIMUM` | CRITICAL | Immediate intervention |
| `state == FAILED` | EMERGENCY | Full recovery procedure |
| Circuit OPEN > 2 min | WARNING | Check external service |

---

## 7. SLA Guarantees

### 7.1 Availability

| State | Target Availability |
|-------|---------------------|
| HEALTHY | 99.5% |
| DEGRADED acceptable | < 1% time |
| MINIMUM acceptable | < 0.1% time |
| FAILED acceptable | < 0.01% time |

### 7.2 Response Times

| Operation | P50 | P99 |
|-----------|-----|-----|
| Health check | < 10ms | < 50ms |
| RAG search | < 200ms | < 1s |
| LLM generate | < 2s | < 10s |
| Document upload | < 500ms | < 2s |

---

## 8. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-05 | Initial version |

---

*Document generated as part of NAT v7.0.1 maturity roadmap*
