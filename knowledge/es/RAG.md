# === METADATA RAG ===
versio: "2.0"
data: 2026-04-02
id: nexe-rag-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referencia completa del sistema de memoria RAG de server-nexe (v0.9.0 pre-release). Cubre 3 colecciones Qdrant con thresholds, MEM_SAVE memoria automatica, intent de borrado, subida de documentos con aislamiento por sesion, embeddings (768D), parametros de chunking, construccion de contexto con etiquetas i18n, visualizacion de pesos RAG, sanitizacion de contexto RAG, poda inteligente, deduplicacion, TextStore para texto encriptado, y payloads de Qdrant sin texto."
tags: [rag, embeddings, qdrant, memory, mem_save, collections, thresholds, chunking, vectors, semantic-search, documents, session-isolation, delete-intent, pruning, deduplication, sanitization, text-store, encryption]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy"
expires: null
---

# Sistema RAG — server-nexe 0.9.0 pre-release

RAG (Retrieval-Augmented Generation) es el sistema de memoria persistente de server-nexe. Aumenta las respuestas del LLM inyectando informacion relevante recuperada de la memoria vectorial en el contexto del prompt.

## Como funciona el RAG en server-nexe

1. El usuario envia un mensaje
2. El mensaje se convierte en un vector de embedding de 768 dimensiones
3. Qdrant busca en 3 colecciones vectores similares (similitud coseno)
4. Los resultados coincidentes se sanitizan via `_sanitize_rag_context()` para filtrar patrones de inyeccion
5. Los resultados sanitizados se inyectan en el prompt del LLM como contexto
6. El LLM genera una respuesta usando el contexto aumentado
7. MEM_SAVE: el modelo tambien extrae hechos de la conversacion y los guarda en memoria (misma llamada LLM)

## Colecciones Qdrant

server-nexe usa 3 colecciones Qdrant especializadas. Cada una tiene un proposito diferente y un umbral de similitud diferente.

| Coleccion | Proposito | Threshold | Top-K | Contenido |
|-----------|---------|-----------|-------|---------|
| `nexe_documentation` | Documentacion del sistema (esta carpeta knowledge) | 0.4 | 3 | Auto-ingestada desde `docs/` y `knowledge/` en la instalacion |
| `user_knowledge` | Documentos subidos por el usuario | 0.35 | 3 | Subidos via Web UI o `nexe knowledge ingest`. Aislados por sesion via metadatos session_id |
| `personal_memory` | Memoria de conversacion (MEM_SAVE) | 0.3 | 2 | Extraccion automatica del chat. Maximo 500 entradas con poda inteligente |

**Orden de busqueda:** nexe_documentation primero (prioridad sistema), luego user_knowledge, luego personal_memory.

**Los thresholds son configurables** via variables de entorno:
- `NEXE_RAG_DOCS_THRESHOLD` (por defecto: 0.4)
- `NEXE_RAG_KNOWLEDGE_THRESHOLD` (por defecto: 0.35)
- `NEXE_RAG_MEMORY_THRESHOLD` (por defecto: 0.3)

La Web UI tambien permite ajustar el threshold en tiempo real via un slider (por defecto 0.30, rango configurable).

## Payloads de Qdrant (sin texto)

A partir de la v0.9.0, los payloads de Qdrant **ya no contienen texto**. Cada payload solo almacena:
- `entry_type` — el tipo de entrada
- `original_id` — enlace a SQLite para el texto completo

Todo el texto reside en SQLite (opcionalmente encriptado via SQLCipher). Esto significa que incluso sin encriptacion activada, los vectores de Qdrant por si solos no pueden reconstruir el contenido original del texto.

## TextStore (nuevo en v0.9.0)

`TextStore` (`memory/memory/api/text_store.py`) es un almacenamiento basado en SQLite para texto de documentos RAG, desacoplado de Qdrant:

- Almacena texto de documentos con `document_id` para enlace
- Opcionalmente encriptado via SQLCipher cuando `crypto_provider` esta disponible
- Usado por `store_document()`, `search_documents()`, `get_document()`, `delete_document()`
- Compatible hacia atras: si `text_store` no se proporciona, se usa el comportamiento legacy (texto en payload de Qdrant)

## Embeddings

**Modelo primario (via Ollama):** `nomic-embed-text` — 768 dimensiones. Usado cuando Ollama esta disponible.

