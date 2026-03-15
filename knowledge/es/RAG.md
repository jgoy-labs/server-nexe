# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-rag-system

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guía completa del sistema RAG de NEXE. Cubre embeddings, Qdrant, chunking, búsqueda multi-colección y limitaciones. Explica cómo añadir documentos, hacer búsquedas semánticas y optimizar la recuperación de contexto."
tags: [rag, embeddings, qdrant, chunking, vectors, búsqueda-semántica, documentos]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Sistema RAG - NEXE 0.8

RAG (Retrieval-Augmented Generation) es el sistema de **memoria persistente** de NEXE. Este documento explica cómo funciona, por qué es útil y cómo usarlo de forma efectiva.

## Índice

1. [¿Qué es RAG?](#qué-es-rag)
2. [¿Por qué RAG?](#por-qué-rag)
3. [Cómo funciona en NEXE](#cómo-funciona-en-nexe)
4. [Embeddings](#embeddings)
5. [Qdrant y búsqueda vectorial](#qdrant-y-búsqueda-vectorial)
6. [Chunking de documentos](#chunking-de-documentos)
7. [Estrategias de retrieval](#estrategias-de-retrieval)
8. [Ejemplos prácticos](#ejemplos-prácticos)
9. [Limitaciones](#limitaciones)
10. [Mejoras futuras](#mejoras-futuras)

---

## ¿Qué es RAG?

**RAG = Retrieval-Augmented Generation**

Es una técnica que **aumenta las capacidades de una LLM** dándole acceso a información externa que no tiene en su entrenamiento.

### Problema que resuelve

Las LLMs (como Phi-3.5, Mistral, Llama) tienen **limitaciones**:

1. **Conocimiento limitado:** Solo saben lo que aprendieron durante el entrenamiento
2. **No recuerdan:** Cada conversación es independiente (sin estado)
3. **No te conocen:** No pueden recordar preferencias, proyectos, etc.
4. **Desfasadas:** El training es de una fecha pasada

### Solución: RAG

```
Pregunta usuario: "¿Cuáles son mis proyectos actuales?"
         ↓
   Búsqueda en memoria (RAG)
         ↓
   Encuentra: "NEXE 0.8, JGOY Quest"
         ↓
   Añade al contexto de la LLM
         ↓
   LLM genera respuesta con esta info
```

**Resultado:** La LLM puede responder con información que realmente no "sabe", pero que recupera de la memoria.

---

## ¿Por qué RAG?

### Ventajas vs. fine-tuning

| | RAG | Fine-tuning |
|---|-----|-------------|
| **Coste** | Bajo (solo embeddings) | Alto (reentrenar modelo) |
| **Actualización** | Inmediata (añadir a memoria) | Lenta (nuevo training) |
| **Flexibilidad** | Alta (cambiar datos fácilmente) | Baja (modelo fijo) |
| **Precisión** | Buena (información exacta) | Variable |
| **Transparencia** | Alta (ves qué recupera) | Baja (caja negra) |

### Ventajas vs. contexto largo

Algunos modelos tienen contexto de 100K+ tokens, pero:

- **Más lento:** Procesar mucho contexto es costoso
- **Degradación:** El rendimiento baja con contextos muy largos
- **Límite fijo:** Siempre hay un máximo
- **Ineficiente:** Pasar siempre todo el contexto es un desperdicio

RAG solo pasa el contexto **relevante** a la LLM.

---

## Cómo funciona en NEXE

### Arquitectura general

```
┌────────────────────────────────────────────────────────┐
│                     USUARIO                             │
│  "¿Cuáles son mis proyectos actuales?"                 │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              1. GENERACIÓN EMBEDDING                    │
│  Query → Ollama/sentence-transformers → Vector [768]   │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              2. BÚSQUEDA VECTORIAL (Qdrant)             │
│  Busca en 3 colecciones con thresholds diferentes      │
│  HNSW algorithm para búsqueda aproximada rápida        │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              3. CONSTRUCCIÓN DE CONTEXTO               │
│  Combina resultados de las 3 colecciones               │
│  Sanitiza contexto para prevenir prompt injection      │
│  Format: "[CONTEXT] <text1> <text2> ..."              │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              4. PROMPT AUMENTADO                        │
│  System: "Eres un asistente..."                        │
│  Context: "<información recuperada>"                   │
│  User: "¿Cuáles son mis proyectos actuales?"          │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│              5. GENERACIÓN LLM                          │
│  El modelo genera respuesta usando el contexto         │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│                    RESPUESTA                            │
│  "Tus proyectos actuales son NEXE 0.8 y               │
│   JGOY Quest según la información que tengo"          │
└────────────────────────────────────────────────────────┘
```

### Componentes del sistema

1. **Embedding Model:** Convierte texto a vectores
2. **Qdrant:** Base de datos vectorial para búsqueda
3. **MemoryAPI + chat.py:** Orquesta todo el proceso
4. **LLM:** Genera la respuesta final

---

## Embeddings

### ¿Qué son los embeddings?

Un **embedding** es una **representación numérica** de un texto que captura su significado semántico.

**Ejemplo conceptual:**

```
Text: "El gato está sobre el tejado"
  ↓
Embedding: [0.23, -0.51, 0.78, ..., 0.12]  (768 dimensions)
```

Textos con significado similar tienen vectores similares:

```
"El gato está sobre el tejado"    → [0.23, -0.51, 0.78, ...] (768 dims)
"Un gato encima de un tejado"     → [0.25, -0.49, 0.80, ...] (768 dims)
                                      ↑ ¡Vectores muy similares!

"Python es un lenguaje"           → [-0.82, 0.31, -0.15, ...] (768 dims)
                                      ↑ ¡Vector muy diferente!
```

### Modelos de embeddings en NEXE

NEXE utiliza un sistema híbrido de embeddings con varios modelos:

**Modelo prioritario (vía Ollama):** `nomic-embed-text`
- **Dimensiones:** 768
- **Ventajas:** Alta calidad, optimizado para Ollama
- **Uso:** Cuando Ollama está disponible (preferido)

**Modelo de configuración:** `mxbai-embed-large`
- Definido en `server.toml` como modelo por defecto
- Dimensiones compatibles con el sistema

**Modelo fallback (sentence-transformers):** `paraphrase-multilingual-mpnet-base-v2`
- **Dimensiones:** Configurable (DEFAULT_VECTOR_SIZE=768)
- **Multilingüe:** Excelente soporte para español
- **Offline:** No requiere API externa
- **Uso:** Cuando Ollama no está disponible

**Pipeline de embeddings:**
1. Intenta usar Ollama con `nomic-embed-text` (768 dims)
2. Si no está disponible, usa sentence-transformers con el modelo configurado
3. Todos los vectores se almacenan con 768 dimensiones

### Cómo se generan

```python
# Opción 1: Vía Ollama (prioritario)
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

# Opción 2: Vía sentence-transformers (fallback)
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
text = "El meu projecte és NEXE"
embedding = model.encode(text)

print(len(embedding))  # 768
print(embedding[:5])   # [0.234, -0.512, 0.789, ...]
```

### Similaridad entre vectores

Usamos **cosine similarity** para comparar vectores:

```python
from numpy import dot
from numpy.linalg import norm

def cosine_similarity(v1, v2):
    return dot(v1, v2) / (norm(v1) * norm(v2))

# Ejemplo
v1 = model.encode("gat sobre teulat")
v2 = model.encode("gat al damunt teulada")
v3 = model.encode("programar en Python")

print(cosine_similarity(v1, v2))  # 0.92 (molt similar)
print(cosine_similarity(v1, v3))  # 0.15 (molt diferent)
```

**Rango:** -1 (opuestos) a +1 (idénticos)
**Thresholds en NEXE:** Varían según colección (ver estrategias de retrieval)

---

## Qdrant y búsqueda vectorial

### ¿Por qué Qdrant?

Qdrant es una **base de datos vectorial** especializada en búsqueda semántica.

**Ventajas:**
- **Rápido:** Algoritmo HNSW (Hierarchical Navigable Small World)
- **Eficiente:** Optimizado para vectores de alta dimensión
- **Filtrable:** Permite filtrar por metadata
- **Persistencia:** Guarda datos en disco
- **Embedded mode:** No requiere servidor externo

### Algoritmo HNSW

**HNSW = Hierarchical Navigable Small World**

Es un algoritmo aproximado (ANN = Approximate Nearest Neighbors) que encuentra los vectores más similares **muy rápidamente**.

**Cómo funciona (simplificado):**

1. Construye un **grafo multicapa** de los vectores
2. Capa superior: Pocas conexiones, saltos grandes
3. Capas inferiores: Más conexiones, saltos pequeños
4. Búsqueda: Empieza arriba, baja hacia resultados exactos

**Trade-off:**
- **Exactitud:** ~95-99% (no 100% exacto)
- **Velocidad:** 100-1000x más rápido que búsqueda exhaustiva

### Estructura de datos en Qdrant

**Colecciones:** NEXE utiliza múltiples colecciones especializadas:

1. **`nexe_web_ui`:** Memoria de conversaciones con el usuario
2. **`nexe_documentation`:** Documentación técnica del sistema
3. **`user_knowledge`:** Conocimiento específico del usuario

**Cada punto tiene:**

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

### Búsqueda en Qdrant

**Ejemplo de búsqueda:**

```python
from qdrant_client import QdrantClient

client = QdrantClient(host="localhost", port=6333)

# Vector de la query
query_vector = [0.25, -0.49, ..., 0.14]

# Búsqueda (ejemplo con nexe_documentation)
results = client.search(
    collection_name="nexe_documentation",
    query_vector=query_vector,
    limit=3,              # Top-3 resultados
    score_threshold=0.4   # Similitud mínima (varía según colección)
)

for result in results:
    print(f"Score: {result.score}")
    print(f"Text: {result.payload['text']}")
```

**Respuesta:**

```
Score: 0.94
Text: El meu projecte és NEXE 0.8

Score: 0.87
Text: Estic desenvolupant NEXE, un servidor IA local

Score: 0.81
Text: NEXE és un projecte d'aprenentatge
```

### Persistencia

Qdrant guarda los datos en:
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

## Chunking de documentos

Cuando indexas documentos largos, hay que dividirlos en **chunks** (trozos).

### ¿Por qué chunking?

1. **Límites del modelo:** Los embeddings funcionan mejor con textos cortos-medios
2. **Granularidad:** Recuperar solo la parte relevante, no todo el documento
3. **Rendimiento:** Chunks pequeños = búsqueda más rápida

### Estrategias de chunking en NEXE

#### 1. Chunking fijo (por defecto)

NEXE utiliza chunking basado en **caracteres**, no palabras:

```python
def chunk_text(text, max_chunk_size=1500, chunk_overlap=200):
    """Dividir texto en chunks de tamaño fijo con overlap (en caracteres)"""
    chunks = []

    for i in range(0, len(text), max_chunk_size - chunk_overlap):
        chunk = text[i:i + max_chunk_size]
        chunks.append(chunk)

    return chunks
```

**Parámetros para texto general:**
- `max_chunk_size`: 1500 caracteres
- `chunk_overlap`: 200 caracteres
- `min_chunk_size`: 100 caracteres

**Parámetros para RAG endpoint:**
- `max_chunk_size`: 800 caracteres
- `chunk_overlap`: 100 caracteres

**Ejemplo:**

```
Documento: "Este es un documento muy largo sobre Python..."

Chunk 1: "Este es un documento muy largo sobre Python..." (1500 chars)
Chunk 2: "...bre Python y cómo programar con FastAPI..." (1500 chars)
Chunk 3: "...con FastAPI para crear APIs REST modernas..." (resto)
         ↑ 200 chars overlap ↑
```

**Importante:** El chunking es por CARACTERES, no palabras, para tener un control más preciso sobre el tamaño de los vectores.

#### 2. Chunking por párrafos (alternativo)

```python
def chunk_by_paragraphs(text, max_size=1500):
    """Dividir por párrafos (respeta estructura)"""
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

**Ventaja:** Respeta la estructura del documento
**Desventaja:** Chunks de tamaño más variable que chunking fijo

#### 3. Chunking semántico (futuro)

Dividir por **temas/secciones** usando NLP:

```python
# Futuro: Usar un modelo para detectar límites semánticos
def semantic_chunking(text):
    # Detectar cambios de tema
    # Dividir en lugares semánticamente coherentes
    pass
```

### Metadata por chunk

Cada chunk guarda metadata útil para el retrieval:

```json
{
  "text": "...chunk de texto...",
  "timestamp": 1706950400,
  "metadata": {
    "document_id": "doc-123",
    "document_name": "ARCHITECTURE.md",
    "chunk_index": 2,
    "total_chunks": 15,
    "section": "Componentes principales",
    "source": "documentation"
  }
}
```

**Utilidad:**
- Filtrar por documento origen o colección
- Reconstruir el orden original de los chunks
- Mostrar contexto y fuentes al usuario
- Priorizar información por timestamp (más reciente)

---

## Estrategias de retrieval

### 1. Multi-Collection Top-K

NEXE busca en múltiples colecciones con thresholds diferentes:

```python
# Búsqueda en nexe_documentation
docs_results = client.search(
    collection_name="nexe_documentation",
    query_vector=query_vector,
    limit=3,
    score_threshold=0.4  # Threshold más alto para docs técnicos
)

# Búsqueda en user_knowledge
knowledge_results = client.search(
    collection_name="user_knowledge",
    query_vector=query_vector,
    limit=3,
    score_threshold=0.35  # Threshold medio
)

# Búsqueda en nexe_web_ui
memory_results = client.search(
    collection_name="nexe_web_ui",
    query_vector=query_vector,
    limit=2,
    score_threshold=0.3  # Threshold más bajo para conversaciones
)
```

**Thresholds por colección:**
- `nexe_documentation`: 0.4 (información técnica precisa)
- `user_knowledge`: 0.35 (conocimiento del usuario)
- `nexe_web_ui`: 0.3 (contexto conversacional)

### 2. MMR (Maximal Marginal Relevance)

Evita retornar resultados demasiado similares entre sí:

```
Top-5 candidatos:
1. Score: 0.95 - "NEXE és un projecte..."
2. Score: 0.94 - "NEXE és un projecte d'IA..."  ← Muy similar a #1
3. Score: 0.88 - "JGOY Quest és un sistema..."   ← ¡Diferente!
4. Score: 0.85 - "El projecte NEXE..."          ← Similar a #1/#2
5. Score: 0.82 - "Desenvolupament amb Python..."← ¡Diferente!

MMR selecciona: #1, #3, #5 (diversidad)
```

**Implementación (futuro):**

```python
def mmr_retrieval(candidates, lambda_param=0.5):
    selected = []
    while len(selected) < 3:
        best = None
        best_score = -1

        for candidate in candidates:
            # Score = Relevancia - λ * Similaridad con seleccionados
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

### 3. Filtrado por metadata

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

**Búsqueda:** Solo en documentos con categoría específica

### 4. Re-ranking (futuro)

Usar la LLM para reordenar resultados:

```
1. Búsqueda vectorial → Top-20 candidatos
2. LLM evalúa cada candidato: "¿Es relevante para la query?"
3. Reordena según evaluación LLM
4. Retorna Top-5 finales
```

**Ventaja:** Más preciso
**Desventaja:** Más lento y costoso

---

## Ejemplos prácticos

### Ejemplo 1: Asistente personal vía API

```bash
# 1. Guardar información personal en user_knowledge
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

# 2. Preguntar con RAG activado
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "¿Dónde vivo?"}],
    "use_rag": true
  }'
```

**Respuesta:**
```json
{
  "choices": [{
    "message": {
      "content": "Según la información que tengo, vives en Barcelona."
    }
  }]
}
```

**Bajo el capó:**

1. Query: "¿Dónde vivo?" → Embedding (768 dims)
2. Búsqueda Qdrant → Encuentra: "...sóc de Barcelona" (score: 0.89)
3. Contexto: "El meu nom és Jordi i sóc de Barcelona"
4. Prompt a LLM: "Context: <info>. Pregunta: ¿Dónde vivo?"
5. LLM: "Vives en Barcelona"

### Ejemplo 2: Consultar base de conocimiento

```bash
# Consultar documentación vía API (RAG activado por defecto)
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": "¿Cómo funciona el sistema de plugins?"
    }],
    "use_rag": true
  }'
```

**Respuesta:**
```json
{
  "choices": [{
    "message": {
      "content": "El sistema de plugins de NEXE está basado en una interfaz BasePlugin que todos los plugins implementan. Los plugins se registran en el PluginRegistry y se cargan dinámicamente durante el inicio del servidor..."
    }
  }],
  "rag_context": {
    "sources": ["ARCHITECTURE.md", "PLUGINS.md"],
    "chunks_used": 3
  }
}
```

**Nota:** La documentación se indexa automáticamente en `nexe_documentation` durante la instalación/inicio del sistema.

### Ejemplo 3: Búsqueda por similitud semántica

```bash
# Buscar directamente en la memoria
curl -X POST http://127.0.0.1:9119/v1/memory/search \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "embeddings i cerca semàntica",
    "collection": "user_knowledge",
    "limit": 5
  }'
```

**Respuesta:**
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

**Magia:** ¡Busca por **significado semántico**, no palabras exactas! Palabras diferentes con el mismo concepto obtienen scores altos.

---

## Limitaciones

### 1. Calidad de los embeddings

**Problema:** El modelo de embeddings no es perfecto

**Ejemplo:**
```
Query: "¿Qué tiempo hace?"
Búsqueda: "tiempo de procesamiento", "tiempo verbal"
  ↑ Palabra "tiempo" con significados diferentes
```

**Mitigación:**
- Usar modelos mejores (más grandes, más específicos)
- Añadir contexto a las queries
- Filtrar resultados con score bajo

### 2. Límite de contexto

**Problema:** Solo se recuperan Top-K resultados

Si tienes mucha información, puede que la relevante no esté en el Top-5.

**Mitigación:**
- Aumentar K (pero más lento)
- Mejorar chunking (chunks más pequeños y precisos)
- Usar metadata para pre-filtrar

### 3. Información contradictoria

**Problema:** Si guardas información contradictoria:

```
Memoria:
- "Mi color favorito es el azul"
- "Me gusta el color rojo"
```

La LLM puede confundirse.

**Mitigación:**
- Mantener la memoria actualizada
- Borrar información antigua/incorrecta
- Timestamps para priorizar información reciente

### 4. Privacidad de los embeddings

**Problema:** Los embeddings contienen información semántica

Si alguien accede a la base de datos Qdrant, puede extraer información (aunque no sea trivial).

**Mitigación:**
- No exponer Qdrant públicamente
- Cifrar disco (FileVault, LUKS)
- Borrar datos sensibles cuando no se necesiten

### 5. Consumo de espacio

**Problema:** Cada chunk genera:
- Vector (768 floats × 4 bytes = 3 KB)
- Payload (texto + metadata = variable)

Muchos documentos = mucho espacio.

**Ejemplo:**
```
10.000 chunks × 4 KB/chunk = 40 MB (aceptable)
1.000.000 chunks × 4 KB/chunk = 4 GB (¡mucho!)
```

**Mitigación:**
- Chunking más agresivo (chunks más grandes)
- Comprimir payloads
- Borrar documentos antiguos

### 6. Cold start

**Problema:** Sin memoria, RAG no aporta nada

Durante la primera ejecución, NEXE:
- Carga automáticamente la documentación del sistema en `nexe_documentation`
- Las colecciones `user_knowledge` y `nexe_web_ui` empiezan vacías
- Se van llenando progresivamente con el uso del sistema

Las conversaciones con el usuario se almacenan automáticamente en `nexe_web_ui` cuando RAG está activado.

---

## Mejoras futuras

### 1. Embeddings mejores

**Opciones futuras:**
- `multilingual-e5-large`: Mejor calidad, multilingüe (1024 dims)
- `bge-m3`: SOTA multilingual, más dimensiones
- Modelos específicos de dominio
- Fine-tuning de modelos existentes para casos específicos

**Nota:** Actualmente NEXE ya utiliza un sistema híbrido con `nomic-embed-text` (768 dims) vía Ollama, que ofrece muy buena calidad.

### 2. Chunking semántico

Usar NLP para dividir por temas, no por tamaño fijo.

### 3. Hybrid search

Combinar búsqueda vectorial + búsqueda por palabras clave:

```
Results = α × VectorScore + (1-α) × BM25Score
```

**Ventaja:** Mejor precisión

### 4. Re-ranking con LLM

Usar la LLM para evaluar resultados y reordenar.

### 5. Graph RAG

Construir un **grafo de conocimiento** sobre los vectores:

```
Entity: "NEXE" → relacionado con → "FastAPI", "Qdrant", "Python"
```

**Ventaja:** Recuperar información más rica y contextualizada

### 6. Auto-update

Detectar cuando un documento cambia y reindexarlo automáticamente.

### 7. Multi-modal

Soportar imágenes, audio, vídeo (no solo texto):

```
Query: "Imagen de un gato"
Results: <imágenes similares>
```

**Requiere:** Modelos multi-modales (CLIP, etc.)

---

## Recursos

### Papers recomendados

- **RAG original:** "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (Lewis et al., 2020)
- **HNSW:** "Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs" (Malkov & Yashunin, 2018)
- **Sentence-BERT:** "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks" (Reimers & Gurevych, 2019)

### Herramientas relacionadas

- **LangChain:** Framework Python para RAG
- **LlamaIndex:** Especializado en indexar documentos
- **Haystack:** Framework para search y QA
- **Weaviate, Pinecone, Milvus:** Otras bases de datos vectoriales

### Tutoriales

- Documentación Qdrant: https://qdrant.tech/documentation/
- Sentence-Transformers: https://www.sbert.net/
- RAG en LangChain: https://python.langchain.com/docs/use_cases/question_answering/

---

## Resumen técnico

### Componentes clave
- **Embeddings:** Ollama nomic-embed-text (768 dims) + fallbacks
- **Base de datos:** Qdrant con algoritmo HNSW
- **Colecciones:** nexe_web_ui, nexe_documentation, user_knowledge
- **Chunking:** 1500/200 chars (texto), 800/100 chars (RAG endpoint)
- **Thresholds:** 0.4 (docs), 0.35 (knowledge), 0.3 (memory)

### Endpoints principales
- `POST /v1/chat/completions` - Chat con RAG (use_rag: true)
- `POST /v1/memory/store` - Guardar en memoria
- `POST /v1/memory/search` - Búsqueda directa

### Configuración
- `server.toml`: Modelo de embedding por defecto
- `storage/qdrant/`: Persistencia de vectores
- Autenticación: X-API-Key header

---

## Próximos pasos

Para continuar aprendiendo sobre NEXE:

1. **API.md** - Referencia completa de la API REST
2. **SECURITY.md** - Sistema de seguridad y autenticación
3. **ARCHITECTURE.md** - Arquitectura general del sistema

---

**Nota:** RAG es un área en rápida evolución. Esta implementación es funcional y está en producción. Hay margen de mejora con técnicas como Graph RAG, hybrid search y re-ranking.

**Experimenta:** Los parámetros de threshold y chunking son configurables. Ajústalos según tu caso de uso específico.
