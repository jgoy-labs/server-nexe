# Memory Architecture — v1

## The 4 Layers

```
┌─────────────────────────────────────────────────┐
│           WORKING MEMORY (RAM)                   │
│  Current session facts. Dies on close.           │
│  Participates in retrieve FIRST.                 │
│  Flush to staging every N turns + at shutdown.   │
└────────────────────┬────────────────────────────┘
                     │ (async, post-response)
┌────────────────────▼────────────────────────────┐
│           STAGING BUFFER (SQLite)                │
│  Quarantine + evidence + pending decision.       │
│  TTL 48h. Everything enters here first.          │
│  Traceable: stores scores and cause.             │
└────────────────────┬────────────────────────────┘
                     │ (dreaming cycle)
          ┌──────────┴──────────┐
          ▼                     ▼
┌──────────────────┐   ┌────────────────────────┐
│  PROFILE STORE   │   │   EPISODIC STORE        │
│  (SQLite, EAV)   │   │   (SQLite + Qdrant)     │
│                  │   │                          │
│  Closed schema   │   │  RDBMS = owns data       │
│  30+ attributes  │   │  Qdrant = semantic index  │
│  Upsert only     │   │  (rebuildable from RDBMS) │
│  History tracked │   │                          │
└──────────────────┘   └────────────────────────┘
```

## Pipeline Flow

```
[Message] → Gate → Extractor → Validator → Staging
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼              ▼
                 reject      stage_only    promote/upsert
```

### Gate (pipeline/gate.py)
- Length check: <20 chars → reject (bypassed by high-importance patterns)
- Token uniqueness ratio <0.3 → repetitive → reject
- Pure question → reject
- Model-generated (non MEM_SAVE) → reject
- High-importance patterns: identity, health, restrictions → bypass length

### Extractor (pipeline/extractor.py)
- Zero LLM, heuristic only (v1)
- Detects: identity (name, location, occupation), preferences, corrections, allergies
- Multilingual: Catalan, Spanish, English
- Output: `ExtractedFact{content, entity, attribute, value, tags, importance}`

### Schema Enforcer (pipeline/schema_enforcer.py)
- 30+ predefined attributes across 6 categories
- Resolution: exact match → alias match → null (goes to episodic)
- Aliases: multilingual (ca/es/en), auto-learnable

### Validator (pipeline/validator.py)
- 6 dimensions: trust, explicitness, stability, future_utility, novelty, contradiction_risk
- v1: 2 trust levels (trusted / untrusted)
- Decisions: reject, stage_only, promote_episodic, upsert_profile

## Data Schema (SQLite)

9 tables:

| Table | Purpose |
|-------|---------|
| `profile` | EAV with closed schema, user identity |
| `profile_history` | Change log for profile attributes |
| `episodic` | Facts, episodes, notebooks, summaries |
| `staging` | Quarantine buffer (48h TTL) |
| `tombstones` | Anti-zombie re-insertion (90d TTL) |
| `memory_events` | Audit log |
| `attribute_aliases` | Schema enforcer alias mappings |
| `gc_log` | Garbage collection history |
| `user_activity` | Session tracking per user |

All tables have `user_id` from day 1. All SQL parameterized (`?`).

## Vector Index (Qdrant)

- Collection: `memory_index`
- Model: `paraphrase-multilingual-mpnet-base-v2` (768 dims)
- Payload: rdbms_id, user_id, namespace, memory_type, state, importance, trust_level
- Text lives ONLY in SQLite — Qdrant stores vectors + metadata for filtering

## Retrieve Flow

1. Working Memory (RAM, current session)
2. Profile Store (deterministic lookup)
3. Staging (recent unprocessed claims)
4. Vector Search (semantic, 2-phase threshold)
5. Re-rank (additive score)
6. Token budget: min(context_window * 0.10, cap)

### Threshold (v1 frozen)
- Base: 0.40 (broad candidate retrieval)
- Floor: 0.45 (never below)
- Ceiling: 0.65 (never above)
- Fallback: 0.55 (few results)

## Config Profiles

```yaml
m1_8gb:        # Default — no LLM, conservative budgets
m1_16gb:       # LLM extraction enabled, larger budgets
server_gpu:    # Full LLM, large budgets, longer half-life
```

## MemoryService Facade

Single entry point for all consumers:

```python
MemoryService.remember()    # Write path (gate → extractor → validator → store)
MemoryService.recall()      # Read path (multi-layer → rerank → budget → cards)
MemoryService.get_profile() # Direct profile access
MemoryService.forget()      # Real delete + tombstone + history redaction
MemoryService.stats()       # Counts per store
```

## Design Principles

1. **Remember less, but better** — pipeline filters aggressively
2. **Persistence by promotion** — data earns permanence
3. **Better empty than dirty** — no context injection if quality is low
4. **SQLite is truth** — Qdrant is a rebuildable index
5. **Single facade** — all consumers go through MemoryService
6. **Zero LLM fallback** — everything works without a loaded model
