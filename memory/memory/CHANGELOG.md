# Changelog — Memory System

## v1.0.0 (2026-03-30) — Architecture Rewrite

### What changed vs previous system

**Before (v0.x):**
- FlashMemory (RAM) + RAMContext + PersistenceManager
- IngestionPipeline with basic deduplication
- Direct Qdrant writes from chat endpoints
- No validation pipeline
- No profile schema
- No staging buffer
- No tombstones
- No user_id isolation

**After (v1.0):**
- Full extraction pipeline: Gate → Extractor → Validator → Staging
- Profile Store with closed schema (30+ attributes, EAV)
- Episodic Store with importance scoring and decay
- Staging Buffer with 48h quarantine and traceability
- Tombstones for real forget (anti-zombie)
- MemoryService facade (single entry point)
- Hardware config profiles (m1_8gb, m1_16gb, server_gpu)
- CLI debug commands (inspect, search, stats, mirror, gc)
- All tables with user_id from day 1
- All SQL parameterized (zero f-strings)

### New files

| File | Lines | Purpose |
|------|-------|---------|
| `memory_service.py` | 400 | Single facade |
| `config.py` | 132 | Hardware profiles |
| `pipeline/gate.py` | 160 | Heuristic gate |
| `pipeline/extractor.py` | 285 | Fact extraction |
| `pipeline/validator.py` | 181 | 6-dimension validator |
| `pipeline/schema_enforcer.py` | 185 | Profile schema |
| `storage/sqlite_store.py` | 370 | SQLite backend (9 tables) |
| `storage/vector_index.py` | 201 | Qdrant wrapper |
| `workers/dreaming_cycle.py` | — | Consolidation (Dev1) |
| `workers/gc_daemon.py` | — | Garbage collection (Dev1) |
| `workers/sync_worker.py` | — | RDBMS→Vector sync (Dev1) |
| `retrieve/retriever.py` | — | Multi-layer retrieve (Dev1) |
| `retrieve/formatter.py` | — | Memory Cards (Dev1) |
| `working_memory.py` | — | RAM cache (Dev1) |

### Modified files

| File | Change |
|------|--------|
| `models/memory_types.py` | +TrustLevel, MemoryState, ValidatorDecision, StagingStatus |
| `models/memory_entry.py` | +ExtractedFact, ValidatorResult, MemoryCard, MemoryStats |
| `module.py` | +MemoryService lifecycle, +get_memory_service() |
| `router.py` | +/stats, +/profile endpoints |
| `cli.py` | +inspect, search, mirror, gc commands |
| `api/__init__.py` | Default qdrant_path=storage/vectors |
| `api/v1.py` | MemoryService integration |
| `engines/persistence.py` | Default qdrant_path=storage/vectors |
| Workflow nodes | MemoryService path + legacy fallback |
| Chat endpoints | MemoryService integration |

### v1 Decisions (frozen)

- Trust: 2 levels (trusted/untrusted)
- Episodic dedup: 2 bands (>0.92 refresh, <0.92 new)
- Graph overlay: OFF (related_ids inline)
- Exploratory mode: CLI/user only
- Retrieve threshold: floor 0.45, ceiling 0.65
- Embedding model: paraphrase-multilingual-mpnet-base-v2 (768d)
- Storage: SQLite = truth, Qdrant = rebuildable
- user_id: day 1 on all tables

### Test coverage

- 50 contract tests (gate, extractor, validator, schema, sqlite, working memory, retriever, service)
- 4019 total tests passing (zero regressions from baseline)
