# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-rag-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referència completa del sistema de memòria RAG de server-nexe (v0.8.2). Cobreix 3 col·leccions Qdrant amb thresholds, MEM_SAVE memòria automàtica, intent d'esborrat, pujada de documents amb aïllament per sessió, embeddings (768D), paràmetres de chunking, construcció de context amb etiquetes i18n, visualització pesos RAG, poda intel·ligent i deduplicació."
tags: [rag, embeddings, qdrant, memoria, mem_save, colleccions, thresholds, chunking, vectors, cerca-semantica, documents, aillament-sessio, intent-esborrat, poda, deduplicacio]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema RAG — server-nexe 0.8.2

RAG (Retrieval-Augmented Generation) és el sistema de memòria persistent de server-nexe. Augmenta les respostes del LLM injectant informació rellevant recuperada de la memòria vectorial al context del prompt.

## Com funciona el RAG a server-nexe

1. L'usuari envia un missatge
2. El missatge es converteix en un vector d'embedding de 768 dimensions
3. Qdrant cerca en 3 col·leccions vectors similars (similitud cosinus)
4. Els resultats coincidents s'injecten al prompt del LLM com a context
5. El LLM genera una resposta usant el context augmentat
6. MEM_SAVE: el model també extreu fets de la conversa i els guarda a memòria (mateixa crida LLM)

## Col·leccions Qdrant

server-nexe usa 3 col·leccions Qdrant especialitzades. Cadascuna té un propòsit diferent i un llindar de similitud diferent.

| Col·lecció | Propòsit | Threshold | Top-K | Contingut |
|-----------|---------|-----------|-------|---------|
| `nexe_documentation` | Documentació del sistema (aquesta carpeta knowledge) | 0.4 | 3 | Auto-ingestada des de `docs/` i `knowledge/` a la instal·lació |
| `user_knowledge` | Documents pujats per l'usuari | 0.35 | 3 | Pujats via Web UI o `nexe knowledge ingest`. Aïllats per sessió via metadata session_id |
| `nexe_web_ui` | Memòria de conversa (MEM_SAVE) | 0.3 | 2 | Extracció automàtica del xat. Màxim 500 entrades amb poda intel·ligent |

**Ordre de cerca:** nexe_documentation primer (prioritat sistema), després user_knowledge, després nexe_web_ui.

**Els thresholds són configurables** via variables d'entorn:
- `NEXE_RAG_DOCS_THRESHOLD` (per defecte: 0.4)
- `NEXE_RAG_KNOWLEDGE_THRESHOLD` (per defecte: 0.35)
- `NEXE_RAG_MEMORY_THRESHOLD` (per defecte: 0.3)

La Web UI també permet ajustar el threshold en temps real via un slider (per defecte 0.30).

## Embeddings

**Model primari (via Ollama):** `nomic-embed-text` — 768 dimensions. Usat quan Ollama està disponible.

**Model fallback (offline):** `paraphrase-multilingual-mpnet-base-v2` via sentence-transformers — 768 dimensions. Multilingüe. Usat quan Ollama no està disponible.

Tots els vectors s'emmagatzemen amb 768 dimensions. Aquest valor està centralitzat a `memory/memory/constants.py` com `DEFAULT_VECTOR_SIZE = 768`.

**Mètrica de similitud:** Similitud cosinus. Rang: -1 (oposat) a +1 (idèntic).

## MEM_SAVE — Memòria Automàtica

server-nexe té un sistema de memòria automàtica similar a ChatGPT o Claude. El model extreu fets de les converses i els guarda a memòria dins la mateixa crida LLM (zero latència extra).

**Com funciona:**
1. El system prompt instrueix el model a extreure fets: noms, feines, ubicacions, preferències, projectes, deadlines
2. El model genera marcadors `[MEM_SAVE: fet]` dins la seva resposta
3. routes_chat.py parseja aquests marcadors i els treu del stream visible
4. Els fets es guarden a la col·lecció `nexe_web_ui`
5. La UI mostra l'indicador `[MEM:N]` amb el comptador de fets guardats

**Detecció d'intencions (trilingüe ca/es/en):**
- **Guardar:** "Recorda que...", "Guarda a memòria", "Remember that..."
- **Esborrar:** "Oblida que...", "Esborra-ho", "Forget that...", "Delete from memory"
- **Recordar:** Automàtic via cerca RAG a cada missatge

**Filtres auto-save (què NO es guarda):**
- Preguntes (contenen "?")
- Comandes ("nexe", "status", etc.)
- Salutacions ("hola", "hello")
- Brossa (menys de 10 caràcters)
- Patrons negatius (detectats via SAVE_TRIGGERS i DELETE_TRIGGERS)

**Deduplicació:** Abans de guardar, comprova similitud amb entrades existents. Si similitud > 0.80, l'entrada es considera duplicada i no es guarda.

**Intent d'esborrat:** Quan l'usuari diu "oblida que X", cerca entrades amb similitud >= 0.6 i esborra la coincidència més propera.

## Pujada de Documents amb Aïllament per Sessió

Els documents pujats via la Web UI s'indexen a la col·lecció `user_knowledge` amb `session_id` a les metadades. Això vol dir:

