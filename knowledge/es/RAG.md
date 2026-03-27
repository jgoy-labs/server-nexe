# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-rag-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Referencia completa del sistema de memoria RAG de server-nexe (v0.8.2). Cubre 3 colecciones Qdrant con thresholds, MEM_SAVE memoria automática, intent de borrado, subida de documentos con aislamiento por sesión, embeddings (768D), parámetros de chunking, construcción de contexto con etiquetas i18n, visualización pesos RAG, poda inteligente y deduplicación."
tags: [rag, embeddings, qdrant, memoria, mem_save, colecciones, thresholds, chunking, vectors, busqueda-semantica, documentos, aislamiento-sesion, intent-borrado, poda, deduplicacion]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema RAG — server-nexe 0.8.2

RAG (Retrieval-Augmented Generation) es el sistema de memoria persistente de server-nexe. Aumenta las respuestas del LLM inyectando información relevante recuperada de la memoria vectorial en el contexto del prompt.

## Cómo funciona el RAG en server-nexe

1. El usuario envía un mensaje
2. El mensaje se convierte en un vector de embedding de 768 dimensiones
3. Qdrant busca en 3 colecciones vectores similares (similitud coseno)
4. Los resultados coincidentes se inyectan en el prompt del LLM como contexto
5. El LLM genera una respuesta usando el contexto aumentado
6. MEM_SAVE: el modelo también extrae hechos de la conversación y los guarda en memoria (misma llamada LLM)

## Colecciones Qdrant

server-nexe usa 3 colecciones Qdrant especializadas. Cada una tiene un propósito diferente y un umbral de similitud diferente.

| Colección | Propósito | Threshold | Top-K | Contenido |
|-----------|---------|-----------|-------|---------|
| `nexe_documentation` | Documentación del sistema (esta carpeta knowledge) | 0.4 | 3 | Auto-ingestada desde `docs/` y `knowledge/` en la instalación |
| `user_knowledge` | Documentos subidos por el usuario | 0.35 | 3 | Subidos vía Web UI o `nexe knowledge ingest`. Aislados por sesión vía metadata session_id |
| `nexe_web_ui` | Memoria de conversación (MEM_SAVE) | 0.3 | 2 | Extracción automática del chat. Máximo 500 entradas con poda inteligente |

**Orden de búsqueda:** nexe_documentation primero (prioridad sistema), luego user_knowledge, luego nexe_web_ui.

**Los thresholds son configurables** vía variables de entorno:
- `NEXE_RAG_DOCS_THRESHOLD` (por defecto: 0.4)
- `NEXE_RAG_KNOWLEDGE_THRESHOLD` (por defecto: 0.35)
- `NEXE_RAG_MEMORY_THRESHOLD` (por defecto: 0.3)

La Web UI también permite ajustar el threshold en tiempo real vía un slider (por defecto 0.30).

## Embeddings

**Modelo primario (vía Ollama):** `nomic-embed-text` — 768 dimensiones. Usado cuando Ollama está disponible.

**Modelo fallback (offline):** `paraphrase-multilingual-mpnet-base-v2` vía sentence-transformers — 768 dimensiones. Multilingüe. Usado cuando Ollama no está disponible.

Todos los vectores se almacenan con 768 dimensiones. Este valor está centralizado en `memory/memory/constants.py` como `DEFAULT_VECTOR_SIZE = 768`.

**Métrica de similitud:** Similitud coseno. Rango: -1 (opuesto) a +1 (idéntico).

## MEM_SAVE — Memoria Automática

server-nexe tiene un sistema de memoria automática similar a ChatGPT o Claude. El modelo extrae hechos de las conversaciones y los guarda en memoria dentro de la misma llamada LLM (cero latencia extra).

**Cómo funciona:**
1. El system prompt instruye al modelo a extraer hechos: nombres, trabajos, ubicaciones, preferencias, proyectos, deadlines
2. El modelo genera marcadores `[MEM_SAVE: hecho]` dentro de su respuesta
3. routes_chat.py parsea estos marcadores y los elimina del stream visible
4. Los hechos se guardan en la colección `nexe_web_ui`
5. La UI muestra el indicador `[MEM:N]` con el contador de hechos guardados

**Detección de intenciones (trilingüe ca/es/en):**
- **Guardar:** "Recorda que...", "Guarda en memoria", "Remember that..."
- **Borrar:** "Oblida que...", "Bórralo", "Forget that...", "Delete from memory"
- **Recordar:** Automático vía búsqueda RAG en cada mensaje

**Filtros auto-save (qué NO se guarda):**
- Preguntas (contienen "?")
- Comandos ("nexe", "status", etc.)
- Saludos ("hola", "hello")
- Basura (menos de 10 caracteres)
- Patrones negativos (detectados vía SAVE_TRIGGERS y DELETE_TRIGGERS)

**Deduplicación:** Antes de guardar, comprueba similitud con entradas existentes. Si similitud > 0.80, la entrada se considera duplicada y no se guarda.

**Intent de borrado:** Cuando el usuario dice "olvida que X", busca entradas con similitud >= 0.6 y borra la coincidencia más cercana.

## Subida de Documentos con Aislamiento por Sesión

Los documentos subidos vía la Web UI se indexan en la colección `user_knowledge` con `session_id` en los metadatos. Esto significa:

- Los documentos solo son visibles dentro de la sesión donde se subieron
- No hay contaminación cruzada entre sesiones
- Los documentos persisten dentro de la sesión (no se borran al refrescar la página)
- Los metadatos se generan sin LLM (instantáneo, no requiere modelo)

