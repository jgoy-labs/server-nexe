# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-rag-system
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Complete reference of the server-nexe RAG memory system (v1.0.1-beta). Covers 3 Qdrant collections with thresholds, MEM_SAVE automatic memory, delete intent (DELETE_THRESHOLD 0.20 post-Bug #18), session-isolated document upload, embeddings (768D, fastembed ONNX primary offline), chunking parameters, context building with i18n labels, RAG weight visualization, RAG injection sanitization (_filter_rag_injection), 2-turn clear_all confirmation, precomputed KB embeddings, smart pruning, deduplication, TextStore for encrypted text, and Qdrant payloads without text."
tags: [rag, embeddings, qdrant, memory, mem_save, collections, thresholds, chunking, vectors, semantic-search, documents, session-isolation, delete-intent, pruning, deduplication, sanitization, text-store, encryption]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# RAG System — server-nexe 1.0.1-beta

## Table of contents

- [How RAG works in server-nexe](#how-rag-works-in-server-nexe)
- [Qdrant Collections](#qdrant-collections)
- [Qdrant Payloads (no text)](#qdrant-payloads-no-text)
- [TextStore (new in v0.9.0)](#textstore-new-in-v090)
- [Embeddings](#embeddings)
- [MEM_SAVE — Automatic Memory](#mem_save--automatic-memory)
  - [2-turn `clear_all` confirmation](#2-turn-clear_all-confirmation)
  - [RAG injection sanitisation (`_filter_rag_injection`)](#rag-injection-sanitisation-_filter_rag_injection)
- [RAG Context Sanitization](#rag-context-sanitization)
- [Document Upload with Session Isolation](#document-upload-with-session-isolation)
- [Document Ingestion](#document-ingestion)
  - [System documentation (nexe_documentation)](#system-documentation-nexe_documentation)
  - [User knowledge (user_knowledge via CLI)](#user-knowledge-user_knowledge-via-cli)
- [Context Building](#context-building)
- [RAG Weight Visualization](#rag-weight-visualization)
- [Smart Pruning (personal_memory collection)](#smart-pruning-personal_memory-collection)
- [Qdrant Storage](#qdrant-storage)
- [Key Configuration](#key-configuration)
- [Limitations](#limitations)
- [Main Endpoints for RAG](#main-endpoints-for-rag)

## In 30 seconds

- **3 Qdrant collections:** `personal_memory`, `user_knowledge`, `nexe_documentation`
- **`fastembed` ONNX embeddings** (multilingual, 768 dimensions, offline)
- **Top-K retrieval** with per-collection thresholds (0.3 / 0.35 / 0.4)
- **Automatic MEM_SAVE:** the model extracts facts from conversations and saves them
- **`_filter_rag_injection`** neutralises malicious tags (MEM_SAVE, MEM_DELETE, OLVIDA, MEMORIA) on ingest and retrieval

---

RAG (Retrieval-Augmented Generation) is the persistent memory system of server-nexe. It augments the LLM's responses by injecting relevant information retrieved from vector memory into the prompt context.

## How RAG works in server-nexe

1. User sends a message
2. Message is converted to a 768-dimensional embedding vector
3. Qdrant searches 3 collections for similar vectors (cosine similarity)
4. Matching results are sanitized via `_sanitize_rag_context()` to filter injection patterns
5. Sanitized results are injected into the LLM prompt as context
6. LLM generates a response using the augmented context
7. MEM_SAVE: the model also extracts facts from the conversation and saves them to memory (same LLM call)

## Qdrant Collections

server-nexe uses 3 specialized Qdrant collections. Each has a different purpose and similarity threshold.

| Collection | Purpose | Threshold | Top-K | Content |
|-----------|---------|-----------|-------|---------|
| `nexe_documentation` | System documentation (this knowledge folder) | 0.4 | 3 | Auto-ingested from `docs/` and `knowledge/` at install |
| `user_knowledge` | Documents uploaded by the user | 0.35 | 3 | Uploaded via Web UI or `nexe knowledge ingest`. Session-isolated via session_id metadata |
| `personal_memory` | Conversation memory (MEM_SAVE) | 0.3 | 2 | Automatic extraction from chat. Max 500 entries with smart pruning |

**Search order:** nexe_documentation first (system priority), then user_knowledge, then personal_memory.

**Thresholds are configurable** via environment variables:
- `NEXE_RAG_DOCS_THRESHOLD` (default: 0.4)
- `NEXE_RAG_KNOWLEDGE_THRESHOLD` (default: 0.35)
- `NEXE_RAG_MEMORY_THRESHOLD` (default: 0.3)

The Web UI also allows real-time threshold adjustment via a slider (default 0.30, range configurable).

## Qdrant Payloads (no text)

As of v0.9.0, Qdrant payloads **no longer contain text content**. Each payload only stores:
- `entry_type` — the type of entry
- `original_id` — link back to SQLite for the full text

All text lives in SQLite (optionally encrypted via SQLCipher). This means even without encryption enabled, Qdrant vectors alone cannot reconstruct the original text content.

## TextStore (new in v0.9.0)

`TextStore` (`memory/memory/api/text_store.py`) is a SQLite-backed storage for RAG document text, decoupled from Qdrant:

- Stores document text with `document_id` for linkback
- Optionally encrypted via SQLCipher when `crypto_provider` is available
- Used by `store_document()`, `search_documents()`, `get_document()`, `delete_document()`
- Backwards compatible: if `text_store` is not provided, legacy behavior (text in Qdrant payload) is used

## Embeddings

**Primary model (offline, always available):** `paraphrase-multilingual-mpnet-base-v2` via **fastembed (ONNX)** — 768 dimensions, multilingual. It is the **primary backend** since v0.9.3 (migrated from sentence-transformers to fastembed, PyTorch removed ~600 MB). Works without Ollama, without network, and ships **bundled in the DMG** to guarantee offline installation.

**Optional model (via Ollama):** `nomic-embed-text` — 768 dimensions. Configurable via `NEXE_OLLAMA_EMBED_MODEL`. Used only if the user enables it explicitly; **it is not the primary path**.

**Precomputed KB embeddings** (v0.9.8+): files in `knowledge/` have precomputed embeddings in `knowledge/.embeddings/`. At startup, if the hashes match, the system skips the computation and loads directly (10.7× cold-boot speedup). Embeddings regenerate automatically if the content changes.

All vectors are stored with 768 dimensions. This value is centralized in `memory/memory/constants.py` as `DEFAULT_VECTOR_SIZE = 768`.

**Similarity metric:** Cosine similarity. Range: -1 (opposite) to +1 (identical).

## MEM_SAVE — Automatic Memory

server-nexe has an automatic memory system similar to ChatGPT or Claude. The model extracts facts from conversations and saves them to memory within the same LLM call (zero extra latency).

**How it works:**
1. The system prompt instructs the model to extract facts: names, jobs, locations, preferences, projects, deadlines
2. The model outputs `[MEM_SAVE: fact]` markers within its response
3. routes_chat.py parses these markers and removes them from the visible stream
4. Facts are saved to `personal_memory` collection
5. The UI shows `[MEM:N]` indicator with the count of saved facts

**Intent detection (trilingual ca/es/en):**
- **Save:** "Recorda que...", "Guarda a memòria", "Remember that..."
- **Delete:** "Oblida que...", "Esborra-ho", "Forget that...", "Delete from memory"
- **Recall:** Automatic via RAG search on every message

**Auto-save filters (what is NOT saved):**
- Questions (contain "?")
- Commands ("nexe", "status", etc.)
- Greetings ("hola", "hello")
- Junk (less than 10 characters)
- Negative/junk patterns (regex filter for non-informative content)

**Deduplication:** Before saving, checks similarity with existing entries. If similarity > 0.80, the entry is considered duplicate and not saved.

**Complete MEM_SAVE flow:**

```
LLM Response
    │
    ▼
routes_chat.py — _extract_safe_mem_saves()
    │  · Strict regex: [MEM_SAVE: <text 5-200 chars>]
    │  · Normalises [MEMORIA: ...] → [MEM_SAVE: ...]
    │  · Validates character whitelist (safe unicode)
    │  · Rejects injection keywords, user prompt echo
    │
    ├─── clean text → visible stream (user never sees the marker)
    │
    ▼
chat_memory.py — auto_save_to_memory()
    │  · Creates personal_memory collection if missing
    │  · Checks duplicates (similarity > 0.80 → discards)
    │
    ▼
Qdrant — personal_memory collection
    · 768D vector (fastembed/ONNX)
    · Search threshold: 0.3
    · Max 500 entries (smart pruning)
```

**Delete intent (MEM_DELETE):** When the user says "forget that X", searches for entries with similarity >= **DELETE_THRESHOLD (0.20 since v0.9.9)**. Deletes the closest match. Anti-re-save guard: `_recently_deleted_facts` prevents the model from re-saving a just-deleted fact within the same session.

> **Bug #18 fix (v0.9.9):** The previous threshold (0.70) was too high and no match passed the check. It was adjusted to **0.20** after 8 real e2e tests (`tests/integration/test_mem_delete_e2e.py`) against embedded Qdrant + fastembed. Deletion now works consistently.

### 2-turn `clear_all` confirmation

If the user asks to delete **everything** (patterns like "delete all memory", "forget everything", "olvida todo"), the system does **NOT delete immediately**. Instead:

1. **Turn 1:** The server detects the `CLEAR_ALL_TRIGGERS` pattern, marks `session._pending_clear_all = True` and asks for explicit confirmation ("Are you sure? This will erase all of your memory. Reply 'yes' to confirm.").
2. **Turn 2:** If the user confirms with a short affirmative pattern (`yes`, `confirm`, `ok`, etc.), the collection is deleted. Any other message cancels the operation and resets the flag.

This prevents accidental mass wipes caused by an ambiguous message or an injected instruction from a document/prompt.

### RAG injection sanitisation (`_filter_rag_injection`)

Before injecting RAG context into the LLM prompt (ingest + retrieval), `_filter_rag_injection` **neutralises control tags** that could manipulate memory via side-effect:

- `[MEM_SAVE:…]` → removed (prevents the model from auto-saving just because it sees the pattern in a document)
- `[MEM_DELETE:…]` → removed
- `[OLVIDA:…]` / `[OBLIT:…]` / `[FORGET:…]` → removed (trilingual delete intents)
- `[MEMORIA:…]` → removed

This applies **both on ingest** (when a document or memory is stored) **and on retrieval** (when content is fetched for injection into the prompt), creating a double barrier against RAG injection.

**Large document truncation:** If an uploaded document is too large for the available context, it is truncated and the UI shows a yellow warning via the SSE marker `[DOC_TRUNCATED:XX%]` indicating the percentage discarded.

## RAG Context Sanitization

`_sanitize_rag_context()` filters retrieved RAG content before injecting it into the LLM prompt. This prevents stored documents or memory entries from containing injection patterns that could manipulate the model's behavior.

Applied in the Web UI pipeline (`routes_chat.py`) consistently with the API pipeline.

## Document Upload with Session Isolation

Documents uploaded via the Web UI are indexed into `user_knowledge` collection with `session_id` in the metadata. This means:

- Documents are only visible within the session where they were uploaded
- No cross-session contamination of document context
- Documents persist within the session (not cleared on page refresh)
- Metadata is generated without LLM (instant, no model required)

**Supported formats:** .txt, .md, .pdf (with magic bytes validation SEC-004)
**Chunking for uploads:** Dynamic based on document size -- 800 chars (<20K), 1000 (<100K), 1200 (<300K), 1500 (>=300K). If the document has a valid RAG header, the specified chunk_size is used.

## Document Ingestion

### System documentation (nexe_documentation)
- Source: `docs/` folder + `README.md`
- Chunking: 500 characters per chunk, 50 characters overlap
- Ingested via `core/ingest/ingest_docs.py`
- Recreates the collection on each ingestion (fresh start)

### User knowledge (user_knowledge via CLI)
- Source: `knowledge/` folder (ca/en/es subfolders)
- Chunking: 1500 characters per chunk by default (configurable via RAG header chunk_size), overlap = max(50, chunk_size/10)
- Ingested via `core/ingest/ingest_knowledge.py`
- Supports RAG headers with metadata (`#!RAG id=..., priority=...`)

## Context Building

When RAG finds relevant results, they are injected into the LLM prompt in 3 labeled categories:

| Category | Label (EN) | Label (CA) | Label (ES) | Source collection |
|----------|-----------|-----------|-----------|-------------------|
| System docs | SYSTEM DOCUMENTATION | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | nexe_documentation |
| Technical docs | TECHNICAL DOCUMENTATION | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | user_knowledge |
| User memory | USER MEMORY | MEMORIA USUARI | MEMORIA USUARIO | personal_memory |

**Context limits:**
- `MAX_CONTEXT_CHARS` = 24000 (configurable via `NEXE_MAX_CONTEXT_CHARS` env var)
- RAG context is truncated if it exceeds available space after subtracting system prompt, history, and current message

## RAG Weight Visualization

The Web UI and CLI show RAG relevance scores:

- **RAG_AVG marker:** Average score across all retrieved results
- **RAG_ITEM markers:** Individual score per source with collection name
- **UI badge:** Color-coded bar (green > 0.7, yellow 0.4-0.7, orange < 0.4)
- **Expandable detail:** Click to see individual source scores
- **CLI:** Use `--verbose` flag to see per-source detail

## Smart Pruning (personal_memory collection)

When `personal_memory` exceeds `MAX_MEMORY_ENTRIES` (500), smart pruning removes the lowest-scored entries:

**Retention score formula:**
- type_weight (0.4): weight based on memory type
- access_score (0.3): how recently accessed
- recency_score (0.3): how recently created
- Temporal decay bonus: +15% for entries within 7 days (`TEMPORAL_DECAY_DAYS = 7`)

## Qdrant Storage

Qdrant runs in embedded mode via `QdrantClient(path=...)` in the singleton pool `core/qdrant_pool.py`. Data stored at:
```
storage/vectors/
├── collection/
│   ├── nexe_documentation/
│   ├── personal_memory/
│   └── user_knowledge/
└── meta.json
```

**Mode:** embedded (no external server, no port). Data is loaded directly from the filesystem via RocksDB.
**Algorithm:** HNSW (Hierarchical Navigable Small World) for fast approximate nearest neighbor search

## Key Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| NEXE_RAG_DOCS_THRESHOLD | 0.4 | Minimum score for nexe_documentation |
| NEXE_RAG_KNOWLEDGE_THRESHOLD | 0.35 | Minimum score for user_knowledge |
| NEXE_RAG_MEMORY_THRESHOLD | 0.3 | Minimum score for personal_memory |
| NEXE_MAX_CONTEXT_CHARS | 24000 | Maximum context window in characters |
| NEXE_OLLAMA_EMBED_MODEL | nomic-embed-text | Ollama embedding model |
| NEXE_ENCRYPTION_ENABLED | auto | Enable encryption at rest for TextStore/SQLCipher |

## Limitations

- **Homonyms:** "bank" (seat) vs "bank" (finance) confuse embeddings — same word, different meanings get similar vectors
- **Negations:** "I don't like Python" ≈ "I like Python" in embedding space (high similarity)
- **Cold start:** Empty memory = RAG contributes nothing until populated
- **Top-K misses:** Relevant chunks may fall outside Top-K results
- **Contradictory info:** RAG may retrieve conflicting facts from different times
- **Ollama keep_alive:0 bug:** Does not always release VRAM on shutdown (known Ollama issue)

## Main Endpoints for RAG

- `POST /v1/chat/completions` — Chat with RAG (use_rag: true by default)
- `POST /v1/memory/store` — Save text to a collection
- `POST /v1/memory/search` — Direct semantic search in a collection
- `DELETE /v1/rag/documents/{id}` — Delete a specific entry