- Els documents només són visibles dins la sessió on es van pujar
- No hi ha contaminació creuada entre sessions
- Els documents persisteixen dins la sessió (no s'esborren en refrescar la pàgina)
- Les metadades es generen sense LLM (instantani, no cal model)

**Formats suportats:** .txt, .md, .pdf
**Chunking per uploads:** 1500 caràcters per chunk, 200 caràcters d'overlap.

## Ingesta de Documents

### Documentació del sistema (nexe_documentation)
- Font: carpeta `docs/` + `README.md`
- Chunking: 500 caràcters per chunk, 50 caràcters d'overlap
- Ingestada via `core/ingest/ingest_docs.py`
- Recrea la col·lecció a cada ingesta (inici net)

### Coneixement d'usuari (user_knowledge via CLI)
- Font: carpeta `knowledge/` (subcarpetes ca/en/es)
- Chunking: 1500 caràcters per chunk, 200 caràcters d'overlap
- Ingestat via `core/ingest/ingest_knowledge.py`
- Suporta capçaleres RAG amb metadades (`#!RAG id=..., priority=...`)

## Construcció del Context

Quan el RAG troba resultats rellevants, s'injecten al prompt del LLM en 3 categories etiquetades:

| Categoria | Etiqueta (EN) | Etiqueta (CA) | Etiqueta (ES) | Col·lecció font |
|----------|-----------|-----------|-----------|-------------------|
| Docs sistema | SYSTEM DOCUMENTATION | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | nexe_documentation |
| Docs tècnics | TECHNICAL DOCUMENTATION | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | user_knowledge |
| Memòria usuari | USER MEMORY | MEMORIA USUARI | MEMORIA USUARIO | nexe_web_ui |

**Límits de context:**
- `MAX_CONTEXT_CHARS` = 24000 (configurable via variable d'entorn `NEXE_MAX_CONTEXT_CHARS`)
- El context RAG es trunca si excedeix l'espai disponible després de restar system prompt, historial i missatge actual

## Visualització Pesos RAG

La Web UI i el CLI mostren puntuacions de rellevància RAG:

- **Marcador RAG_AVG:** Puntuació mitjana de tots els resultats recuperats
- **Marcadors RAG_ITEM:** Puntuació individual per font amb nom de col·lecció
- **Badge UI:** Barra amb codi de colors (verd > 0.7, groc 0.4-0.7, taronja < 0.4)
- **Detall expandible:** Clic per veure puntuacions individuals per font
- **CLI:** Flag `--verbose` per veure detall per font

## Poda Intel·ligent (col·lecció nexe_web_ui)

Quan `nexe_web_ui` supera `MAX_MEMORY_ENTRIES` (500), la poda intel·ligent elimina les entrades amb puntuació més baixa:

**Fórmula de retenció:**
- type_weight (0.4): pes basat en el tipus de memòria
- access_score (0.3): com de recentment s'ha accedit
- recency_score (0.3): com de recentment s'ha creat
- Bonus decaïment temporal: +15% per entrades dins 7 dies (`TEMPORAL_DECAY_DAYS = 7`)

## Emmagatzematge Qdrant

Qdrant corre com un binari embedit (sense servidor extern). Dades a:
```
storage/qdrant/
├── collection/
│   ├── nexe_documentation/
│   ├── nexe_web_ui/
│   └── user_knowledge/
└── meta.json
```

**Port Qdrant:** 6333 (configurable via `NEXE_QDRANT_HOST` i `NEXE_QDRANT_PORT`)
**Algorisme:** HNSW (Hierarchical Navigable Small World) per cerca ràpida de veïns aproximats

## Configuració Clau

| Variable | Per defecte | Propòsit |
|----------|---------|---------|
| NEXE_RAG_DOCS_THRESHOLD | 0.4 | Puntuació mínima per nexe_documentation |
| NEXE_RAG_KNOWLEDGE_THRESHOLD | 0.35 | Puntuació mínima per user_knowledge |
| NEXE_RAG_MEMORY_THRESHOLD | 0.3 | Puntuació mínima per nexe_web_ui |
| NEXE_MAX_CONTEXT_CHARS | 24000 | Finestra de context màxima en caràcters |
| NEXE_QDRANT_HOST | localhost | Host Qdrant |
| NEXE_QDRANT_PORT | 6333 | Port Qdrant |
| NEXE_QDRANT_TIMEOUT | 5.0 | Timeout connexió Qdrant |
| NEXE_OLLAMA_EMBED_MODEL | nomic-embed-text | Model d'embeddings Ollama |

## Limitacions

- **Homònims:** "banc" (seient) vs "banc" (financer) confonen embeddings — mateixa paraula, significats diferents obtenen vectors similars
- **Negacions:** "No m'agrada Python" ≈ "M'agrada Python" a l'espai d'embeddings (alta similitud)
- **Cold start:** Memòria buida = RAG no aporta res fins que es pobla
- **Misses Top-K:** Chunks rellevants poden quedar fora dels resultats Top-K
- **Info contradictòria:** RAG pot recuperar fets conflictius de moments diferents
- **Vectors a disc sense xifrar:** Qdrant no xifra els vectors emmagatzemats (acceptable per dispositiu local de confiança)
- **Bug Ollama keep_alive:0:** No sempre allibera VRAM al shutdown (problema conegut d'Ollama)

## Endpoints Principals per RAG

- `POST /v1/chat/completions` — Chat amb RAG (use_rag: true per defecte)
- `POST /v1/memory/store` — Guardar text a una col·lecció
- `POST /v1/memory/search` — Cerca semàntica directa en una col·lecció
- `DELETE /v1/memory/{id}` — Esborrar una entrada específica