**Formatos soportados:** .txt, .md, .pdf
**Chunking para uploads:** 1500 caracteres por chunk, 200 caracteres de overlap.

## Ingesta de Documentos

### Documentación del sistema (nexe_documentation)
- Fuente: carpeta `docs/` + `README.md`
- Chunking: 500 caracteres por chunk, 50 caracteres de overlap
- Ingestada vía `core/ingest/ingest_docs.py`
- Recrea la colección en cada ingesta (inicio limpio)

### Conocimiento de usuario (user_knowledge vía CLI)
- Fuente: carpeta `knowledge/` (subcarpetas ca/en/es)
- Chunking: 1500 caracteres por chunk, 200 caracteres de overlap
- Ingestado vía `core/ingest/ingest_knowledge.py`
- Soporta cabeceras RAG con metadatos (`#!RAG id=..., priority=...`)

## Construcción del Contexto

Cuando el RAG encuentra resultados relevantes, se inyectan en el prompt del LLM en 3 categorías etiquetadas:

| Categoría | Etiqueta (EN) | Etiqueta (CA) | Etiqueta (ES) | Colección fuente |
|----------|-----------|-----------|-----------|-------------------|
| Docs sistema | SYSTEM DOCUMENTATION | DOCUMENTACIO DEL SISTEMA | DOCUMENTACION DEL SISTEMA | nexe_documentation |
| Docs técnicos | TECHNICAL DOCUMENTATION | DOCUMENTACIO TECNICA | DOCUMENTACION TECNICA | user_knowledge |
| Memoria usuario | USER MEMORY | MEMORIA USUARI | MEMORIA USUARIO | nexe_web_ui |

**Límites de contexto:**
- `MAX_CONTEXT_CHARS` = 24000 (configurable vía variable de entorno `NEXE_MAX_CONTEXT_CHARS`)
- El contexto RAG se trunca si excede el espacio disponible después de restar system prompt, historial y mensaje actual

## Visualización Pesos RAG

La Web UI y el CLI muestran puntuaciones de relevancia RAG:

- **Marcador RAG_AVG:** Puntuación media de todos los resultados recuperados
- **Marcadores RAG_ITEM:** Puntuación individual por fuente con nombre de colección
- **Badge UI:** Barra con código de colores (verde > 0.7, amarillo 0.4-0.7, naranja < 0.4)
- **Detalle expandible:** Clic para ver puntuaciones individuales por fuente
- **CLI:** Flag `--verbose` para ver detalle por fuente

## Poda Inteligente (colección nexe_web_ui)

Cuando `nexe_web_ui` supera `MAX_MEMORY_ENTRIES` (500), la poda inteligente elimina las entradas con puntuación más baja:

**Fórmula de retención:**
- type_weight (0.4): peso basado en el tipo de memoria
- access_score (0.3): cuán recientemente se ha accedido
- recency_score (0.3): cuán recientemente se ha creado
- Bonus decaimiento temporal: +15% para entradas dentro de 7 días (`TEMPORAL_DECAY_DAYS = 7`)

## Almacenamiento Qdrant

Qdrant funciona como un binario embebido (sin servidor externo). Datos en:
```
storage/qdrant/
├── collection/
│   ├── nexe_documentation/
│   ├── nexe_web_ui/
│   └── user_knowledge/
└── meta.json
```

**Puerto Qdrant:** 6333 (configurable vía `NEXE_QDRANT_HOST` y `NEXE_QDRANT_PORT`)
**Algoritmo:** HNSW (Hierarchical Navigable Small World) para búsqueda rápida de vecinos aproximados

## Configuración Clave

| Variable | Por defecto | Propósito |
|----------|---------|---------|
| NEXE_RAG_DOCS_THRESHOLD | 0.4 | Puntuación mínima para nexe_documentation |
| NEXE_RAG_KNOWLEDGE_THRESHOLD | 0.35 | Puntuación mínima para user_knowledge |
| NEXE_RAG_MEMORY_THRESHOLD | 0.3 | Puntuación mínima para nexe_web_ui |
| NEXE_MAX_CONTEXT_CHARS | 24000 | Ventana de contexto máxima en caracteres |
| NEXE_QDRANT_HOST | localhost | Host Qdrant |
| NEXE_QDRANT_PORT | 6333 | Puerto Qdrant |
| NEXE_QDRANT_TIMEOUT | 5.0 | Timeout conexión Qdrant |
| NEXE_OLLAMA_EMBED_MODEL | nomic-embed-text | Modelo de embeddings Ollama |

## Limitaciones

- **Homónimos:** "banco" (asiento) vs "banco" (financiero) confunden embeddings — misma palabra, significados diferentes obtienen vectores similares
- **Negaciones:** "No me gusta Python" ≈ "Me gusta Python" en el espacio de embeddings (alta similitud)
- **Cold start:** Memoria vacía = RAG no aporta nada hasta que se puebla
- **Misses Top-K:** Chunks relevantes pueden quedar fuera de los resultados Top-K
- **Info contradictoria:** RAG puede recuperar hechos conflictivos de momentos diferentes
- **Vectores en disco sin cifrar:** Qdrant no cifra los vectores almacenados (aceptable para dispositivo local de confianza)
- **Bug Ollama keep_alive:0:** No siempre libera VRAM en shutdown (problema conocido de Ollama)

## Endpoints Principales para RAG

- `POST /v1/chat/completions` — Chat con RAG (use_rag: true por defecto)
- `POST /v1/memory/store` — Guardar texto en una colección
- `POST /v1/memory/search` — Búsqueda semántica directa en una colección
- `DELETE /v1/memory/{id}` — Borrar una entrada específica