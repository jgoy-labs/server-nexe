# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-rag-system
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referencia completa del sistema de memoria RAG de server-nexe (v1.0.0-beta). Cobreix 3 col·leccions Qdrant amb llindars, memoria automatica MEM_SAVE, intent d'esborrat (DELETE_THRESHOLD 0.20 post-Bug #18), pujada de documents amb aillament de sessio, embeddings (768D, fastembed ONNX principal offline), parametres de chunking, construccio de context amb etiquetes i18n, visualitzacio de pesos RAG, sanititzacio RAG injection (_filter_rag_injection), confirmacio clear_all 2-torns, precomputed KB embeddings, poda intel·ligent, deduplicacio, TextStore per a text encriptat i payloads de Qdrant sense text."
tags: [rag, embeddings, qdrant, memory, mem_save, collections, thresholds, chunking, vectors, semantic-search, documents, session-isolation, delete-intent, pruning, deduplication, sanitization, text-store, encryption]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Sistema RAG — server-nexe 1.0.0-beta

## Taula de continguts

- [Com funciona RAG a server-nexe](#com-funciona-rag-a-server-nexe)
- [Col·leccions Qdrant](#colleccions-qdrant)
- [Payloads de Qdrant (sense text)](#payloads-de-qdrant-sense-text)
- [TextStore (nou a la v0.9.0)](#textstore-nou-a-la-v090)
- [Embeddings](#embeddings)
- [MEM_SAVE — Memoria automatica](#mem_save--memoria-automatica)
  - [Confirmacio `clear_all` 2-torns](#confirmacio-clear_all-2-torns)
  - [Sanititzacio RAG injection (`_filter_rag_injection`)](#sanititzacio-rag-injection-_filter_rag_injection)
- [Sanititzacio de context RAG](#sanititzacio-de-context-rag)
- [Pujada de documents amb aillament de sessio](#pujada-de-documents-amb-aillament-de-sessio)
- [Ingestio de documents](#ingestio-de-documents)
  - [Documentacio del sistema (nexe_documentation)](#documentacio-del-sistema-nexe_documentation)
  - [Coneixement de l'usuari (user_knowledge via CLI)](#coneixement-de-lusuari-user_knowledge-via-cli)
- [Construccio del context](#construccio-del-context)
- [Visualitzacio de pesos RAG](#visualitzacio-de-pesos-rag)
- [Poda intel·ligent (col·leccio personal_memory)](#poda-intelligent-colleccio-personal_memory)
- [Emmagatzematge Qdrant](#emmagatzematge-qdrant)
- [Configuracio clau](#configuracio-clau)
- [Limitacions](#limitacions)
- [Endpoints principals per a RAG](#endpoints-principals-per-a-rag)

## En 30 segons

- **3 col·leccions Qdrant:** `personal_memory`, `user_knowledge`, `nexe_documentation`
- **Embeddings `fastembed` ONNX** (multilingue, 768 dimensions, offline)
- **Top-K retrieval** amb thresholds per col·leccio (0.3 / 0.35 / 0.4)
- **MEM_SAVE automatic:** el model extreu fets de les converses i els guarda
- **`_filter_rag_injection`** neutralitza tags maliciosos (MEM_SAVE, MEM_DELETE, OLVIDA, MEMORIA) a ingest i retrieval

---

RAG (Retrieval-Augmented Generation) es el sistema de memoria persistent de server-nexe. Augmenta les respostes del LLM injectant informacio rellevant recuperada de la memoria vectorial al context del prompt.

## Com funciona RAG a server-nexe

1. L'usuari envia un missatge
2. El missatge es converteix en un vector d'embedding de 768 dimensions
3. Qdrant cerca en 3 col·leccions vectors similars (similitud del cosinus)
4. Els resultats coincidents es sanititzen via `_sanitize_rag_context()` per filtrar patrons d'injeccio
5. Els resultats sanititzats s'injecten al prompt del LLM com a context
6. El LLM genera una resposta utilitzant el context augmentat
7. MEM_SAVE: el model tambe extreu fets de la conversa i els guarda a memoria (mateixa crida LLM)

## Col·leccions Qdrant

server-nexe utilitza 3 col·leccions Qdrant especialitzades. Cadascuna te un proposit diferent i un llindar de similitud diferent.

| Col·leccio | Proposit | Llindar | Top-K | Contingut |
|-----------|---------|-----------|-------|---------|
| `nexe_documentation` | Documentacio del sistema (aquesta carpeta knowledge) | 0.4 | 3 | Auto-ingerida de `docs/` i `knowledge/` a la instal·lacio |
| `user_knowledge` | Documents pujats per l'usuari | 0.35 | 3 | Pujats via Web UI o `nexe knowledge ingest`. Aillament per sessio via metadades session_id |
| `personal_memory` | Memoria de conversa (MEM_SAVE) | 0.3 | 2 | Extraccio automatica del xat. Maxim 500 entrades amb poda intel·ligent |

**Ordre de cerca:** nexe_documentation primer (prioritat del sistema), despres user_knowledge, despres personal_memory.

**Els llindars son configurables** via variables d'entorn:
- `NEXE_RAG_DOCS_THRESHOLD` (per defecte: 0.4)
- `NEXE_RAG_KNOWLEDGE_THRESHOLD` (per defecte: 0.35)
- `NEXE_RAG_MEMORY_THRESHOLD` (per defecte: 0.3)

La Web UI tambe permet l'ajust en temps real del llindar via un slider (per defecte 0.30, rang configurable).

## Payloads de Qdrant (sense text)

A partir de la v0.9.0, els payloads de Qdrant **ja no contenen text**. Cada payload nomes emmagatzema:
- `entry_type` — el tipus d'entrada
- `original_id` — enllac de tornada a SQLite per al text complet

Tot el text viu a SQLite (opcionalment encriptat via SQLCipher). Aixo significa que fins i tot sense encriptacio activada, els vectors de Qdrant sols no poden reconstruir el contingut original del text.

## TextStore (nou a la v0.9.0)

`TextStore` (`memory/memory/api/text_store.py`) es un emmagatzematge SQLite per al text de documents RAG, desacoblat de Qdrant:

- Emmagatzema text de documents amb `document_id` per a enllac de tornada
- Opcionalment encriptat via SQLCipher quan `crypto_provider` esta disponible
- Utilitzat per `store_document()`, `search_documents()`, `get_document()`, `delete_document()`
- Compatible enrere: si no es proporciona `text_store`, s'utilitza el comportament legacy (text al payload de Qdrant)

## Embeddings

**Model principal (offline, sempre disponible):** `paraphrase-multilingual-mpnet-base-v2` via **fastembed (ONNX)** — 768 dimensions, multilingue. És el **backend principal** des de v0.9.3 (migrat de sentence-transformers a fastembed, PyTorch eliminat ~600 MB). Funciona sense Ollama, sense xarxa, i ve **bundled al DMG** per garantir instal·lació offline.

**Model opcional (via Ollama):** `nomic-embed-text` — 768 dimensions. Configurable via `NEXE_OLLAMA_EMBED_MODEL`. Només s'usa si l'usuari ho activa explícitament; **no és el camí principal**.

**KB embeddings precomputats** (v0.9.8+): els fitxers de `knowledge/` tenen embeddings pre-calculats a `knowledge/.embeddings/`. A l'arrencada, si els hashes coincideixen, el sistema salta el càlcul i carrega directament (10.7× speedup a cold boot). Els embeddings es regeneren automàticament si canvia el contingut.

Tots els vectors s'emmagatzemen amb 768 dimensions. Aquest valor esta centralitzat a `memory/memory/constants.py` com `DEFAULT_VECTOR_SIZE = 768`.

**Metrica de similitud:** Similitud del cosinus. Rang: -1 (oposat) a +1 (identic).

## MEM_SAVE — Memoria automatica

server-nexe te un sistema de memoria automatica similar a ChatGPT o Claude. El model extreu fets de les converses i els guarda a memoria dins la mateixa crida LLM (zero latencia extra).

**Com funciona:**
1. El prompt del sistema instrueix el model per extreure fets: noms, feines, ubicacions, preferencies, projectes, terminis
2. El model genera marcadors `[MEM_SAVE: fet]` dins la seva resposta
3. routes_chat.py parseja aquests marcadors i els elimina del flux visible
4. Els fets es guarden a la col·leccio `personal_memory`
5. La UI mostra l'indicador `[MEM:N]` amb el recompte de fets guardats

**Deteccio d'intents (trilingue ca/es/en):**
- **Guardar:** "Recorda que...", "Guarda a memoria", "Remember that..."
- **Esborrar:** "Oblida que...", "Esborra-ho", "Forget that...", "Delete from memory"
- **Recuperar:** Automatic via cerca RAG a cada missatge

**Filtres d'auto-guardat (que NO es guarda):**
- Preguntes (contenen "?")
- Comandes ("nexe", "status", etc.)
- Salutacions ("hola", "hello")
- Brossa (menys de 10 caracters)
- Patrons negatius/brossa (filtre regex per a contingut no informatiu)

**Deduplicacio:** Abans de guardar, comprova la similitud amb entrades existents. Si la similitud > 0.80, l'entrada es considera duplicada i no es guarda.

**Flux complet d'un marcador MEM_SAVE:**

```
Resposta LLM
    │
    ▼
routes_chat.py — _extract_safe_mem_saves()
    │  · Regex estricte: [MEM_SAVE: <text 5-200 cars>]
    │  · Normalitza [MEMORIA: ...] → [MEM_SAVE: ...]
    │  · Valida whitelist de caracters (unicode segur)
    │  · Rebutja injection keywords, echo del prompt usuari
    │
    ├─── text net → flux visible (l'usuari no veu el marcador)
    │
    ▼
chat_memory.py — auto_save_to_memory()
    │  · Crea col·leccio personal_memory si no existeix
    │  · Comprova duplicats (similitud > 0.80 → descarta)
    │
    ▼
Qdrant — col·leccio personal_memory
    · Vector 768D (fastembed/ONNX)
    · Llindar de cerca: 0.3
    · Màxim 500 entrades (poda intel·ligent)
```

**Intent d'esborrat (MEM_DELETE):** Quan l'usuari diu "oblida que X", cerca entrades amb similitud >= **DELETE_THRESHOLD (0.20 des de v0.9.9)**. Esborra la coincidencia mes propera. Guard anti-re-save: `_recently_deleted_facts` evita que el model torni a guardar un fet acabat d'esborrar dins la mateixa sessio.

> **Bug #18 fix (v0.9.9):** El threshold anterior (0.70) era massa alt i cap coincidència passava la prova. Es va ajustar a **0.20** després de 8 tests e2e reals (`tests/integration/test_mem_delete_e2e.py`) contra Qdrant embedded + fastembed. Ara l'esborrat funciona consistentment.

### Confirmacio `clear_all` 2-torns

Si l'usuari demana esborrar **tot** (patrons com "esborra tota la memòria", "forget everything", "olvida todo"), el sistema **NO esborra immediatament**. En lloc d'això:

1. **Torn 1:** El servidor detecta el patró de `CLEAR_ALL_TRIGGERS`, marca `session._pending_clear_all = True` i demana confirmació explícita ("Estàs segur? Això esborrarà tota la teva memòria. Respon 'sí' per confirmar.").
2. **Torn 2:** Si l'usuari confirma amb un patró afirmatiu curt (`sí`, `confirma`, `ok`, etc.), es procedeix a esborrar la col·lecció. Qualsevol altre missatge cancel·la l'operació i reseteja el flag.

Això evita pèrdues massives accidentals per un missatge ambigu o una instrucció injectada per un document/prompt.

### Sanititzacio RAG injection (`_filter_rag_injection`)

Abans d'injectar context RAG al prompt del LLM (ingest + retrieval), `_filter_rag_injection` **neutralitza tags de control** que podrien manipular la memòria via efecte rebot:

- `[MEM_SAVE:…]` → eliminat (evita que el model auto-guardi pel simple fet de veure el patró a un document)
- `[MEM_DELETE:…]` → eliminat
- `[OLVIDA:…]` / `[OBLIT:…]` / `[FORGET:…]` → eliminats (intents trilingües d'esborrat)
- `[MEMORIA:…]` → eliminat

Això s'aplica **tant a l'ingest** (quan un document o una memòria es guarda) **com al retrieval** (quan es recupera per injectar al prompt), creant una doble barrera contra injecció RAG.

**Truncat de documents grans:** Si un document pujat es massa gran pel context disponible, es trunca i la UI mostra un avis groc amb el marcador SSE `[DOC_TRUNCATED:XX%]` indicant el percentatge descartat.

## Sanititzacio de context RAG

`_sanitize_rag_context()` filtra el contingut RAG recuperat abans d'injectar-lo al prompt del LLM. Aixo evita que documents emmagatzemats o entrades de memoria continguin patrons d'injeccio que podrien manipular el comportament del model.

S'aplica al pipeline de la Web UI (`routes_chat.py`) de manera consistent amb el pipeline de l'API.

## Pujada de documents amb aillament de sessio

Els documents pujats via la Web UI s'indexen a la col·leccio `user_knowledge` amb `session_id` a les metadades. Aixo significa:

- Els documents nomes son visibles dins la sessio on s'han pujat
- Sense contaminacio creuada de context de documents entre sessions
- Els documents persisteixen dins la sessio (no s'esborren en recarregar la pagina)
- Les metadades es generen sense LLM (instantani, no cal model)

**Formats suportats:** .txt, .md, .pdf (amb validacio de magic bytes SEC-004)
**Chunking per a pujades:** Dinamic segons mida del document — 800 chars (<20K), 1000 (<100K), 1200 (<300K), 1500 (>=300K). Si el document te capcalera RAG valida, s'utilitza el chunk_size especificat.

## Ingestio de documents

### Documentacio del sistema (nexe_documentation)
- Font: carpeta `docs/` + `README.md`
- Chunking: 500 caracters per chunk, 50 caracters de solapament
- Ingerida via `core/ingest/ingest_docs.py`
- Recrea la col·leccio a cada ingestio (inici net)

### Coneixement de l'usuari (user_knowledge via CLI)
- Font: carpeta `knowledge/` (subcarpetes ca/en/es)
- Chunking: 1500 caracters per chunk per defecte (configurable via capcalera RAG chunk_size), solapament = max(50, chunk_size/10)
- Ingerit via `core/ingest/ingest_knowledge.py`
- Suporta capcaleres RAG amb metadades (`#!RAG id=..., priority=...`)

## Construccio del context

Quan RAG troba resultats rellevants, s'injecten al prompt del LLM en 3 categories etiquetades:

| Categoria | Etiqueta (EN) | Etiqueta (CA) | Etiqueta (ES) | Col·leccio font |
|----------|-----------|-----------|-----------|-------------------|
| Docs del sistema | SYSTEM DOCUMENTATION | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | nexe_documentation |
| Docs tecnics | TECHNICAL DOCUMENTATION | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | user_knowledge |
| Memoria de l'usuari | USER MEMORY | MEMORIA USUARI | MEMORIA USUARIO | personal_memory |

**Limits de context:**
- `MAX_CONTEXT_CHARS` = 24000 (configurable via variable d'entorn `NEXE_MAX_CONTEXT_CHARS`)
- El context RAG es trunca si supera l'espai disponible despres de restar el prompt del sistema, l'historial i el missatge actual

## Visualitzacio de pesos RAG

La Web UI i el CLI mostren les puntuacions de rellevancia RAG:

- **Marcador RAG_AVG:** Puntuacio mitjana de tots els resultats recuperats
- **Marcadors RAG_ITEM:** Puntuacio individual per font amb nom de col·leccio
- **Badge UI:** Barra amb codi de colors (verd > 0.7, groc 0.4-0.7, taronja < 0.4)
- **Detall expandible:** Fes clic per veure les puntuacions individuals per font
- **CLI:** Utilitza el flag `--verbose` per veure el detall per font

## Poda intel·ligent (col·leccio personal_memory)

Quan `personal_memory` supera `MAX_MEMORY_ENTRIES` (500), la poda intel·ligent elimina les entrades amb menor puntuacio:

**Formula de puntuacio de retencio:**
- type_weight (0.4): pes basat en el tipus de memoria
- access_score (0.3): com de recent s'ha accedit
- recency_score (0.3): com de recent s'ha creat
- Bonus de decaiment temporal: +15% per a entrades dels ultims 7 dies (`TEMPORAL_DECAY_DAYS = 7`)

## Emmagatzematge Qdrant

Qdrant s'executa en mode embedded via `QdrantClient(path=...)` al pool singleton `core/qdrant_pool.py`. Dades emmagatzemades a:
```
storage/vectors/
├── collection/
│   ├── nexe_documentation/
│   ├── personal_memory/
│   └── user_knowledge/
└── meta.json
```

**Mode:** embedded (sense servidor extern, sense port). Les dades es carreguen directament del filesystem via RocksDB.
**Algorisme:** HNSW (Hierarchical Navigable Small World) per a cerca rapida de veins aproximats

## Configuracio clau

| Variable | Per defecte | Proposit |
|----------|---------|---------|
| NEXE_RAG_DOCS_THRESHOLD | 0.4 | Puntuacio minima per a nexe_documentation |
| NEXE_RAG_KNOWLEDGE_THRESHOLD | 0.35 | Puntuacio minima per a user_knowledge |
| NEXE_RAG_MEMORY_THRESHOLD | 0.3 | Puntuacio minima per a personal_memory |
| NEXE_MAX_CONTEXT_CHARS | 24000 | Finestra de context maxima en caracters |
| NEXE_OLLAMA_EMBED_MODEL | nomic-embed-text | Model d'embedding d'Ollama |
| NEXE_ENCRYPTION_ENABLED | auto | Activar encriptacio at-rest per a TextStore/SQLCipher |

## Limitacions

- **Homonims:** "bank" (seient) vs "bank" (finances) confonen els embeddings — mateixa paraula, significats diferents obtenen vectors similars
- **Negacions:** "No m'agrada Python" ~ "M'agrada Python" a l'espai d'embeddings (alta similitud)
- **Inici en fred:** Memoria buida = RAG no contribueix res fins que es pobla
- **Falles Top-K:** Chunks rellevants poden quedar fora dels resultats Top-K
- **Informacio contradictoria:** RAG pot recuperar fets conflictius de periodes de temps diferents
- **Bug Ollama keep_alive:0:** No sempre allibera la VRAM a l'aturada (problema conegut d'Ollama)

## Endpoints principals per a RAG

- `POST /v1/chat/completions` — Xat amb RAG (use_rag: true per defecte)
- `POST /v1/memory/store` — Guardar text a una col·leccio
- `POST /v1/memory/search` — Cerca semantica directa en una col·leccio
- `DELETE /v1/rag/documents/{id}` — Esborrar una entrada especifica
