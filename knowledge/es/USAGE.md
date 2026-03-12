# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guía práctica de uso de NEXE. Inicio y parada del servidor, comandos CLI, chat interactivo, sistema de memoria, gestión de documentos RAG, uso de la API y casos de uso prácticos como asistente personal o base de conocimiento."
tags: [uso, cli, chat, memory, rag, api, web-ui, casos-de-uso]
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
4. [Sistema de memoria (RAG)](#sistema-de-memoria-rag)
5. [Gestión de documentos](#gestión-de-documentos)
6. [Uso de la API](#uso-de-la-api)
7. [Web UI](#web-ui)
8. [Casos de uso prácticos](#casos-de-uso-prácticos)
9. [Consejos y buenas prácticas](#consejos-y-buenas-prácticas)

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
✓ Model: Phi-3.5 Mini
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

**Salida:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEXE Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Servidor: ✓ Actiu (http://localhost:9119)
Backend: MLX
Model: Phi-3.5 Mini (2.4 GB)
RAM en ús: 3.2 GB
Uptime: 2h 15min

Memòria RAG:
  Documents indexats: 15
  Vectors emmagatzemats: 342
  Mida base de dades: 48 MB
```

### Detener el servidor

Si está en primer plano: `Ctrl+C`

**Nota:** No existe un comando `./nexe stop` dedicado. Para detener el servidor en segundo plano, usa `Ctrl+C` o localiza el proceso y mátalo manualmente.

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

### Ayuda específica

```bash
# Ayuda para un comando
./nexe chat --help
./nexe memory --help
```

---

## Chat interactivo

### Chat simple (sin memoria)

```bash
./nexe chat
```

**Ejemplo de sesión:**
```
╭──────────────────────────────────────────╮
│  NEXE Chat - Phi-3.5 Mini               │
│  Escriu 'exit' per sortir               │
╰──────────────────────────────────────────╯

Tu: Hola, qui ets?

NEXE: Hola! Sóc NEXE, un assistent d'IA que funciona
completament en local al teu ordinador. Estic basat
en el model Phi-3.5 Mini. En què et puc ajudar?

Tu: Explica'm què és Python en 2 línies

NEXE: Python és un llenguatge de programació
interpretat, d'alt nivell i de propòsit general,
conegut per la seva sintaxi clara i llegible. És
molt popular per scripting, ciència de dades,
desenvolupament web i automatització.

Tu: exit

Adéu! 👋
```

### Chat con memoria RAG

```bash
./nexe chat --rag
```

Con `--rag` activado, NEXE:
- Consulta la memoria persistente antes de responder
- Usa contexto de los documentos indexados
- Recuerda información de conversaciones anteriores

**Ejemplo:**
```
Tu: Quins són els meus projectes actuals?

NEXE: [Consultant memòria...]

Segons la informació que tinc guardada, estàs
treballant en:
- NEXE 0.8: Servidor IA local amb RAG
- JGOY Quest: Sistema de tracking gamificat

Vols que et doni més detalls d'algun?

Tu: Sí, explica'm més sobre NEXE

NEXE: [Consultant documentació...]

NEXE és un projecte personal d'aprenentatge (learning
by doing) que explora com construir un servidor d'IA
local amb memòria persistent. Actualment està en
versió 0.8 i funciona en macOS amb tres backends...
```

### Opciones del chat

```bash
# Chat con RAG activado
./nexe chat --rag

# Chat con system prompt personalizado
./nexe chat --system "Ets un expert en Python"

# Chat con engine específico (si tienes múltiples backends)
./nexe chat --engine mlx

# Nota: model, temperatura i max_tokens es configuren via .env
# (NEXE_DEFAULT_MODEL, temperatura a server.toml)
```

---

## Sistema de memoria (RAG)

El sistema RAG permite guardar información y recuperarla automáticamente.

### Guardar información

```bash
# Guardar una frase
./nexe memory store "El meu color favorit és el blau"

# Guardar información estructurada
./nexe memory store "Projecte: NEXE - Estat: v0.8 - Plataforma: macOS"
```

### Recuperar de la memoria

```bash
# Buscar/recuperar información
./nexe memory recall "color favorit"

# Resultados:
# [1] El meu color favorit és el blau (similaritat: 0.92)
```

### Limpiar memoria

```bash
# Limpiar memoria antigua (cleanup)
./nexe memory cleanup
```

### Estadísticas de memoria

```bash
./nexe memory stats
```

**Salida:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Estadístiques de Memòria
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total entrades: 342
Mida total: 48.2 MB
Vectors: 342
Col·leccions: 3 (nexe_chat_memory, nexe_documentation, user_knowledge)

Model d'embeddings: nomic-embed-text (Ollama) + fallbacks
Dimensió vectors: 768

Última actualització: fa 2 hores
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

# Formatos soportados:
# - Markdown (.md)
# - Texto plano (.txt)
# - Otros formatos según configuración
```

### Consultar documentos

Una vez indexados, los documentos se usan automáticamente en el chat con `--rag`:

```bash
./nexe chat --rag

Tu: Quina és l'arquitectura de NEXE?

NEXE: Segons el document ARCHITECTURE.md, NEXE està
estructurat en tres capes principals: Core (servidor
FastAPI), Plugins (backends modulars) i Memory
(sistema RAG amb Qdrant)...
```

**Nota:** La documentación del sistema (dentro de `knowledge/`) se indexa automáticamente en la colección `nexe_documentation` durante el inicio del servidor.

---

## Uso de la API

NEXE ofrece una API REST compatible con OpenAI para integrarlo con otras herramientas.

### Endpoints principales

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/info` | GET | Información del sistema |
| `/v1/chat/completions` | POST | Chat completion (compatible OpenAI) |
| `/v1/memory/store` | POST | Guardar en memoria |
| `/v1/memory/search` | POST | Buscar en memoria |
| `/docs` | GET | API documentation (Swagger) |

**Importante:** Todos los endpoints `/v1/*` requieren autenticación con el header `X-API-Key`.

### Ejemplos con curl

#### Health check

```bash
curl http://localhost:9119/health
```

**Respuesta:**
```json
{
  "status": "ok",
  "message": "NEXE server is running",
  "version": "0.8.0",
  "uptime": 7200
}
```

#### Chat completion

```bash
curl -X POST http://localhost:9119/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "model": "phi3",
    "messages": [
      {"role": "user", "content": "Hola, com estàs?"}
    ],
    "temperature": 0.7,
    "max_tokens": 150
  }'
```

**Respuesta:**
```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1706950400,
  "model": "phi3",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hola! Estic bé, gràcies per preguntar. Sóc un assistent d'IA funcionant en local. Com et puc ajudar avui?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 28,
    "total_tokens": 40
  }
}
```

#### Guardar en memoria

```bash
curl -X POST http://localhost:9119/v1/memory/store \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "text": "El meu framework favorit és FastAPI",
    "collection": "user_knowledge",
    "metadata": {"category": "preferències"}
  }'
```

#### Buscar en memoria

```bash
curl -X POST http://localhost:9119/v1/memory/search \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "query": "framework favorit",
    "collection": "user_knowledge",
    "limit": 5
  }'
```

### Uso con Python

```python
import requests

# Configuración
BASE_URL = "http://localhost:9119"
API_KEY = "YOUR_API_KEY"  # Des de .env NEXE_PRIMARY_API_KEY

# Chat
def chat(message):
    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        headers={"X-API-Key": API_KEY},
        json={
            "messages": [{"role": "user", "content": message}],
            "temperature": 0.7
        }
    )
    return response.json()["choices"][0]["message"]["content"]

# Ejemplo
resposta = chat("Explica'm què és Python")
print(resposta)

# Memoria
def guardar_memoria(text, collection="user_knowledge"):
    response = requests.post(
        f"{BASE_URL}/v1/memory/store",
        headers={"X-API-Key": API_KEY},
        json={"text": text, "collection": collection}
    )
    return response.json()

def cercar_memoria(query, collection="user_knowledge"):
    response = requests.post(
        f"{BASE_URL}/v1/memory/search",
        headers={"X-API-Key": API_KEY},
        json={"query": query, "collection": collection, "limit": 3}
    )
    return response.json()

# Ejemplo
guardar_memoria("El meu projecte actual és NEXE")
resultats = cercar_memoria("projecte actual")
print(resultats)
```

### Uso con curl y jq

```bash
# Chat con respuesta formateada
curl -s -X POST http://localhost:9119/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"messages":[{"role":"user","content":"Hola"}]}' \
  | jq -r '.choices[0].message.content'

# Información del sistema
curl -s http://localhost:9119/api/info | jq
```

---

## Web UI

NEXE incluye una interfaz web básica (experimental).

### Acceder a la Web UI

1. Inicia el servidor: `./nexe go`
2. Abre el navegador en: `http://localhost:9119/ui`
3. Aparecerá una **pantalla de login** — introduce tu API key

La API key está en `.env` → `NEXE_PRIMARY_API_KEY`. Para encontrarla:

```bash
grep NEXE_PRIMARY_API_KEY .env
```

La clave se guarda en el `localStorage` del navegador: no hace falta introducirla en cada visita. Para cerrar sesión o cambiar la clave, abre las DevTools → Application → Local Storage → elimina `nexe_api_key`.

**Acceso externo (Tailscale):** usa la misma clave, cambiando `localhost` por la IP de Tailscale: `http://100.x.x.x:9119/ui`

### Funcionalidades de la Web UI

**Disponible:**
- Chat interactivo
- Historial de conversaciones
- Toggle RAG on/off
- Parámetros básicos (temperatura, max_tokens)

**No disponible (todavía):**
- Gestión de documentos
- Visualización de memoria
- Configuración avanzada
- Estadísticas y gráficos

**Nota:** La Web UI es muy básica y no es la prioridad del proyecto. El CLI y la API son más completos.

---

## Casos de uso prácticos

### 1. Asistente personal con memoria

**Objetivo:** Tener un asistente que recuerde información sobre ti.

```bash
# 1. Guardar información personal
./nexe memory store "El meu nom és Jordi"
./nexe memory store "Treballo en desenvolupament d'IA"
./nexe memory store "Els meus projectes són NEXE i JGOY Quest"
./nexe memory store "M'agrada programar en Python i treballar amb FastAPI"

# 2. Usar el chat con memoria
./nexe chat --rag

Tu: Qui sóc jo?
NEXE: Ets Jordi, treballes en desenvolupament d'IA
i els teus projectes actuals són NEXE i JGOY Quest...

Tu: Quin llenguatge faig servir?
NEXE: T'agrada programar en Python i treballes
amb FastAPI...
```

### 2. Base de conocimiento de proyecto

**Objetivo:** Indexar la documentación de tu proyecto.

```bash
# 1. Indexar la documentación
./nexe knowledge ingest ./projecte/docs/

# 2. Consultarla con lenguaje natural
./nexe chat --rag

Tu: Com funciona el sistema d'autenticació?
NEXE: Segons el fitxer auth.md, el sistema usa
dual-key authentication amb X-API-Key header...

Tu: On està el fitxer de configuració?
NEXE: El fitxer de configuració principal està
a personality/server.toml...
```

### 3. Desarrollo asistido

**Objetivo:** Usar NEXE como ayuda con código.

```bash
./nexe chat

Tu: Escriu una funció Python per llegir un fitxer JSON

NEXE: Aquí tens una funció per llegir un fitxer JSON:

\`\`\`python
import json

def llegir_json(fitxer):
    try:
        with open(fitxer, 'r', encoding='utf-8') as f:
            dades = json.load(f)
        return dades
    except FileNotFoundError:
        print(f"Error: El fitxer {fitxer} no existeix")
        return None
    except json.JSONDecodeError:
        print(f"Error: El fitxer {fitxer} no és JSON vàlid")
        return None
\`\`\`

Tu: Com gestiono errors millor?
NEXE: [Explica gestió d'errors en Python...]
```

### 4. Búsqueda semántica en notas

**Objetivo:** Buscar información en tus notas.

```bash
# 1. Indexar notas
./nexe knowledge ingest ~/notes/

# 2. Buscar sin recordar las palabras exactas
./nexe memory recall "on vaig guardar la recepta de pa"

# Encuentra: "Notes de cuina - recepta pa casolà.md"
```

### 5. Experimentación con engines

**Objetivo:** Probar diferentes backends.

```bash
# Prueba con MLX (Apple Silicon)
./nexe chat --engine mlx
Tu: Explica'm què és la relativitat

# Prueba con Ollama
./nexe chat --engine ollama
Tu: Explica'm què és la relativitat

# Nota: El model específic es configura via .env (NEXE_DEFAULT_MODEL)
```

---

## Consejos y buenas prácticas

### Rendimiento

1. **Elige el modelo adecuado:**
   - Modelos pequeños (2-4GB): Rápidos, menos precisos
   - Modelos medianos (7-8B): Buen equilibrio
   - Modelos grandes (70B): Lentos, muy precisos

2. **Usa el backend correcto:**
   - Apple Silicon → MLX (el más rápido)
   - Intel Mac → llama.cpp con Metal
   - Linux/Win → llama.cpp u Ollama

3. **Ajusta la temperatura:**
   - 0.0-0.3: Respuestas precisas, deterministas
   - 0.5-0.7: Equilibrio creatividad/precisión
   - 0.8-1.0: Respuestas creativas, variables

### Memoria RAG

1. **Guarda información estructurada:**
   ```bash
   # Mejor:
   ./nexe memory store "Projecte: NEXE | Versió: 0.8 | Estat: Actiu"

   # Peor:
   ./nexe memory store "nexe està en versió 0.8 i està actiu"
   ```

2. **Usa metadata cuando indexes documentos:**
   ```bash
   ./nexe docs add report.md --tags "important,2026" --category "informes"
   ```

3. **Reindexar cuando actualices documentos:**
   ```bash
   # Reindexar todo el conocimiento
   ./nexe knowledge ingest ./docs/
   ```

4. **Limpia la memoria antigua periódicamente:**
   ```bash
   ./nexe memory cleanup
   ```

### Limitaciones a tener en cuenta

1. **Contexto limitado:**
   - Los modelos locales tienen ventanas de contexto pequeñas (2K-8K tokens)
   - No esperes que recuerden conversaciones muy largas sin RAG

2. **Calidad vs. velocidad:**
   - Los modelos pequeños son rápidos pero menos precisos
   - Los modelos grandes son lentos pero más capaces
   - Elige según la tarea

3. **Consumo de RAM:**
   - Vigila el uso de RAM con modelos grandes
   - Si va lento, cierra otras aplicaciones

4. **Idiomas:**
   - Los modelos multilingües funcionan bien en español
   - Salamandra es mejor para catalán específico
   - Los modelos en inglés pueden mezclar idiomas

### Seguridad

1. **No expongas el puerto públicamente:**
   - Por defecto, NEXE escucha solo en localhost (127.0.0.1:9119)
   - La autenticación es **obligatoria** con X-API-Key (NEXE_PRIMARY_API_KEY en el .env)

2. **Revisa qué indexas:**
   - No indexes ficheros con secretos (.env, claves, etc.)
   - La memoria se guarda sin encriptar

3. **Logs:**
   - Los logs pueden contener información sensible
   - Revísalos antes de compartirlos

---

## Siguientes pasos

Ahora que sabes usar NEXE:

1. **ARCHITECTURE.md** - Entiende cómo funciona internamente
2. **RAG.md** - Profundiza en el sistema de memoria
3. **API.md** - Referencia completa de la API
4. **PLUGINS.md** - Aprende sobre el sistema de plugins
5. **LIMITATIONS.md** - Conoce las limitaciones actuales

**¡Experimenta!** NEXE es un proyecto de aprendizaje. Prueba cosas, rómpelas, aprende.

---

**Nota:** Esta documentación también está indexada en el RAG de NEXE. ¡Puedes preguntarle sobre sí mismo!

```bash
./nexe chat --rag

Tu: Com puc cercar a la memòria?
NEXE: Pots usar la comanda `./nexe memory search "query"`...
```
