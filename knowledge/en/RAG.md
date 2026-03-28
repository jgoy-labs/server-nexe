# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-rag-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Complete reference of the server-nexe RAG memory system (v0.8.5 pre-release). Covers 3 Qdrant collections with thresholds, MEM_SAVE automatic memory, delete intent, session-isolated document upload, embeddings (768D), chunking parameters, context building with i18n labels, RAG weight visualization, RAG context sanitization, smart pruning, deduplication, TextStore for encrypted text, and Qdrant payloads without text."
tags: [rag, embeddings, qdrant, memory, mem_save, collections, thresholds, chunking, vectors, semantic-search, documents, session-isolation, delete-intent, pruning, deduplication, sanitization, text-store, encryption]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# RAG System — server-nexe 0.8.5 pre-release

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
| `nexe_web_ui` | Conversation memory (MEM_SAVE) | 0.3 | 2 | Automatic extraction from chat. Max 500 entries with smart pruning |

**Search order:** nexe_documentation first (system priority), then user_knowledge, then nexe_web_ui.

**Thresholds are configurable** via environment variables:
- `NEXE_RAG_DOCS_THRESHOLD` (default: 0.4)
- `NEXE_RAG_KNOWLEDGE_THRESHOLD` (default: 0.35)
- `NEXE_RAG_MEMORY_THRESHOLD` (default: 0.3)

The Web UI also allows real-time threshold adjustment via a slider (default 0.30, range configurable).

## Qdrant Payloads (no text)

As of v0.8.5, Qdrant payloads **no longer contain text content**. Each payload only stores:
- `entry_type` — the type of entry
- `original_id` — link back to SQLite for the full text

All text lives in SQLite (optionally encrypted via SQLCipher). This means even without encryption enabled, Qdrant vectors alone cannot reconstruct the original text content.

## TextStore (new in v0.8.5)

`TextStore` (`memory/memory/api/text_store.py`) is a SQLite-backed storage for RAG document text, decoupled from Qdrant:

- Stores document text with `document_id` for linkback
- Optionally encrypted via SQLCipher when `crypto_provider` is available
- Used by `store_document()`, `search_documents()`, `get_document()`, `delete_document()`
- Backwards compatible: if `text_store` is not provided, legacy behavior (text in Qdrant payload) is used

## Embeddings

**Primary model (via Ollama):** `nomic-embed-text` — 768 dimensions. Used when Ollama is available.

**Fallback model (offline):** `paraphrase-multilingual-mpnet-base-v2` via sentence-transformers — 768 dimensions. Multilingual. Used when Ollama is not available.

All vectors are stored with 768 dimensions. This value is centralized in `memory/memory/constants.py` as `DEFAULT_VECTOR_SIZE = 768`.

**Similarity metric:** Cosine similarity. Range: -1 (opposite) to +1 (identical).

## MEM_SAVE — Automatic Memory

server-nexe has an automatic memory system similar to ChatGPT or Claude. The model extracts facts from conversations and saves them to memory within the same LLM call (zero extra latency).

**How it works:**
1. The system prompt instructs the model to extract facts: names, jobs, locations, preferences, projects, deadlines
2. The model outputs `[MEM_SAVE: fact]` markers within its response
3. routes_chat.py parses these markers and removes them from the visible stream
4. Facts are saved to `nexe_web_ui` collection
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

**Delete intent:** When user says "forget that X", searches for entries with similarity >= 0.6 and deletes the closest match.

## RAG Context Sanitization

`_sanitize_rag_context()` filters retrieved RAG content before injecting it into the LLM prompt. This prevents stored documents or memory entries from containing injection patterns that could manipulate the model's behavior.

Applied in the Web UI pipeline (`routes_chat.py`) consistently with the API pipeline.

## Document Upload with Session Isolation

Documents uploaded via the Web UI are indexed into `user_knowledge` collection with `session_id` in the metadata. This means:

- Documents are only visible within the session where they were uploaded
- No cross-session contamination of document context
- Documents persist within the session (not cleared on page refresh)
- Metadata is generated without LLM (instant, no model required)

**Supported formats:** .txt, .md, .pdf
**Chunking for uploads:** 1500 characters per chunk, 200 characters overlap.

## Document Ingestion

### System documentation (nexe_documentation)
- Source: `docs/` folder + `README.md`
- Chunking: 500 characters per chunk, 50 characters overlap
- Ingested via `core/ingest/ingest_docs.py`
- Recreates the collection on each ingestion (fresh start)

### User knowledge (user_knowledge via CLI)
- Source: `knowledge/` folder (ca/en/es subfolders)
- Chunking: 1500 characters per chunk, 200 characters overlap
- Ingested via `core/ingest/ingest_knowledge.py`
- Supports RAG headers with metadata (`#!RAG id=..., priority=...`)

## Context Building

When RAG finds relevant results, they are injected into the LLM prompt in 3 labeled categories:

| Category | Label (EN) | Label (CA) | Label (ES) | Source collection |
|----------|-----------|-----------|-----------|-------------------|
| System docs | SYSTEM DOCUMENTATION | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | nexe_documentation |
| Technical docs | TECHNICAL DOCUMENTATION | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | user_knowledge |
| User memory | USER MEMORY | MEMORIA USUARI | MEMORIA USUARIO | nexe_web_ui |

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

## Smart Pruning (nexe_web_ui collection)

When `nexe_web_ui` exceeds `MAX_MEMORY_ENTRIES` (500), smart pruning removes the lowest-scored entries:

**Retention score formula:**
- type_weight (0.4): weight based on memory type
- access_score (0.3): how recently accessed
- recency_score (0.3): how recently created
- Temporal decay bonus: +15% for entries within 7 days (`TEMPORAL_DECAY_DAYS = 7`)

## Qdrant Storage

Qdrant runs as an embedded binary (no external server). Data stored at:
```
storage/qdrant/
├── collection/
│   ├── nexe_documentation/
│   ├── nexe_web_ui/
│   └── user_knowledge/
└── meta.json
```

**Qdrant port:** 6333 (configurable via `NEXE_QDRANT_HOST` and `NEXE_QDRANT_PORT`)
**Algorithm:** HNSW (Hierarchical Navigable Small World) for fast approximate nearest neighbor search

## Key Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| NEXE_RAG_DOCS_THRESHOLD | 0.4 | Minimum score for nexe_documentation |
| NEXE_RAG_KNOWLEDGE_THRESHOLD | 0.35 | Minimum score for user_knowledge |
| NEXE_RAG_MEMORY_THRESHOLD | 0.3 | Minimum score for nexe_web_ui |
| NEXE_MAX_CONTEXT_CHARS | 24000 | Maximum context window in characters |
| NEXE_QDRANT_HOST | localhost | Qdrant host |
| NEXE_QDRANT_PORT | 6333 | Qdrant port |
| NEXE_QDRANT_TIMEOUT | 5.0 | Qdrant connection timeout |
| NEXE_OLLAMA_EMBED_MODEL | nomic-embed-text | Ollama embedding model |
| NEXE_ENCRYPTION_ENABLED | false | Enable encryption at rest for TextStore/SQLCipher |

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
- `DELETE /v1/memory/{id}` — Delete a specific entry
