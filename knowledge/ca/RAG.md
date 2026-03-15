# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-rag-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia completa del sistema RAG de NEXE. Cobreix embeddings, Qdrant, chunking, cerca multi-col·lecció i limitacions. Explica com afegir documents, fer cerques semàntiques i optimitzar la recuperació de context."
tags: [rag, embeddings, qdrant, chunking, vectors, cerca-semàntica, documents]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema RAG - NEXE 0.8

RAG (Retrieval-Augmented Generation) és el sistema de **memòria persistent** de NEXE. Aquest document explica com funciona, per què és útil i com usar-lo efectivament.

## Índex

1. [Què és RAG?](#què-és-rag)
2. [Per què RAG?](#per-què-rag)
3. [Com funciona a NEXE](#com-funciona-a-nexe)
4. [Embeddings](#embeddings)
5. [Qdrant i cerca vectorial](#qdrant-i-cerca-vectorial)
6. [Chunking de documents](#chunking-de-documents)
7. [Estratègies de retrieval](#estratègies-de-retrieval)
8. [Exemples pràctics](#exemples-pràctics)
9. [Limitacions](#limitacions)
10. [Millores futures](#millores-futures)

---

## Què és RAG?

**RAG = Retrieval-Augmented Generation**

És una tècnica que **augmenta les capacitats d'una LLM** donant-li accés a informació externa que no té en el seu training.

### Problema que resol

Les LLMs (com Phi-3.5, Mistral, Llama) tenen **limitacions**:

1. **Coneixement limitat:** Només saben el que van aprendre durant l'entrenament
2. **No recorden:** Cada conversa és independent (sense estat)
3. **No saben de tu:** No poden recordar preferències, projectes, etc.
4. **Desfasades:** El training és d'una data passada

### Solució: RAG

```
Pregunta usuari: "Quins són els meus projectes actuals?"
         ↓
   Cerca a memòria (RAG)
         ↓
   Troba: "NEXE 0.8, JGOY Quest"
         ↓
   Afegeix al context de la LLM
         ↓
   LLM genera resposta amb aquesta info
```

**Resultat:** La LLM pot respondre amb informació que realment no "sap", però que recupera de la memòria.

---

## Per què RAG?

### Avantatges vs. fine-tuning

| | RAG | Fine-tuning |
|---|-----|-------------|
| **Cost** | Baix (només embeddings) | Alt (reentrenar model) |
| **Actualització** | Immediata (afegir a memòria) | Lenta (nou training) |
| **Flexibilitat** | Alta (canviar dades fàcilment) | Baixa (model fix) |
| **Precisió** | Bona (informació exacta) | Variable |
| **Transparència** | Alta (veus què recupera) | Baixa (caixa negra) |

### Avantatges vs. context llarg

Alguns models tenen context de 100K+ tokens, però:

- **Més lent:** Processar molt context és costós
- **Degradació:** Performance baixa amb contexts molt llargs
- **Límit fix:** Sempre hi ha un màxim
- **Ineficient:** Passar sempre tot el context és un malbaratament

RAG només passa el context **rellevant** a la LLM.

---

## Com funciona a NEXE

### Arquitectura general

```
┌────────────────────────────────────────────────────────┐
│                     USUARI                             │
│  "Quins són els meus projectes actuals?"               │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              1. GENERACIÓ EMBEDDING                    │
│  Query → Ollama/sentence-transformers → Vector [768]   │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              2. CERCA VECTORIAL (Qdrant)               │
│  Cerca a 3 col·leccions amb thresholds diferents       │
│  HNSW algorithm per cerca aproximada ràpida            │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              3. CONSTRUCCIÓ DE CONTEXT                 │
│  Combina resultats de les 3 col·leccions               │
│  Sanititza context per prevenir prompt injection       │
│  Format: "[CONTEXT] <text1> <text2> ..."              │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              4. PROMPT AUGMENTAT                       │
│  System: "Ets un assistent..."                         │
│  Context: "<informació recuperada>"                    │
│  User: "Quins són els meus projectes actuals?"        │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              5. GENERACIÓ LLM                          │
│  Model genera resposta usant el context               │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│                    RESPOSTA                            │
│  "Els teus projectes actuals són NEXE 0.8 i           │
│   JGOY Quest segons la informació que tinc"           │
└────────────────────────────────────────────────────────┘
```

### Components del sistema

1. **Embedding Model:** Converteix text a vectors
2. **Qdrant:** Base de dades vectorial per cerca
3. **MemoryAPI + chat.py:** Orquestra tot el procés
4. **LLM:** Genera la resposta final

---

## Embeddings

### Què són els embeddings?

Un **embedding** és una **representació numèrica** d'un text que captura el seu significat semàntic.

**Exemple conceptual:**

```
Text: "El gat està sobre el teulat"
  ↓
Embedding: [0.23, -0.51, 0.78, ..., 0.12]  (768 dimensions)
```

Textos amb significat similar tenen vectors similars:

```
"El gat està sobre el teulat"    → [0.23, -0.51, 0.78, ...] (768 dims)
"Un gat al damunt d'una teulada" → [0.25, -0.49, 0.80, ...] (768 dims)
                                      ↑ Vectors molt similars!

"Python és un llenguatge"         → [-0.82, 0.31, -0.15, ...] (768 dims)
                                      ↑ Vector molt diferent!
```

### Models d'embeddings a NEXE

NEXE utilitza un sistema híbrid d'embeddings amb diversos models:

**Model prioritari (via Ollama):** `nomic-embed-text`
- **Dimensions:** 768
- **Avantatges:** Alta qualitat, optimitzat per Ollama
- **Ús:** Quan Ollama està disponible (preferit)

**Model de configuració:** `mxbai-embed-large`
- Definit a `server.toml` com a model per defecte
- Dimensions compatibles amb sistema

**Model fallback (sentence-transformers):** `paraphrase-multilingual-mpnet-base-v2`
- **Dimensions:** Configurable (DEFAULT_VECTOR_SIZE=768)
- **Multilingüe:** Excel·lent suport per català
- **Offline:** No requereix API externa
- **Ús:** Quan Ollama no està disponible

**Pipeline d'embeddings:**
1. Intenta usar Ollama amb `nomic-embed-text` (768 dims)
2. Si no està disponible, usa sentence-transformers amb el model configurat
3. Tots els vectors s'emmagatzemen amb 768 dimensions

### Com es generen

```python
# Opció 1: Via Ollama (prioritari)
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

# Opció 2: Via sentence-transformers (fallback)
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
text = "El meu projecte és NEXE"
embedding = model.encode(text)

print(len(embedding))  # 768
print(embedding[:5])   # [0.234, -0.512, 0.789, ...]
```

### Similaritat entre vectors

Usem **cosine similarity** per comparar vectors:

```python
from numpy import dot
from numpy.linalg import norm

def cosine_similarity(v1, v2):
    return dot(v1, v2) / (norm(v1) * norm(v2))

# Exemple
v1 = model.encode("gat sobre teulat")
v2 = model.encode("gat al damunt teulada")
v3 = model.encode("programar en Python")

print(cosine_similarity(v1, v2))  # 0.92 (molt similar)
print(cosine_similarity(v1, v3))  # 0.15 (molt diferent)
```

**Rang:** -1 (oposats) a +1 (idèntics)
**Thresholds a NEXE:** Varien segons col·lecció (veure estratègies de retrieval)

---

## Qdrant i cerca vectorial

### Per què Qdrant?

Qdrant és una **base de dades vectorial** especialitzada en cerca semàntica.

**Avantatges:**
- **Ràpid:** Algorisme HNSW (Hierarchical Navigable Small World)
- **Efficient:** Optimitzat per vectors high-dimensional
- **Filtrable:** Permet filtrar per metadata
- **Persistència:** Guarda dades a disc
- **Embedded mode:** No cal servidor extern

### Algorisme HNSW

**HNSW = Hierarchical Navigable Small World**

És un algorisme aproximat (ANN = Approximate Nearest Neighbors) que troba els vectors més similars **molt ràpidament**.

**Com funciona (simplificat):**

1. Construeix un **graf multi-capa** dels vectors
2. Capa superior: Poques connexions, salts grans
3. Capes inferiors: Més connexions, salts petits
4. Cerca: Comença a dalt, baixa cap a resultats exactes

**Trade-off:**
- **Exactitud:** ~95-99% (no 100% exacte)
- **Velocitat:** 100-1000x més ràpid que cerca exhaustiva

### Estructura de dades a Qdrant

**Col·leccions:** NEXE utilitza múltiples col·leccions especialitzades:

1. **`nexe_web_ui`:** Memòria personal de l'usuari (auto-save de missatges de xat)
2. **`nexe_documentation`:** Documentació tècnica del sistema
3. **`user_knowledge`:** Documents i coneixement indexat manualment

**Cada punt té:**

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

### Cerca a Qdrant

**Exemple de cerca:**

```python
from qdrant_client import QdrantClient

client = QdrantClient(host="localhost", port=6333)

# Vector de la query
query_vector = [0.25, -0.49, ..., 0.14]

# Cerca (exemple amb nexe_documentation)
results = client.search(
    collection_name="nexe_documentation",
    query_vector=query_vector,
    limit=3,              # Top-3 resultats
    score_threshold=0.4   # Mínim similaritat (varia segons col·lecció)
)

for result in results:
    print(f"Score: {result.score}")
    print(f"Text: {result.payload['text']}")
```

**Resposta:**

```
Score: 0.94
Text: El meu projecte és NEXE 0.8

Score: 0.87
Text: Estic desenvolupant NEXE, un servidor IA local

Score: 0.81
Text: NEXE és un projecte d'aprenentatge
```

### Persistència

Qdrant guarda les dades a:
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
# Backup manual
cp -r storage/qdrant/ backup/

# Restore
rm -rf storage/qdrant/
cp -r backup/qdrant/ storage/
```

---

## Chunking de documents

Quan indexes documents llargs, cal dividir-los en **chunks** (trossos).

### Per què chunking?

1. **Límits del model:** Els embeddings funcionen millor amb texts curts-mitjans
2. **Granularitat:** Recuperar només la part rellevant, no tot el document
3. **Performance:** Chunks petits = cerca més ràpida

### Estratègies de chunking a NEXE

#### 1. Chunking fix (per defecte)

NEXE utilitza chunking basat en **caràcters**, no paraules:

```python
def chunk_text(text, max_chunk_size=1500, chunk_overlap=200):
    """Dividir text en chunks de mida fixa amb overlap (en caràcters)"""
    chunks = []

    for i in range(0, len(text), max_chunk_size - chunk_overlap):
        chunk = text[i:i + max_chunk_size]
        chunks.append(chunk)

    return chunks
```

**Paràmetres per text general:**
- `max_chunk_size`: 1500 caràcters
- `chunk_overlap`: 200 caràcters
- `min_chunk_size`: 100 caràcters

**Paràmetres per RAG endpoint:**
- `max_chunk_size`: 800 caràcters
- `chunk_overlap`: 100 caràcters

**Exemple:**

```
Document: "Aquest és un document molt llarg sobre Python..."

Chunk 1: "Aquest és un document molt llarg sobre Python..." (1500 chars)
Chunk 2: "...bre Python i com programar amb FastAPI..." (1500 chars)
Chunk 3: "...amb FastAPI per crear APIs REST modernes..." (resta)
         ↑ 200 chars overlap ↑
```

**Important:** El chunking és per CARÀCTERS, no paraules, per tenir control més precís sobre la mida dels vectors.

#### 2. Chunking per paràgrafs (alternatiu)

```python
def chunk_by_paragraphs(text, max_size=1500):
    """Dividir per paràgrafs (respecta estructura)"""
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

**Avantatge:** Respecta l'estructura del document
**Desavantatge:** Chunks de mida més variable que chunking fix

#### 3. Chunking semàntic (futur)

Dividir per **temes/seccions** usant NLP:

```python
# Futur: Usar un model per detectar límits semàntics
def semantic_chunking(text):
    # Detectar canvis de tema
    # Dividir en llocs semànticament coherents
    pass
```

### Metadata per chunk

Cada chunk guarda metadata útil per al retrieval:

```json
{
  "text": "...chunk de text...",
  "timestamp": 1706950400,
  "metadata": {
    "document_id": "doc-123",
    "document_name": "ARCHITECTURE.md",
    "chunk_index": 2,
    "total_chunks": 15,
    "section": "Components principals",
    "source": "documentation"
  }
}
```

**Utilitat:**
- Filtrar per document origen o col·lecció
- Reconstruir ordre original dels chunks
- Mostrar context i fonts a l'usuari
- Prioritzar informació per timestamp (més recent)

---

## Estratègies de retrieval

### 1. Multi-Collection Top-K

NEXE cerca en múltiples col·leccions amb thresholds diferents:

```python
# Cerca a nexe_documentation
docs_results = client.search(
    collection_name="nexe_documentation",
    query_vector=query_vector,
    limit=3,
    score_threshold=0.4  # Threshold més alt per docs tècnics
)

# Cerca a user_knowledge
knowledge_results = client.search(
    collection_name="user_knowledge",
    query_vector=query_vector,
    limit=3,
    score_threshold=0.35  # Threshold mitjà
)

# Cerca a nexe_web_ui
memory_results = client.search(
    collection_name="nexe_web_ui",
    query_vector=query_vector,
    limit=2,
    score_threshold=0.3  # Threshold més baix per converses
)
```

**Thresholds per col·lecció:**
- `nexe_documentation`: 0.4 (informació tècnica precisa)
- `user_knowledge`: 0.35 (coneixement de l'usuari)
- `nexe_web_ui`: 0.3 (missatges personals de l'usuari)

### 2. MMR (Maximal Marginal Relevance)

Evita retornar resultats massa similars entre ells:

```
Top-5 candidats:
1. Score: 0.95 - "NEXE és un projecte..."
2. Score: 0.94 - "NEXE és un projecte d'IA..."  ← Molt similar a #1
3. Score: 0.88 - "JGOY Quest és un sistema..."   ← Diferent!
4. Score: 0.85 - "El projecte NEXE..."          ← Similar a #1/#2
5. Score: 0.82 - "Desenvolupament amb Python..."← Diferent!

MMR selecciona: #1, #3, #5 (diversitat)
```

**Implementació (futur):**

```python
def mmr_retrieval(candidates, lambda_param=0.5):
    selected = []
    while len(selected) < 3:
        best = None
        best_score = -1

        for candidate in candidates:
            # Score = Relevància - λ * Similaritat amb seleccionats
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

### 3. Filtratge per metadata

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

**Cerca:** Només en documents amb categoria específica

### 4. Re-ranking (futur)

Usar la LLM per re-ordenar resultats:

```
1. Cerca vectorial → Top-20 candidats
2. LLM avalua cada candidat: "És rellevant per la query?"
3. Re-ordena segons avaluació LLM
4. Retorna Top-5 finals
```

**Avantatge:** Més precís
**Desavantatge:** Més lent i costós

---

## Exemples pràctics

### Exemple 1: Assistent personal via API

```bash
# 1. Guardar informació personal a user_knowledge
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

# 2. Preguntar amb RAG activat
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "On visc?"}],
    "use_rag": true
  }'
```

**Resposta:**
```json
{
  "choices": [{
    "message": {
      "content": "Segons la informació que tinc, vius a Barcelona."
    }
  }]
}
```

**Sota el capó:**

1. Query: "On visc?" → Embedding (768 dims)
2. Cerca Qdrant → Troba: "...sóc de Barcelona" (score: 0.89)
3. Context: "El meu nom és Jordi i sóc de Barcelona"
4. Prompt a LLM: "Context: <info>. Pregunta: On visc?"
5. LLM: "Vius a Barcelona"

### Exemple 2: Consultar base de coneixement

```bash
# Consultar documentació via API (RAG activat per defecte)
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": "Com funciona el sistema de plugins?"
    }],
    "use_rag": true
  }'
```

**Resposta:**
```json
{
  "choices": [{
    "message": {
      "content": "El sistema de plugins de NEXE està basat en una interface BasePlugin que tots els plugins implementen. Els plugins es registren al PluginRegistry i es carreguen dinàmicament durant l'inici del servidor..."
    }
  }],
  "rag_context": {
    "sources": ["ARCHITECTURE.md", "PLUGINS.md"],
    "chunks_used": 3
  }
}
```

**Nota:** La documentació s'indexa automàticament a `nexe_documentation` durant la instal·lació/inici del sistema.

### Exemple 3: Cerca per similaritat semàntica

```bash
# Cercar directament a la memòria
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "embeddings i cerca semàntica",
    "collection": "user_knowledge",
    "limit": 5
  }'
```

**Resposta:**
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

**Màgia:** Cerca per **significat semàntic**, no paraules exactes! Paraules diferents amb el mateix concepte obtenen scores alts.

---

## Limitacions

### 1. Qualitat dels embeddings

**Problema:** El model d'embeddings no és perfecte

**Exemple:**
```
Query: "Com està el temps?"
Cerca: "temps de processament", "temps verbal"
  ↑ Paraula "temps" amb significats diferents
```

**Mitigació:**
- Usar models millors (més grans, més específics)
- Afegir context a les queries
- Filtrar resultats amb score baix

### 2. Límit de context

**Problema:** Només es recuperen Top-K resultats

Si tens molta informació, potser la rellevant no està al Top-5.

**Mitigació:**
- Augmentar K (però més lent)
- Millorar chunking (chunks més petits i precisos)
- Usar metadata per pre-filtrar

### 3. Informació contradictòria

**Problema:** Si guardes informació contradictòria:

```
Memòria:
- "El meu color favorit és blau"
- "M'agrada el color vermell"
```

La LLM pot confondre's.

**Mitigació:**
- Mantenir memòria actualitzada
- Esborrar informació antiga/incorrecta
- Timestamps per prioritzar informació recent

### 4. Privacitat dels embeddings

**Problema:** Els embeddings contenen informació semàntica

Si algú accedeix a la base de dades Qdrant, pot extreure informació (encara que no sigui trivial).

**Mitigació:**
- No exposar Qdrant públicament
- Encriptar disc (FileVault, LUKS)
- Esborrar dades sensibles quan no es necessitin

### 5. Consum d'espai

**Problema:** Cada chunk genera:
- Vector (768 floats × 4 bytes = 3 KB)
- Payload (text + metadata = variable)

Molts documents = molt espai.

**Exemple:**
```
10.000 chunks × 4 KB/chunk = 40 MB (acceptable)
1.000.000 chunks × 4 KB/chunk = 4 GB (molt!)
```

**Mitigació:**
- Chunking més agressiu (chunks més grans)
- Comprimir payloads
- Esborrar documents antics

### 6. Cold start

**Problema:** Sense memòria, RAG no aporta res

Durant la primera execució, NEXE:
- Carrega automàticament la documentació del sistema a `nexe_documentation`
- Les col·leccions `user_knowledge` i `nexe_web_ui` comencen buides
- Es van omplint progressivament amb l'ús del sistema

Cada missatge de l'usuari (≥8 caràcters, no salutació) s'emmagatzema automàticament a `nexe_web_ui` sense passar per cap LLM. La cerca semàntica recupera el context rellevant abans de cada resposta.

---

## Millores futures

### 1. Embeddings millors

**Opcions futures:**
- `multilingual-e5-large`: Millor qualitat, multilingüe (1024 dims)
- `bge-m3`: SOTA multilingual, més dimensions
- Models específics de domini
- Fine-tuning de models existents per casos específics

**Nota:** Actualment NEXE ja utilitza un sistema híbrid amb `nomic-embed-text` (768 dims) via Ollama, que ofereix molt bona qualitat.

### 2. Chunking semàntic

Usar NLP per dividir per temes, no per mida fixa.

### 3. Hybrid search

Combinar cerca vectorial + cerca per paraules clau:

```
Results = α × VectorScore + (1-α) × BM25Score
```

**Avantatge:** Millor precisió

### 4. Re-ranking amb LLM

Usar la LLM per avaluar resultats i re-ordenar.

### 5. Graph RAG

Construir un **graf de coneixement** sobre els vectors:

```
Entity: "NEXE" → relacionat amb → "FastAPI", "Qdrant", "Python"
```

**Avantatge:** Recuperar informació més rica i contextualitzada

### 6. Auto-update

Detectar quan un document canvia i reindexar-lo automàticament.

### 7. Multi-modal

Suportar imatges, àudio, vídeo (no només text):

```
Query: "Imatge d'un gat"
Results: <imatges similars>
```

**Requereix:** Models multi-modals (CLIP, etc.)

---

## Recursos

### Papers recomanats

- **RAG original:** "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (Lewis et al., 2020)
- **HNSW:** "Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs" (Malkov & Yashunin, 2018)
- **Sentence-BERT:** "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks" (Reimers & Gurevych, 2019)

### Eines relacionades

- **LangChain:** Framework Python per RAG
- **LlamaIndex:** Especialitzat en indexar documents
- **Haystack:** Framework per search i QA
- **Weaviate, Pinecone, Milvus:** Altres bases de dades vectorials

### Tutorials

- Documentació Qdrant: https://qdrant.tech/documentation/
- Sentence-Transformers: https://www.sbert.net/
- RAG a LangChain: https://python.langchain.com/docs/use_cases/question_answering/

---

## Resum tècnic

### Components clau
- **Embeddings:** Ollama nomic-embed-text (768 dims) + fallbacks
- **Base de dades:** Qdrant amb algorisme HNSW
- **Col·leccions:** nexe_web_ui (memòria personal), nexe_documentation, user_knowledge
- **Chunking:** 1500/200 chars (text), 800/100 chars (RAG endpoint)
- **Thresholds:** 0.4 (docs), 0.35 (knowledge), 0.3 (memory)

### Endpoints principals
- `POST /v1/chat/completions` - Chat amb RAG (use_rag: true)
- `POST /v1/memory/store` - Guardar a memòria
- `POST /v1/memory/search` - Cerca directa

### Configuració
- `server.toml`: Model d'embedding per defecte
- `storage/qdrant/`: Persistència de vectors
- Autenticació: X-API-Key header

---

## Següents passos

Per continuar aprenent sobre NEXE:

1. **API.md** - Referència completa de l'API REST
2. **SECURITY.md** - Sistema de seguretat i autenticació
3. **ARCHITECTURE.md** - Arquitectura general del sistema

---

**Nota:** RAG és una àrea en evolució ràpida. Aquesta implementació és funcional i en producció. Hi ha marge de millora amb tècniques com Graph RAG, hybrid search i re-ranking.

**Experimenta:** Els paràmetres de threshold i chunking són configurables. Ajusta'ls segons el teu cas d'ús específic.