**Modelo fallback (offline):** `paraphrase-multilingual-mpnet-base-v2` via sentence-transformers — 768 dimensiones. Multilingue. Usado cuando Ollama no esta disponible.

Todos los vectores se almacenan con 768 dimensiones. Este valor esta centralizado en `memory/memory/constants.py` como `DEFAULT_VECTOR_SIZE = 768`.

**Metrica de similitud:** Similitud coseno. Rango: -1 (opuesto) a +1 (identico).

## MEM_SAVE — Memoria automatica

server-nexe tiene un sistema de memoria automatica similar a ChatGPT o Claude. El modelo extrae hechos de las conversaciones y los guarda en memoria dentro de la misma llamada LLM (cero latencia adicional).

**Como funciona:**
1. El system prompt instruye al modelo a extraer hechos: nombres, trabajos, ubicaciones, preferencias, proyectos, deadlines
2. El modelo genera marcadores `[MEM_SAVE: hecho]` dentro de su respuesta
3. routes_chat.py parsea estos marcadores y los elimina del stream visible
4. Los hechos se guardan en la coleccion `personal_memory`
5. La UI muestra el indicador `[MEM:N]` con el recuento de hechos guardados

**Deteccion de intenciones (trilingue ca/es/en):**
- **Guardar:** "Recorda que...", "Guarda en memoria", "Remember that..."
- **Borrar:** "Oblida que...", "Borralo", "Forget that...", "Delete from memory"
- **Recordar:** Automatico via busqueda RAG en cada mensaje

**Filtros auto-save (que NO se guarda):**
- Preguntas (contienen "?")
- Comandos ("nexe", "status", etc.)
- Saludos ("hola", "hello")
- Basura (menos de 10 caracteres)
- Patrones negativos/basura (filtro regex para contenido no informativo)

**Deduplicacion:** Antes de guardar, comprueba similitud con entradas existentes. Si similitud > 0.80, la entrada se considera duplicada y no se guarda.

**Intent de borrado (MEM_DELETE):** Cuando el usuario dice "olvida que X", busca entradas con similitud >= DELETE_THRESHOLD (0.70). Borra la coincidencia mas cercana. Guard anti-re-save: `_recently_deleted_facts` evita que el modelo vuelva a guardar un hecho recien borrado dentro de la misma sesion.

**Truncado de documentos grandes:** Si un documento subido es demasiado grande para el contexto disponible, se trunca y la UI muestra un aviso amarillo via el marcador SSE `[DOC_TRUNCATED:XX%]` indicando el porcentaje descartado.

## Sanitizacion de contexto RAG

`_sanitize_rag_context()` filtra el contenido RAG recuperado antes de inyectarlo en el prompt del LLM. Esto previene que documentos almacenados o entradas de memoria contengan patrones de inyeccion que puedan manipular el comportamiento del modelo.

Se aplica en el pipeline de la Web UI (`routes_chat.py`) de forma consistente con el pipeline de la API.

## Subida de documentos con aislamiento de sesion

Los documentos subidos via la Web UI se indexan en la coleccion `user_knowledge` con `session_id` en los metadatos. Esto significa:

- Los documentos solo son visibles dentro de la sesion donde se subieron
- No hay contaminacion cruzada de contexto entre sesiones
- Los documentos persisten dentro de la sesion (no se borran al refrescar la pagina)
- Los metadatos se generan sin LLM (instantaneo, no requiere modelo)

**Formatos soportados:** .txt, .md, .pdf (con validacion de magic bytes SEC-004)
**Chunking para uploads:** Dinamico segun tamano del documento -- 800 chars (<20K), 1000 (<100K), 1200 (<300K), 1500 (>=300K). Si el documento tiene cabecera RAG valida, se usa el chunk_size especificado.

## Ingestion de documentos

### Documentacion del sistema (nexe_documentation)
- Fuente: carpeta `docs/` + `README.md`
- Chunking: 500 caracteres por chunk, 50 caracteres de overlap
- Ingestada via `core/ingest/ingest_docs.py`
- Recrea la coleccion en cada ingestion (inicio limpio)

### Conocimiento de usuario (user_knowledge via CLI)
- Fuente: carpeta `knowledge/` (subcarpetas ca/en/es)
- Chunking: 1500 caracteres por chunk por defecto (configurable via cabecera RAG chunk_size), overlap = max(50, chunk_size/10)
- Ingestado via `core/ingest/ingest_knowledge.py`
- Soporta cabeceras RAG con metadatos (`#!RAG id=..., priority=...`)

## Construccion del contexto

