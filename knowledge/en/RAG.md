# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-rag-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Complete guide to the NEXE RAG system. Covers embeddings, Qdrant, chunking, multi-collection search and limitations. Explains how to add documents, perform semantic searches and optimize context retrieval."
tags: [rag, embeddings, qdrant, chunking, vectors, semantic-search, documents]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# RAG System - NEXE 0.8

RAG (Retrieval-Augmented Generation) is the **persistent memory** system of NEXE. This document explains how it works, why it is useful and how to use it effectively.

## Table of Contents

1. [What is RAG?](#what-is-rag)
2. [Why RAG?](#why-rag)
3. [How it works in NEXE](#how-it-works-in-nexe)
4. [Embeddings](#embeddings)
5. [Qdrant and vector search](#qdrant-and-vector-search)
6. [Document chunking](#document-chunking)
7. [Retrieval strategies](#retrieval-strategies)
8. [Practical examples](#practical-examples)
9. [Limitations](#limitations)
10. [Future improvements](#future-improvements)

---

## What is RAG?

**RAG = Retrieval-Augmented Generation**

It is a technique that **augments the capabilities of an LLM** by giving it access to external information that is not part of its training.

### Problem it solves

LLMs (such as Phi-3.5, Mistral, Llama) have **limitations**:

1. **Limited knowledge:** They only know what they learned during training
2. **No memory:** Each conversation is independent (stateless)
3. **They do not know you:** They cannot remember preferences, projects, etc.
4. **Outdated:** Training data is from a past date

### Solution: RAG

```
User query: "What are my current projects?"
         ↓
   Search in memory (RAG)
         ↓
   Finds: "NEXE 0.8, JGOY Quest"
         ↓
   Adds to the LLM context
         ↓
   LLM generates response with this info
```

**Result:** The LLM can answer with information it does not really "know", but that it retrieves from memory.

---

## Why RAG?

### Advantages vs. fine-tuning

| | RAG | Fine-tuning |
|---|-----|-------------|
| **Cost** | Low (only embeddings) | High (retraining the model) |
| **Update** | Immediate (add to memory) | Slow (new training) |
| **Flexibility** | High (change data easily) | Low (fixed model) |
| **Accuracy** | Good (exact information) | Variable |
| **Transparency** | High (you see what it retrieves) | Low (black box) |

### Advantages vs. long context

Some models have a context of 100K+ tokens, but:

- **Slower:** Processing a lot of context is expensive
- **Degradation:** Performance drops with very long contexts
- **Fixed limit:** There is always a maximum
- **Inefficient:** Always passing the full context is wasteful

RAG only passes the **relevant** context to the LLM.

---

## How it works in NEXE

### General architecture

```
┌────────────────────────────────────────────────────────┐
│                      USER                              │
│  "What are my current projects?"                       │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              1. EMBEDDING GENERATION                   │
│  Query → Ollama/sentence-transformers → Vector [768]   │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              2. VECTOR SEARCH (Qdrant)                 │
│  Searches 3 collections with different thresholds      │
│  HNSW algorithm for fast approximate search            │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              3. CONTEXT BUILDING                       │
│  Combines results from the 3 collections              │
│  Sanitizes context to prevent prompt injection        │
│  Format: "[CONTEXT] <text1> <text2> ..."              │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              4. AUGMENTED PROMPT                       │
│  System: "You are an assistant..."                     │
│  Context: "<retrieved information>"                    │
│  User: "What are my current projects?"                │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              5. LLM GENERATION                         │
│  Model generates response using the context           │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│                    RESPONSE                            │
│  "Your current projects are NEXE 0.8 and              │
│   JGOY Quest according to the information I have"     │
└────────────────────────────────────────────────────────┘
```

### System components

1. **Embedding Model:** Converts text to vectors
2. **Qdrant:** Vector database for search
3. **MemoryAPI + chat.py:** Orchestrates the entire process
4. **LLM:** Generates the final response

---

## Embeddings

### What are embeddings?

An **embedding** is a **numerical representation** of a text that captures its semantic meaning.

**Conceptual example:**

```
Text: "The cat is on the roof"
  ↓
Embedding: [0.23, -0.51, 0.78, ..., 0.12]  (768 dimensions)
```

Texts with similar meaning have similar vectors:

```
"The cat is on the roof"        → [0.23, -0.51, 0.78, ...] (768 dims)
"A cat sitting on top of a roof"→ [0.25, -0.49, 0.80, ...] (768 dims)
                                      ↑ Very similar vectors!

"Python is a language"          → [-0.82, 0.31, -0.15, ...] (768 dims)
                                      ↑ Very different vector!
```

### Embedding models in NEXE

NEXE uses a hybrid embedding system with several models:

**Primary model (via Ollama):** `nomic-embed-text`
- **Dimensions:** 768
- **Advantages:** High quality, optimized for Ollama
- **Usage:** When Ollama is available (preferred)

**Configuration model:** `mxbai-embed-large`
- Defined in `server.toml` as the default model
- Dimensions compatible with the system

**Fallback model (sentence-transformers):** `paraphrase-multilingual-mpnet-base-v2`
- **Dimensions:** Configurable (DEFAULT_VECTOR_SIZE=768)
- **Multilingual:** Excellent support for multiple languages
- **Offline:** Does not require an external API
- **Usage:** When Ollama is not available

**Embedding pipeline:**
1. Attempts to use Ollama with `nomic-embed-text` (768 dims)
2. If not available, uses sentence-transformers with the configured model
3. All vectors are stored with 768 dimensions

### How they are generated

```python
# Option 1: Via Ollama (primary)
import requests

response = requests.post(
    "http://localhost:11434/api/embeddings",
    json={
        "model": "nomic-embed-text",
        "prompt": "El meu projecte és NEXE"
    }
)
embedding = response.json()["embedding"]
print(len(embedding))  # 768

# Option 2: Via sentence-transformers (fallback)
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
text = "El meu projecte és NEXE"
embedding = model.encode(text)

print(len(embedding))  # 768
print(embedding[:5])   # [0.234, -0.512, 0.789, ...]
```

### Similarity between vectors

We use **cosine similarity** to compare vectors:

```python
from numpy import dot
from numpy.linalg import norm

def cosine_similarity(v1, v2):
    return dot(v1, v2) / (norm(v1) * norm(v2))

# Example
v1 = model.encode("gat sobre teulat")
v2 = model.encode("gat al damunt teulada")
v3 = model.encode("programar en Python")

print(cosine_similarity(v1, v2))  # 0.92 (molt similar)
print(cosine_similarity(v1, v3))  # 0.15 (molt diferent)
```

**Range:** -1 (opposite) to +1 (identical)
**Thresholds in NEXE:** Vary by collection (see retrieval strategies)

---

## Qdrant and vector search

### Why Qdrant?

Qdrant is a **vector database** specialized in semantic search.

**Advantages:**
- **Fast:** HNSW algorithm (Hierarchical Navigable Small World)
- **Efficient:** Optimized for high-dimensional vectors
- **Filterable:** Allows filtering by metadata
- **Persistence:** Saves data to disk
- **Embedded mode:** No external server required

### HNSW algorithm

**HNSW = Hierarchical Navigable Small World**

It is an approximate algorithm (ANN = Approximate Nearest Neighbors) that finds the most similar vectors **very quickly**.

**How it works (simplified):**

1. Builds a **multi-layer graph** of the vectors
2. Top layer: Few connections, large jumps
3. Lower layers: More connections, smaller jumps
4. Search: Starts at the top, descends towards exact results

**Trade-off:**
- **Accuracy:** ~95-99% (not 100% exact)
- **Speed:** 100-1000x faster than exhaustive search

### Data structure in Qdrant

**Collections:** NEXE uses multiple specialized collections:

1. **`nexe_web_ui`:** Memory of conversations with the user
2. **`nexe_documentation`:** Technical documentation of the system
3. **`user_knowledge`:** User-specific knowledge

**Each point has:**

```json
{
  "id": "uuid-1234-5678",
  "vector": [0.23, -0.51, ..., 0.12],  // 768 dimensions
  "payload": {
    "text": "El meu projecte és NEXE 0.8",
    "timestamp": 1706950400,
    "metadata": {
      "source": "user_input",
      "category": "projectes",
      "tags": ["nexe", "desenvolupament"]
    }
  }
}
```

### Searching in Qdrant

**Search example:**

```python
from qdrant_client import QdrantClient

client = QdrantClient(host="localhost", port=6333)

# Query vector
query_vector = [0.25, -0.49, ..., 0.14]

# Search (example with nexe_documentation)
results = client.search(
    collection_name="nexe_documentation",
    query_vector=query_vector,
    limit=3,              # Top-3 results
    score_threshold=0.4   # Minimum similarity (varies by collection)
)

for result in results:
    print(f"Score: {result.score}")
    print(f"Text: {result.payload['text']}")
```

**Response:**

```
Score: 0.94
Text: El meu projecte és NEXE 0.8

Score: 0.87
Text: Estic desenvolupant NEXE, un servidor IA local

Score: 0.81
Text: NEXE és un projecte d'aprenentatge
```

### Persistence

Qdrant stores data in:
```
server-nexe/
└── storage/
    └── qdrant/
        ├── collection/
        │   ├── nexe_web_ui/
        │   │   ├── segments/
        │   │   └── metadata.json
        │   ├── nexe_documentation/
        │   │   ├── segments/
        │   │   └── metadata.json
        │   └── user_knowledge/
        │       ├── segments/
        │       └── metadata.json
        └── meta.json
```

**Backups:**
```bash
# Manual backup
cp -r storage/qdrant/ backup/

# Restore
rm -rf storage/qdrant/
cp -r backup/qdrant/ storage/
```

---

## Document chunking

When indexing long documents, they must be divided into **chunks** (pieces).

### Why chunking?

1. **Model limits:** Embeddings work better with short-to-medium texts
2. **Granularity:** Retrieve only the relevant part, not the entire document
3. **Performance:** Smaller chunks = faster search

### Chunking strategies in NEXE

#### 1. Fixed chunking (default)

NEXE uses chunking based on **characters**, not words:

```python
def chunk_text(text, max_chunk_size=1500, chunk_overlap=200):
    """Split text into fixed-size chunks with overlap (in characters)"""
    chunks = []

    for i in range(0, len(text), max_chunk_size - chunk_overlap):
        chunk = text[i:i + max_chunk_size]
        chunks.append(chunk)

    return chunks
```

**Parameters for general text:**
- `max_chunk_size`: 1500 characters
- `chunk_overlap`: 200 characters
- `min_chunk_size`: 100 characters

**Parameters for RAG endpoint:**
- `max_chunk_size`: 800 characters
- `chunk_overlap`: 100 characters

**Example:**

```
Document: "This is a very long document about Python..."

Chunk 1: "This is a very long document about Python..." (1500 chars)
Chunk 2: "...about Python and how to program with FastAPI..." (1500 chars)
Chunk 3: "...with FastAPI to create modern REST APIs..." (remainder)
         ↑ 200 chars overlap ↑
```

**Important:** Chunking is by CHARACTERS, not words, to have more precise control over vector size.

#### 2. Paragraph chunking (alternative)

```python
def chunk_by_paragraphs(text, max_size=1500):
    """Split by paragraphs (respects structure)"""
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) > max_size:
            chunks.append(current)
            current = para
        else:
            current += "\n\n" + para

    if current:
        chunks.append(current)

    return chunks
```

**Advantage:** Respects the document structure
**Disadvantage:** Chunks of more variable size than fixed chunking

#### 3. Semantic chunking (future)

Split by **topics/sections** using NLP:

```python
# Future: Use a model to detect semantic boundaries
def semantic_chunking(text):
    # Detect topic changes
    # Split at semantically coherent points
    pass
```

### Metadata per chunk

Each chunk stores metadata useful for retrieval:

```json
{
  "text": "...text chunk...",
  "timestamp": 1706950400,
  "metadata": {
    "document_id": "doc-123",
    "document_name": "ARCHITECTURE.md",
    "chunk_index": 2,
    "total_chunks": 15,
    "section": "Main components",
    "source": "documentation"
  }
}
```

**Usefulness:**
- Filter by source document or collection
- Reconstruct the original order of chunks
- Show context and sources to the user
- Prioritize information by timestamp (most recent)

---

## Retrieval strategies

### 1. Multi-Collection Top-K

NEXE searches multiple collections with different thresholds:

```python
# Search in nexe_documentation
docs_results = client.search(
    collection_name="nexe_documentation",
    query_vector=query_vector,
    limit=3,
    score_threshold=0.4  # Higher threshold for technical docs
)

# Search in user_knowledge
knowledge_results = client.search(
    collection_name="user_knowledge",
    query_vector=query_vector,
    limit=3,
    score_threshold=0.35  # Medium threshold
)

# Search in nexe_web_ui
memory_results = client.search(
    collection_name="nexe_web_ui",
    query_vector=query_vector,
    limit=2,
    score_threshold=0.3  # Lower threshold for conversations
)
```

**Thresholds per collection:**
- `nexe_documentation`: 0.4 (precise technical information)
- `user_knowledge`: 0.35 (user knowledge)
- `nexe_web_ui`: 0.3 (conversational context)

### 2. MMR (Maximal Marginal Relevance)

Avoids returning results that are too similar to each other:

```
Top-5 candidates:
1. Score: 0.95 - "NEXE és un projecte..."
2. Score: 0.94 - "NEXE és un projecte d'IA..."  ← Very similar to #1
3. Score: 0.88 - "JGOY Quest és un sistema..."   ← Different!
4. Score: 0.85 - "El projecte NEXE..."          ← Similar to #1/#2
5. Score: 0.82 - "Desenvolupament amb Python..."← Different!

MMR selects: #1, #3, #5 (diversity)
```

**Implementation (future):**

```python
def mmr_retrieval(candidates, lambda_param=0.5):
    selected = []
    while len(selected) < 3:
        best = None
        best_score = -1

        for candidate in candidates:
            # Score = Relevance - λ * Similarity with selected
            relevance = candidate.score
            similarity_to_selected = max_similarity(candidate, selected)
            score = relevance - lambda_param * similarity_to_selected

            if score > best_score:
                best = candidate
                best_score = score

        selected.append(best)
        candidates.remove(best)

    return selected
```

### 3. Metadata filtering

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue

results = client.search(
    collection_name="nexe_documentation",
    query_vector=query_vector,
    limit=5,
    query_filter=Filter(
        must=[
            FieldCondition(
                key="metadata.category",
                match=MatchValue(value="docs")
            )
        ]
    )
)
```

**Search:** Only in documents with a specific category

### 4. Re-ranking (future)

Use the LLM to reorder results:

```
1. Vector search → Top-20 candidates
2. LLM evaluates each candidate: "Is it relevant for the query?"
3. Reorders according to LLM evaluation
4. Returns final Top-5
```

**Advantage:** More accurate
**Disadvantage:** Slower and more expensive

---

## Practical examples

### Example 1: Personal assistant via API

```bash
# 1. Save personal information to user_knowledge
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "El meu nom és Jordi i sóc de Barcelona",
    "collection": "user_knowledge"
  }'

curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Els meus projectes són NEXE i JGOY Quest",
    "collection": "user_knowledge"
  }'

# 2. Ask with RAG enabled
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Where do I live?"}],
    "use_rag": true
  }'
```

**Response:**
```json
{
  "choices": [{
    "message": {
      "content": "According to the information I have, you live in Barcelona."
    }
  }]
}
```

**Under the hood:**

1. Query: "Where do I live?" → Embedding (768 dims)
2. Qdrant search → Finds: "...sóc de Barcelona" (score: 0.89)
3. Context: "El meu nom és Jordi i sóc de Barcelona"
4. Prompt to LLM: "Context: <info>. Question: Where do I live?"
5. LLM: "You live in Barcelona"

### Example 2: Query knowledge base

```bash
# Query documentation via API (RAG enabled by default)
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": "How does the plugin system work?"
    }],
    "use_rag": true
  }'
```

**Response:**
```json
{
  "choices": [{
    "message": {
      "content": "The NEXE plugin system is based on a BasePlugin interface that all plugins implement. Plugins are registered in the PluginRegistry and loaded dynamically during server startup..."
    }
  }],
  "rag_context": {
    "sources": ["ARCHITECTURE.md", "PLUGINS.md"],
    "chunks_used": 3
  }
}
```

**Note:** Documentation is automatically indexed into `nexe_documentation` during system installation/startup.

### Example 3: Semantic similarity search

```bash
# Search directly in memory
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "embeddings i cerca semàntica",
    "collection": "user_knowledge",
    "limit": 5
  }'
```

**Response:**
```json
{
  "results": [
    {
      "text": "Avui he après sobre sistemes de vectors",
      "score": 0.84,
      "metadata": {...}
    },
    {
      "text": "Les bases de dades vectorials són potents",
      "score": 0.79,
      "metadata": {...}
    }
  ]
}
```

**Magic:** Searches by **semantic meaning**, not exact words! Different words expressing the same concept get high scores.

---

## Limitations

### 1. Embedding quality

**Problem:** The embedding model is not perfect

**Example:**
```
Query: "What is the weather like?"
Search: "processing time", "verb tense"
  ↑ Same word with different meanings
```

**Mitigation:**
- Use better models (larger, more specific)
- Add context to queries
- Filter results with low scores

### 2. Context limit

**Problem:** Only Top-K results are retrieved

If you have a lot of information, the relevant one may not be in the Top-5.

**Mitigation:**
- Increase K (but slower)
- Improve chunking (smaller, more precise chunks)
- Use metadata for pre-filtering

### 3. Contradictory information

**Problem:** If you store contradictory information:

```
Memory:
- "My favorite color is blue"
- "I like the color red"
```

The LLM may get confused.

**Mitigation:**
- Keep memory updated
- Delete old/incorrect information
- Timestamps to prioritize recent information

### 4. Embedding privacy

**Problem:** Embeddings contain semantic information

If someone gains access to the Qdrant database, they can extract information (even if it is not trivial).

**Mitigation:**
- Do not expose Qdrant publicly
- Encrypt disk (FileVault, LUKS)
- Delete sensitive data when no longer needed

### 5. Storage consumption

**Problem:** Each chunk generates:
- Vector (768 floats × 4 bytes = 3 KB)
- Payload (text + metadata = variable)

Many documents = a lot of storage.

**Example:**
```
10,000 chunks × 4 KB/chunk = 40 MB (acceptable)
1,000,000 chunks × 4 KB/chunk = 4 GB (a lot!)
```

**Mitigation:**
- More aggressive chunking (larger chunks)
- Compress payloads
- Delete old documents

### 6. Cold start

**Problem:** Without memory, RAG contributes nothing

During the first run, NEXE:
- Automatically loads system documentation into `nexe_documentation`
- The `user_knowledge` and `nexe_web_ui` collections start empty
- They fill up progressively with system usage

Conversations with the user are automatically stored in `nexe_web_ui` when RAG is enabled.

---

## Future improvements

### 1. Better embeddings

**Future options:**
- `multilingual-e5-large`: Better quality, multilingual (1024 dims)
- `bge-m3`: SOTA multilingual, more dimensions
- Domain-specific models
- Fine-tuning of existing models for specific use cases

**Note:** NEXE already uses a hybrid system with `nomic-embed-text` (768 dims) via Ollama, which offers very good quality.

### 2. Semantic chunking

Use NLP to split by topic, not by fixed size.

### 3. Hybrid search

Combine vector search + keyword search:

```
Results = α × VectorScore + (1-α) × BM25Score
```

**Advantage:** Better accuracy

### 4. Re-ranking with LLM

Use the LLM to evaluate results and reorder them.

### 5. Graph RAG

Build a **knowledge graph** over the vectors:

```
Entity: "NEXE" → related to → "FastAPI", "Qdrant", "Python"
```

**Advantage:** Retrieve richer and more contextualized information

### 6. Auto-update

Detect when a document changes and reindex it automatically.

### 7. Multi-modal

Support images, audio, video (not just text):

```
Query: "Image of a cat"
Results: <similar images>
```

**Requires:** Multi-modal models (CLIP, etc.)

---

## Resources

### Recommended papers

- **Original RAG:** "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (Lewis et al., 2020)
- **HNSW:** "Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs" (Malkov & Yashunin, 2018)
- **Sentence-BERT:** "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks" (Reimers & Gurevych, 2019)

### Related tools

- **LangChain:** Python framework for RAG
- **LlamaIndex:** Specialized in indexing documents
- **Haystack:** Framework for search and QA
- **Weaviate, Pinecone, Milvus:** Other vector databases

### Tutorials

- Qdrant documentation: https://qdrant.tech/documentation/
- Sentence-Transformers: https://www.sbert.net/
- RAG with LangChain: https://python.langchain.com/docs/use_cases/question_answering/

---

## Technical summary

### Key components
- **Embeddings:** Ollama nomic-embed-text (768 dims) + fallbacks
- **Database:** Qdrant with HNSW algorithm
- **Collections:** nexe_web_ui, nexe_documentation, user_knowledge
- **Chunking:** 1500/200 chars (text), 800/100 chars (RAG endpoint)
- **Thresholds:** 0.4 (docs), 0.35 (knowledge), 0.3 (memory)

### Main endpoints
- `POST /v1/chat/completions` - Chat with RAG (use_rag: true)
- `POST /v1/memory/store` - Save to memory
- `POST /v1/memory/search` - Direct search

### Configuration
- `server.toml`: Default embedding model
- `storage/qdrant/`: Vector persistence
- Authentication: X-API-Key header

---

## Next steps

To continue learning about NEXE:

1. **API.md** - Complete REST API reference
2. **SECURITY.md** - Security and authentication system
3. **ARCHITECTURE.md** - General system architecture

---

**Note:** RAG is a rapidly evolving area. This implementation is functional and in production. There is room for improvement with techniques such as Graph RAG, hybrid search and re-ranking.

**Experiment:** The threshold and chunking parameters are configurable. Adjust them according to your specific use case.
