# Memory System — server-nexe

Persistent, structured memory for LLM conversations. Extracts facts from user messages, validates them through a deterministic pipeline, and stores them in a dual-layer backend (SQLite + Qdrant).

## Architecture Overview

```
[User Message]
      │
      ▼
[Gate Heuristic] ── discards 70-80% (cost ~0, <3ms)
      │
      ▼
[Extractor] ── heuristic (zero LLM), detects identity/preferences/corrections
      │
      ▼
[Validator] ── 6 dimensions, decision tree, deterministic
      │
      ▼
[Staging Buffer] ── quarantine 48h, traceability
      │
      ├── promote → [Profile Store] (closed schema, 30+ attributes)
      └── promote → [Episodic Store] (facts, episodes, notebooks)

Storage:
  SQLite = source of truth (WAL mode, all tables)
  Qdrant = rebuildable semantic index (memory_index collection)
```

## Quick Start

```python
from memory.memory.memory_service import MemoryService

svc = MemoryService()
await svc.initialize()

# Store a fact
entry_id = await svc.remember("user1", "My name is Anna", trust_level="trusted")

# Recall
cards = await svc.recall("user1", "what's my name?")

# Profile
profile = await svc.get_profile("user1")

# Stats
stats = await svc.stats("user1")
```

## CLI Debug Commands

```bash
nexe memory stats --user-id default
nexe memory search "Barcelona" --user-id default
nexe memory inspect <entry-id> --user-id default
nexe memory mirror --user-id default
nexe memory gc --dry-run --user-id default
```

## Configuration Profiles

| Profile | LLM | Episodic Max | Token Cap | Half-life |
|---------|-----|-------------|-----------|-----------|
| `m1_8gb` | off | 1,000 | 800 | 60 days |
| `m1_16gb` | on (0.6) | 2,000 | 1,200 | 60 days |
| `server_gpu` | on (0.3) | 5,000 | 2,000 | 90 days |

## v1 Decisions (Frozen)

| Decision | v1 | NOT in v1 |
|----------|-----|-----------|
| Trust | 2 levels: trusted / untrusted | No 4 levels |
| Episodic dedup | 2 bands: >0.92 refresh, <0.92 new | No link-on-write |
| Graph overlay | OFF — related_ids inline (JSON) | No memory_edges table |
| Exploratory mode | CLI/user only | No API endpoint |
| Retrieve threshold | floor 0.45, ceiling 0.65 | No generic dynamic |
| Embedding model | paraphrase-multilingual-mpnet-base-v2 (768d) | No model change |
| Storage | SQLite = truth, Qdrant = rebuildable index | No Qdrant as source |
| user_id | Day 1 on all tables | No adding later |

## File Structure

```
memory/memory/
  memory_service.py     ← Single facade (MemoryService)
  config.py             ← Hardware profiles
  models/
    memory_entry.py     ← MemoryEntry, ExtractedFact, MemoryCard, etc.
    memory_types.py     ← TrustLevel, MemoryState, ValidatorDecision, etc.
  pipeline/
    gate.py             ← Heuristic gate (discard non-memorizable)
    extractor.py        ← Fact extraction (zero LLM)
    validator.py        ← 6-dimension decision tree
    schema_enforcer.py  ← Closed profile schema + aliases
  storage/
    sqlite_store.py     ← SQLite backend (9 tables, WAL)
    vector_index.py     ← Qdrant embedded wrapper
  workers/
    dreaming_cycle.py   ← Consolidation (staging → stores)
    gc_daemon.py        ← Garbage collection
    sync_worker.py      ← RDBMS → Vector sync
  retrieve/
    retriever.py        ← Multi-layer retrieve + re-rank
    formatter.py        ← Memory Cards for LLM context
  working_memory.py     ← RAM cache per session
  api/
    __init__.py         ← MemoryAPI (Qdrant facade)
    v1.py               ← REST endpoints
  engines/
    persistence.py      ← Legacy dual persistence (SQLite + Qdrant)
```

## License

See project root LICENSE.
