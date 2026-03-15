# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guía práctica de uso de NEXE. Inicio y parada del servidor, comandos CLI, chat interactivo con pipeline unificado CLI+UI, sistema de memoria, subida de documentos con /upload, RAG adaptativo por tamaño de documento, cabeceras RAG para indexación óptima, uso de la API y casos de uso prácticos."
tags: [uso, cli, chat, memory, rag, api, web-ui, upload, cabecera-rag, pipeline-unificado]
chunk_size: 900
priority: P1

# === OPCIONAL ===
lang: es
type: tutorial
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Guía de Uso - NEXE 0.8

Esta guía te enseña a usar NEXE con ejemplos prácticos. Asume que ya tienes NEXE instalado (si no, consulta **INSTALLATION.md**).

## Índice

1. [Iniciar y detener el servidor](#iniciar-y-detener-el-servidor)
2. [CLI básico](#cli-básico)
3. [Chat interactivo](#chat-interactivo)
4. [Subir documentos al chat](#subir-documentos-al-chat)
5. [Sistema de memoria (RAG)](#sistema-de-memoria-rag)
6. [Cabeceras RAG para documentos](#cabeceras-rag-para-documentos)
7. [Gestión de documentos](#gestión-de-documentos)
8. [Uso de la API](#uso-de-la-api)
9. [Web UI](#web-ui)
10. [Casos de uso prácticos](#casos-de-uso-prácticos)
11. [Consejos y buenas prácticas](#consejos-y-buenas-prácticas)

---

## Iniciar y detener el servidor

### Iniciar el servidor

```bash
cd server-nexe
./nexe go
```

**Salida esperada:**
```
🚀 Iniciant NEXE 0.8...
✓ Backend: MLX
✓ Model: Qwen3-32B-4bit
✓ Qdrant: Connectat
✓ Port: 9119

Servidor operatiu a http://localhost:9119
Web UI a http://localhost:9119/ui
API docs a http://localhost:9119/docs

Prem Ctrl+C per aturar
```

### Verificar estado

```bash
./nexe status
```

### Detener el servidor

```bash
./nexe stop              # detiene Nexe Server + Qdrant
./nexe stop --force      # sin confirmación
```

Si está en primer plano, también puedes usar `Ctrl+C`.

---

## CLI básico

### Comandos disponibles

```bash
./nexe --help
```

**Comandos principales:**

| Comando | Descripción |
|---------|-------------|
| `go` | Inicia el servidor |
| `status` | Estado del sistema |
| `chat` | Chat interactivo |
| `memory` | Gestión de memoria (store, recall, stats, cleanup) |
| `knowledge` | Gestión de documentos (ingest, status) |
| `logs` | Ver logs |
| `--version` | Versión de NEXE |

---

## Chat interactivo

El CLI usa exactamente el **mismo pipeline que el Web UI**: sesiones servidor, memoria automática y búsqueda semántica siempre activa. No hace falta el flag `--rag`.

### Iniciar el chat

```bash
./nexe chat
```

**Ejemplo de sesión:**
```
  🚀 Nexe Chat
  Engine: mlx  |  Model: Qwen3-32B-4bit  |  Memoria: ✅ Activa
  ─────────────────────────────────────────
  Commands: /upload <ruta> · /save <texto> · /recall <query> · /help
  Type "exit" or Ctrl+C to quit

Tu: Hola, ¿quién eres?
  ⠹ 1.2s
Nexe: ¡Hola! Soy Nexe, el asistente experto de Server Nexe.
¿En qué puedo ayudarte?

Tu: ¿Qué proyectos tengo activos?
  ⠸ 2.8s
Nexe: Según lo que tengo en memoria, estás trabajando
en NEXE 0.8 y NAT7...
```

El **spinner con temporizador** (`⠹ 2.8s`) indica que el sistema está buscando en RAG y cargando el modelo. Desaparece cuando llega el primer token.

Al final de cada respuesta aparece el **tiempo total** en gris:
```
Nexe: El documento trata de...
  [34.7s]
```

### Comandos dentro del chat

| Comando | Descripción |
|---------|-------------|
| `/upload <ruta>` | Sube un documento para analizar |
| `/save <texto>` | Guarda información en la memoria persistente |
| `/recall <query>` | Búsqueda directa en memoria |
| `/help` | Muestra todos los comandos |
| `clear` | Reinicia la sesión (nuevo contexto, RAG intacto) |
| `exit` / `quit` | Sale del chat |

### Contexto de sesión

Dentro de una misma sesión de chat, el modelo **recuerda todo lo que has dicho**. El contexto se mantiene hasta que haces `clear` o cierras el chat.

- `clear` → nueva sesión, historial limpio. **El RAG no se borra**: los documentos subidos anteriormente siguen accesibles por búsqueda semántica.
- Cerrar el chat y volver a abrirlo → nueva sesión, pero la memoria RAG persiste entre sesiones.

### Opciones del comando

```bash
# Engine específico
./nexe chat --engine mlx

# Nota: --rag y --system se ignoran (el pipeline UI los gestiona siempre)
```

---

## Subir documentos al chat

Puedes subir documentos directamente en el chat CLI y hacer preguntas sobre ellos. Funciona igual que arrastrar un fichero al Web UI.

### Comando /upload

```bash
# Dentro del chat:
Tu: /upload /ruta/al/informe.pdf
📎 Subiendo informe.pdf...
✅ informe.pdf indexado (24 partes). Ahora puedes hacer preguntas sobre el documento.

Tu: hazme un resumen ejecutivo
Nexe: El documento trata de...
```

**Rutas con espacios:** usa `\ ` para escapar los espacios:
```
/upload /Users/jordi/Documents/Mi\ Proyecto/informe.md
```

**Pregunta directa tras el upload:** puedes añadir la pregunta en el mismo comando:
```
Tu: /upload /ruta/NEGOCI.md hazme un resumen ejecutivo
📎 Subiendo NEGOCI.md...
✅ NEGOCI.md indexado (28 partes).
Nexe: El documento es un plan de negocio que...
```

### Formatos soportados

`.pdf`, `.txt`, `.md`, `.markdown` y otros formatos de texto.

### Cómo funciona la subida

1. **Slot de sesión**: el documento se adjunta a la sesión actual. El primer mensaje lo recibe como contexto completo (hasta 50 partes).
2. **Indexación RAG**: todos los chunks se guardan en `nexe_web_ui`. Persisten entre sesiones y se recuperan por búsqueda semántica.
3. **Metadatos LLM**: si el documento no tiene cabecera RAG, el sistema usa el LLM para generar automáticamente un abstract y tags consistentes con el contenido real del documento.

### Múltiples documentos

```
/upload doc1.pdf           → indexado + adjuntado a sesión
Tu: resumen de doc1?       → recibe doc1 como contexto completo
/upload doc2.pdf           → indexado + sobreescribe slot de sesión
Tu: resumen de doc2?       → recibe doc2 como contexto completo
Tu: compara doc1 y doc2    → ambos accesibles via RAG semántico
```

**Recomendación:** haz la pregunta principal **justo después de cada `/upload`** para aprovechar el contexto completo. Las preguntas posteriores acceden via RAG.

---

## Sistema de memoria (RAG)

NEXE guarda automáticamente cada mensaje del usuario en Qdrant (`nexe_web_ui`). Antes de generar cada respuesta, realiza una búsqueda semántica para recuperar el contexto relevante.

### Cómo funciona el auto-save

**Cada mensaje que envías** se guarda automáticamente si:
- Tiene 8 o más caracteres
- No es un saludo puro ("hola", "gracias", "ok"...)
- No es duplicado de algo ya guardado (similitud > 80%)

### Guardar explícitamente

```bash
# Guardar desde el CLI de sistema
./nexe memory store "Mi framework favorito es FastAPI"

# Guardar desde dentro del chat
Tu: /save Trabajo en el proyecto NAT7 para NatSystem
```

### Recuperar de la memoria

```bash
# Desde CLI de sistema
./nexe memory recall "framework favorito"

# Desde dentro del chat
Tu: /recall proyectos activos
```

### Limpiar memoria

```bash
./nexe memory cleanup
```

### Estadísticas de memoria

```bash
./nexe memory stats
```

### Precisión RAG (threshold)

Cuando el sistema busca en la memoria, filtra los resultados por **similitud semántica**. El umbral de precisión controla cuánto debe parecerse un recuerdo a tu pregunta para ser incluido en el contexto.

**Valor por defecto: 0.6**

| Valor | Comportamiento |
|-------|----------------|
| 0.3–0.5 | Amplio — más contexto, mayor riesgo de alucinación |
| 0.6 | Equilibrado (recomendado) |
| 0.7–0.8 | Preciso — menos contexto, respuestas más enfocadas |
| 0.9+ | Muy estricto — recupera casi nada |

**Web UI:** slider "Precisió RAG" en el sidebar (bajo el nombre del modelo). El valor se guarda en `localStorage`. Pasa por encima del `ⓘ` para ver la explicación.

**CLI:** el threshold se aplica automáticamente con el valor por defecto (0.6). No configurable en tiempo real desde la CLI.

> **Consejo:** si el modelo alucina o mezcla información de documentos no relacionados, sube el threshold a 0.7–0.75.

---

## Cabeceras RAG para documentos

La **cabecera RAG** es la clave para una búsqueda semántica de calidad. Cuando un documento tiene cabecera, el sistema usa `chunk_size`, `abstract` y `tags` para indexarlo de manera óptima.

### Chunk size adaptativo (sin cabecera)

Cuando subes un documento sin cabecera (via `/upload` o Web UI), el sistema elige automáticamente el `chunk_size` según el tamaño. Además, el LLM genera automáticamente un abstract y tags analizando el contenido real:

| Tamaño del documento | Chunk size | Equivalente |
|----------------------|-----------|-------------|
| < 20.000 chars | 800 | ~7 páginas |
| < 100.000 chars | 1.000 | ~33 páginas |
| < 300.000 chars | 1.200 | ~100 páginas |
| ≥ 300.000 chars | 1.500 | > 100 páginas |

Un documento de 170 páginas (~510.000 chars) usará `chunk_size: 1500` automáticamente.

### Formato de la cabecera RAG

Para la mejor calidad posible, añade una cabecera a tu documento `.md` o `.txt`:

```markdown
# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: nombre-unico-del-documento

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Descripción concisa del contenido. Máx 500 chars. El modelo usa esto para entender de qué trata el documento."
tags: [tag1, tag2, tag3]
chunk_size: 1200
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Autor"
expires: null
---

[Contenido del documento aquí...]
```

### Campos de la cabecera

| Campo | Obligatorio | Valores | Descripción |
|-------|------------|---------|-------------|
| `id` | Sí | texto único | Identificador del documento |
| `abstract` | Sí | texto (máx 500) | Resumen para el modelo |
| `tags` | Sí | [lista] | Palabras clave de búsqueda |
| `chunk_size` | Sí | 400–2000 | Tamaño de los fragmentos (800 = doc normal, 1500 = doc grande) |
| `priority` | Sí | P0–P3 | P0 = máxima prioridad, P3 = baja |
| `lang` | No | ca/es/en/multi | Idioma del documento |
| `type` | No | docs/tutorial/api/faq/notes | Tipo |
| `collection` | No | user_knowledge | Dónde se indexa |

### Prioridades recomendadas

- **P0**: Documentación crítica (especificaciones, contratos)
- **P1**: Documentación importante (guías, tutoriales)
- **P2**: Notas generales (por defecto para uploads sin cabecera)
- **P3**: Material de referencia secundario

### Ejemplo para un informe de 170 páginas

```markdown
# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: informe-INF-2026-00007

abstract: "Informe técnico INF-2026-00007. Análisis de rendimiento del sistema NAT7 para el Q1 2026. Incluye métricas, conclusiones y recomendaciones."
tags: [informe, NAT7, rendimiento, Q1-2026, análisis]
chunk_size: 1500
priority: P1

lang: es
type: docs
collection: user_knowledge
---

[Contenido del informe...]
```

---

## Gestión de documentos

NEXE puede indexar documentos locales para consultarlos con lenguaje natural.

### Indexar conocimiento

```bash
# Indexar un fichero o directorio
./nexe knowledge ingest /path/to/docs/

# Ver estado del conocimiento indexado
./nexe knowledge status

# Formatos soportados: .txt, .md, .pdf
```

### Consultar documentos

Una vez indexados, los documentos se usan automáticamente via RAG en el chat:

```bash
./nexe chat

Tu: ¿Cuál es la arquitectura de NEXE?
Nexe: Según el documento ARCHITECTURE.md, NEXE está
estructurado en tres capas principales...
```

**Nota:** La documentación del sistema (dentro de `knowledge/`) se indexa automáticamente en la colección `nexe_documentation` durante el inicio del servidor.

---

## Uso de la API

NEXE ofrece una API REST compatible con OpenAI para integrarlo con otras herramientas.

### Endpoints principales

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/v1/chat/completions` | POST | Chat completion (compatible OpenAI) |
| `/v1/memory/store` | POST | Guardar en memoria |
| `/v1/memory/search` | POST | Buscar en memoria |
| `/ui/chat` | POST | Chat pipeline UI (sesiones, RAG, streaming) |
| `/ui/upload` | POST | Subir documento a sesión |
| `/docs` | GET | API documentation (Swagger) |

**Importante:** Todos los endpoints requieren autenticación con el header `X-API-Key`.

### Ejemplos con curl

```bash
# Health check
curl http://localhost:9119/health

# Chat completion
curl -X POST http://localhost:9119/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"messages": [{"role": "user", "content": "Hola"}]}'

# Guardar en memoria
curl -X POST http://localhost:9119/v1/memory/store \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"text": "Mi framework favorito es FastAPI"}'
```

### Uso con Python

```python
import requests

BASE_URL = "http://localhost:9119"
API_KEY = "YOUR_API_KEY"  # NEXE_PRIMARY_API_KEY del .env

def chat(message):
    r = requests.post(f"{BASE_URL}/v1/chat/completions",
        headers={"X-API-Key": API_KEY},
        json={"messages": [{"role": "user", "content": message}]})
    return r.json()["choices"][0]["message"]["content"]

def guardar_memoria(text):
    r = requests.post(f"{BASE_URL}/v1/memory/store",
        headers={"X-API-Key": API_KEY},
        json={"text": text})
    return r.json()
```

---

## Web UI

NEXE incluye una interfaz web completa accesible desde el navegador.

### Acceder a la Web UI

1. Inicia el servidor: `./nexe go`
2. Abre el navegador en: `http://localhost:9119/ui`
3. Aparecerá una **pantalla de login** — introduce tu API key

La API key está en `.env` → `NEXE_PRIMARY_API_KEY`.

**Acceso externo (Tailscale):** usa la misma clave, cambiando `localhost` por la IP de Tailscale.

### Funcionalidades de la Web UI

- Chat interactivo con streaming y razonamiento (`<think>` blocks)
- Historial de conversaciones persistente entre sesiones
- Memoria automática: cada mensaje (≥8 chars) se guarda en Qdrant
- Subida de documentos (.txt, .md, .pdf) para consulta directa en el chat
- El CLI y la Web UI comparten exactamente el mismo pipeline y memoria

---

## Casos de uso prácticos

### 1. Asistente personal con memoria

```bash
./nexe chat

Tu: /save Mi nombre es Jordi y trabajo en desarrollo de IA
Tu: /save Mis proyectos son NEXE y NAT7
Tu: ¿Quién soy yo?
Nexe: Eres Jordi, trabajas en desarrollo de IA
y tus proyectos son NEXE y NAT7...
```

### 2. Analizar un informe grande

```bash
./nexe chat

Tu: /upload /ruta/Informe_Q1_2026.pdf
📎 Subiendo Informe_Q1_2026.pdf...
✅ Indexado (87 partes). Ahora puedes hacer preguntas.

Tu: ¿Cuáles son las conclusiones principales?
Nexe: Según el informe, las tres conclusiones principales son...

Tu: ¿Qué recomienda para el Q2?
Nexe: El documento recomienda...
```

### 3. Base de conocimiento de proyecto

```bash
# Indexar la documentación del proyecto
./nexe knowledge ingest ./mi-proyecto/docs/

./nexe chat
Tu: ¿Cómo funciona el sistema de autenticación?
Nexe: Según auth.md, el sistema usa...
```

### 4. Comparar dos documentos

```bash
./nexe chat

Tu: /upload contrato_v1.pdf
✅ Indexado (12 partes).
Tu: resume los puntos clave del contrato v1

Tu: /upload contrato_v2.pdf
✅ Indexado (14 partes).
Tu: resume los puntos clave del contrato v2

Tu: ¿cuáles son las diferencias principales entre los dos contratos?
Nexe: Comparando ambos documentos... [busca en RAG los dos]
```

---

## Consejos y buenas prácticas

### Rendimiento

1. **Elige el modelo adecuado:**
   - Modelos pequeños (2-4GB): Rápidos, menos precisos
   - Modelos medianos (7-8B): Buen equilibrio
   - Modelos grandes (32B+): Lentos, muy precisos

2. **Usa el backend correcto:**
   - Apple Silicon → MLX (el más rápido)
   - Intel Mac → llama.cpp con Metal
   - Linux/Win → llama.cpp u Ollama

### Memoria RAG

1. **Para documentos importantes, añade cabecera RAG** antes de subirlos.
2. **Para docs sin cabecera**, el sistema genera metadatos con LLM automáticamente.
3. **Haz la pregunta justo después del `/upload`** para máximo contexto.
4. **`clear` no borra el RAG** — solo reinicia el historial de conversación.

### Seguridad

1. Por defecto, NEXE escucha solo en localhost (127.0.0.1:9119)
2. No indexes ficheros con secretos (.env, claves, etc.)
3. La memoria se guarda sin encriptar

---

## Siguientes pasos

1. **ARCHITECTURE.md** - Entiende cómo funciona internamente
2. **RAG.md** - Profundiza en el sistema de memoria
3. **API.md** - Referencia completa de la API
4. **PLUGINS.md** - Aprende sobre el sistema de plugins
5. **LIMITATIONS.md** - Conoce las limitaciones actuales

**¡Experimenta!** NEXE es un proyecto de aprendizaje. Prueba cosas, rómpelas, aprende.