Cuando el RAG encuentra resultados relevantes, se inyectan en el prompt del LLM en 3 categorias etiquetadas:

| Categoria | Etiqueta (EN) | Etiqueta (CA) | Etiqueta (ES) | Coleccion fuente |
|----------|-----------|-----------|-----------|-------------------|
| Docs sistema | SYSTEM DOCUMENTATION | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | nexe_documentation |
| Docs tecnicos | TECHNICAL DOCUMENTATION | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | user_knowledge |
| Memoria usuario | USER MEMORY | MEMORIA USUARI | MEMORIA USUARIO | personal_memory |

**Limites de contexto:**
- `MAX_CONTEXT_CHARS` = 24000 (configurable via variable de entorno `NEXE_MAX_CONTEXT_CHARS`)
- El contexto RAG se trunca si excede el espacio disponible despues de restar system prompt, historial y mensaje actual

## Visualizacion de pesos RAG

La Web UI y el CLI muestran puntuaciones de relevancia RAG:

- **Marcador RAG_AVG:** Puntuacion media de todos los resultados recuperados
- **Marcadores RAG_ITEM:** Puntuacion individual por fuente con nombre de coleccion
- **Badge UI:** Barra con codigo de colores (verde > 0.7, amarillo 0.4-0.7, naranja < 0.4)
- **Detalle expandible:** Clic para ver puntuaciones individuales por fuente
- **CLI:** Flag `--verbose` para ver detalle por fuente

## Poda inteligente (coleccion personal_memory)

Cuando `personal_memory` supera `MAX_MEMORY_ENTRIES` (500), la poda inteligente elimina las entradas con puntuacion mas baja:

**Formula de retencion:**
- type_weight (0.4): peso basado en el tipo de memoria
- access_score (0.3): cuan recientemente se ha accedido
- recency_score (0.3): cuan recientemente se ha creado
- Bonus decaimiento temporal: +15% para entradas dentro de 7 dias (`TEMPORAL_DECAY_DAYS = 7`)

## Almacenamiento Qdrant

Qdrant funciona en modo embedded via `QdrantClient(path=...)` en el pool singleton `core/qdrant_pool.py`. Datos almacenados en:
```
storage/vectors/
├── collection/
│   ├── nexe_documentation/
│   ├── personal_memory/
│   └── user_knowledge/
└── meta.json
```

**Modo:** embedded (sin servidor externo, sin puerto). Los datos se cargan directamente del filesystem via RocksDB.
**Algoritmo:** HNSW (Hierarchical Navigable Small World) para busqueda rapida de vecinos aproximados

## Configuracion clave

| Variable | Por defecto | Proposito |
|----------|---------|---------|
| NEXE_RAG_DOCS_THRESHOLD | 0.4 | Puntuacion minima para nexe_documentation |
| NEXE_RAG_KNOWLEDGE_THRESHOLD | 0.35 | Puntuacion minima para user_knowledge |
| NEXE_RAG_MEMORY_THRESHOLD | 0.3 | Puntuacion minima para personal_memory |
| NEXE_MAX_CONTEXT_CHARS | 24000 | Ventana de contexto maxima en caracteres |
| NEXE_OLLAMA_EMBED_MODEL | nomic-embed-text | Modelo de embeddings Ollama |
| NEXE_ENCRYPTION_ENABLED | false | Activar encriptacion en reposo para TextStore/SQLCipher |

## Limitaciones

- **Homonimos:** "banco" (asiento) vs "banco" (finanzas) confunden embeddings — misma palabra, diferentes significados obtienen vectores similares
- **Negaciones:** "No me gusta Python" ≈ "Me gusta Python" en el espacio de embeddings (alta similitud)
- **Arranque en frio:** Memoria vacia = el RAG no aporta nada hasta que se puebla
- **Fallos de Top-K:** Chunks relevantes pueden quedar fuera de los resultados Top-K
- **Informacion contradictoria:** El RAG puede recuperar hechos conflictivos de diferentes momentos
- **Bug Ollama keep_alive:0:** No siempre libera VRAM en shutdown (problema conocido de Ollama)

## Endpoints principales para RAG

- `POST /v1/chat/completions` — Chat con RAG (use_rag: true por defecto)
- `POST /v1/memory/store` — Guardar texto en una coleccion
- `POST /v1/memory/search` — Busqueda semantica directa en una coleccion
- `DELETE /v1/rag/documents/{id}` — Borrar una entrada especifica
