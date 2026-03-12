# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia pràctica d'ús de NEXE. Inici i parada del servidor, comandes CLI, xat interactiu, sistema de memòria, gestió de documents RAG, ús de l'API i casos d'ús pràctics com assistent personal o base de coneixement."
tags: [ús, cli, chat, memory, rag, api, web-ui, casos-dús]
chunk_size: 900
priority: P1

# === OPCIONAL ===
lang: ca
type: tutorial
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Guia d'Ús - NEXE 0.8

Aquesta guia t'ensenya a usar NEXE amb exemples pràctics. Assumeix que ja tens NEXE instal·lat (si no, consulta **INSTALLATION.md**).

## Índex

1. [Iniciar i aturar el servidor](#iniciar-i-aturar-el-servidor)
2. [CLI bàsic](#cli-bàsic)
3. [Chat interactiu](#chat-interactiu)
4. [Sistema de memòria (RAG)](#sistema-de-memòria-rag)
5. [Gestió de documents](#gestió-de-documents)
6. [Ús de l'API](#ús-de-lapi)
7. [Web UI](#web-ui)
8. [Casos d'ús pràctics](#casos-dús-pràctics)
9. [Consells i bones pràctiques](#consells-i-bones-pràctiques)

---

## Iniciar i aturar el servidor

### Iniciar el servidor

```bash
cd server-nexe
./nexe go
```

**Sortida esperada:**
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

### Verificar estat

```bash
./nexe status
```

**Sortida:**
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

### Aturar el servidor

Si està en primer pla: `Ctrl+C`

**Nota:** No hi ha comanda `./nexe stop` dedicada. Per aturar el servidor en segon pla, usa `Ctrl+C` o localitza el procés i mata'l manualment.

---

## CLI bàsic

### Comandes disponibles

```bash
./nexe --help
```

**Comandes principals:**

| Comanda | Descripció |
|---------|------------|
| `go` | Inicia el servidor |
| `status` | Estat del sistema |
| `chat` | Chat interactiu |
| `memory` | Gestió de memòria (store, recall, stats, cleanup) |
| `knowledge` | Gestió de documents (ingest, status) |
| `logs` | Veure logs |
| `--version` | Versió de NEXE |

### Ajuda específica

```bash
# Ajuda per una comanda
./nexe chat --help
./nexe memory --help
```

---

## Chat interactiu

### Chat simple (sense memòria)

```bash
./nexe chat
```

**Exemple de sessió:**
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

### Chat amb memòria RAG

```bash
./nexe chat --rag
```

Amb `--rag` activat, NEXE:
- Consulta la memòria persistent abans de respondre
- Usa context dels documents indexats
- Recorda informació de converses anteriors

**Exemple:**
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

### Opcions del chat

```bash
# Chat amb RAG activat
./nexe chat --rag

# Chat amb system prompt personalitzat
./nexe chat --system "Ets un expert en Python"

# Chat amb engine específic (si tens múltiples backends)
./nexe chat --engine mlx

# Nota: model, temperatura i max_tokens es configuren via .env
# (NEXE_DEFAULT_MODEL, temperatura a server.toml)
```

---

## Sistema de memòria (RAG)

El sistema RAG permet guardar informació i recuperar-la automàticament.

### Guardar informació

```bash
# Guardar una frase
./nexe memory store "El meu color favorit és el blau"

# Guardar informació estructurada
./nexe memory store "Projecte: NEXE - Estat: v0.8 - Plataforma: macOS"
```

### Recuperar de la memòria

```bash
# Cercar/recuperar informació
./nexe memory recall "color favorit"

# Resultats:
# [1] El meu color favorit és el blau (similaritat: 0.92)
```

### Netejar memòria

```bash
# Netejar memòria antiga (cleanup)
./nexe memory cleanup
```

### Estadístiques de memòria

```bash
./nexe memory stats
```

**Sortida:**
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

## Gestió de documents

NEXE pot indexar documents locals per consultar-los amb llenguatge natural.

### Indexar coneixement

```bash
# Indexar un fitxer o directori
./nexe knowledge ingest /path/to/docs/

# Veure estat del coneixement indexat
./nexe knowledge status

# Formats suportats:
# - Markdown (.md)
# - Text pla (.txt)
# - Altres formats segons configuració
```

### Consultar documents

Un cop indexats, els documents s'usen automàticament en chat amb `--rag`:

```bash
./nexe chat --rag

Tu: Quina és l'arquitectura de NEXE?

NEXE: Segons el document ARCHITECTURE.md, NEXE està
estructurat en tres capes principals: Core (servidor
FastAPI), Plugins (backends modulars) i Memory
(sistema RAG amb Qdrant)...
```

**Nota:** La documentació del sistema (dins de `knowledge/`) s'indexa automàticament a la col·lecció `nexe_documentation` durant l'inici del servidor.

---

## Ús de l'API

NEXE ofereix una API REST compatible amb OpenAI per integrar-lo amb altres eines.

### Endpoints principals

| Endpoint | Mètode | Descripció |
|----------|--------|------------|
| `/health` | GET | Health check |
| `/api/info` | GET | Informació del sistema |
| `/v1/chat/completions` | POST | Chat completion (compatible OpenAI) |
| `/v1/memory/store` | POST | Guardar a memòria |
| `/v1/memory/search` | POST | Cercar a memòria |
| `/docs` | GET | API documentation (Swagger) |

**Important:** Tots els endpoints `/v1/*` requereixen autenticació amb header `X-API-Key`.

### Exemples amb curl

#### Health check

```bash
curl http://localhost:9119/health
```

**Resposta:**
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

**Resposta:**
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

#### Guardar a memòria

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

#### Cercar a memòria

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

### Ús amb Python

```python
import requests

# Configuració
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

# Exemple
resposta = chat("Explica'm què és Python")
print(resposta)

# Memòria
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

# Exemple
guardar_memoria("El meu projecte actual és NEXE")
resultats = cercar_memoria("projecte actual")
print(resultats)
```

### Ús amb curl i jq

```bash
# Chat amb resposta formatada
curl -s -X POST http://localhost:9119/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"messages":[{"role":"user","content":"Hola"}]}' \
  | jq -r '.choices[0].message.content'

# Informació del sistema
curl -s http://localhost:9119/api/info | jq
```

---

## Web UI

NEXE inclou una interfície web bàsica (experimental).

### Accedir a la Web UI

1. Inicia el servidor: `./nexe go`
2. Obre el navegador a: `http://localhost:9119/ui`
3. Apareixerà una **pantalla de login** — introdueix la teva API key

La API key és a `.env` → `NEXE_PRIMARY_API_KEY`. Per trobar-la:

```bash
grep NEXE_PRIMARY_API_KEY .env
```

La clau es guarda al `localStorage` del navegador: no cal tornar-la a introduir a cada visita. Si vols tancar la sessió o canviar la clau, obre les DevTools del navegador → Application → Local Storage → elimina `nexe_api_key`.

**Accés extern (Tailscale):** usa la mateixa clau, canviant `localhost` per la IP de Tailscale: `http://100.x.x.x:9119/ui`

### Funcionalitats de la Web UI

**Disponible:**
- Chat interactiu
- Historial de converses
- Toggle RAG on/off
- Paràmetres bàsics (temperatura, max_tokens)

**No disponible (encara):**
- Gestió de documents
- Visualització de memòria
- Configuració avançada
- Estadístiques i gràfics

**Nota:** La Web UI és molt bàsica i no és la prioritat del projecte. El CLI i l'API són més complets.

---

## Casos d'ús pràctics

### 1. Assistent personal amb memòria

**Objectiu:** Tenir un assistent que recordi informació sobre tu.

```bash
# 1. Guardar informació personal
./nexe memory store "El meu nom és Jordi"
./nexe memory store "Treballo en desenvolupament d'IA"
./nexe memory store "Els meus projectes són NEXE i JGOY Quest"
./nexe memory store "M'agrada programar en Python i treballar amb FastAPI"

# 2. Usar el chat amb memòria
./nexe chat --rag

Tu: Qui sóc jo?
NEXE: Ets Jordi, treballes en desenvolupament d'IA
i els teus projectes actuals són NEXE i JGOY Quest...

Tu: Quin llenguatge faig servir?
NEXE: T'agrada programar en Python i treballes
amb FastAPI...
```

### 2. Base de coneixement de projecte

**Objectiu:** Indexar la documentació del teu projecte.

```bash
# 1. Indexar la documentació
./nexe knowledge ingest ./projecte/docs/

# 2. Consultar-la amb llenguatge natural
./nexe chat --rag

Tu: Com funciona el sistema d'autenticació?
NEXE: Segons el fitxer auth.md, el sistema usa
dual-key authentication amb X-API-Key header...

Tu: On està el fitxer de configuració?
NEXE: El fitxer de configuració principal està
a personality/server.toml...
```

### 3. Desenvolupament assistit

**Objectiu:** Usar NEXE per ajuda amb codi.

```bash
./nexe chat

Tu: Escriu una funció Python per llegir un fitxer JSON

NEXE: Aquí tens una funció per llegir un fitxer JSON:

```python
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
```

Tu: Com gestiono errors millor?
NEXE: [Explica gestió d'errors en Python...]
```

### 4. Cerca semàntica en notes

**Objectiu:** Cercar informació en les teves notes.

```bash
# 1. Indexar notes
./nexe knowledge ingest ~/notes/

# 2. Cercar sense recordar paraules exactes
./nexe memory recall "on vaig guardar la recepta de pa"

# Troba: "Notes de cuina - recepta pa casolà.md"
```

### 5. Experimentació amb engines

**Objectiu:** Provar diferents backends.

```bash
# Prova amb MLX (Apple Silicon)
./nexe chat --engine mlx
Tu: Explica'm què és la relativitat

# Prova amb Ollama
./nexe chat --engine ollama
Tu: Explica'm què és la relativitat

# Nota: El model específic es configura via .env (NEXE_DEFAULT_MODEL)
```

---

## Consells i bones pràctiques

### Performance

1. **Tria el model adequat:**
   - Models petits (2-4GB): Ràpids, menys precisos
   - Models mitjans (7-8B): Bon equilibri
   - Models grans (70B): Lents, molt precisos

2. **Usa el backend correcte:**
   - Apple Silicon → MLX (el més ràpid)
   - Intel Mac → llama.cpp amb Metal
   - Linux/Win → llama.cpp o Ollama

3. **Ajusta la temperatura:**
   - 0.0-0.3: Respostes precises, deterministes
   - 0.5-0.7: Equilibri creativitat/precisió
   - 0.8-1.0: Respostes creatives, variables

### Memòria RAG

1. **Guarda informació estructurada:**
   ```bash
   # Millor:
   ./nexe memory store "Projecte: NEXE | Versió: 0.8 | Estat: Actiu"

   # Pitjor:
   ./nexe memory store "nexe està en versió 0.8 i està actiu"
   ```

2. **Usa metadata quan indexis documents:**
   ```bash
   ./nexe docs add report.md --tags "important,2026" --category "informes"
   ```

3. **Reindexar quan actualitzis documents:**
   ```bash
   # Reindexar tot el coneixement
   ./nexe knowledge ingest ./docs/
   ```

4. **Neteja memòria antiga periòdicament:**
   ```bash
   ./nexe memory cleanup
   ```

### Limitacions a tenir en compte

1. **Context limitat:**
   - Els models locals tenen finestres de context petites (2K-8K tokens)
   - No esperis que recordin converses molt llargues sense RAG

2. **Qualitat vs. velocitat:**
   - Models petits són ràpids però menys precisos
   - Models grans són lents però més capaços
   - Tria segons la tasca

3. **Consum de RAM:**
   - Vigila l'ús de RAM amb models grans
   - Si va lent, tanca altres aplicacions

4. **Idiomes:**
   - Models multilingües funcionen bé en català
   - Salamandra és millor per català específic
   - Models anglesos poden barrejar idiomes

### Seguretat

1. **No comparteixis el port públicament:**
   - Per defecte, NEXE escolta només localhost (127.0.0.1:9119)
   - L'autenticació és **obligatòria** amb X-API-Key (NEXE_PRIMARY_API_KEY al .env)

2. **Revisa què indexes:**
   - No indexis fitxers amb secrets (.env, claus, etc.)
   - La memòria es guarda sense encriptar

3. **Logs:**
   - Els logs poden contenir informació sensible
   - Revisa'ls abans de compartir-los

---

## Següents passos

Ara que saps usar NEXE:

1. **ARCHITECTURE.md** - Entén com funciona internament
2. **RAG.md** - Aprofundeix en el sistema de memòria
3. **API.md** - Referència completa de l'API
4. **PLUGINS.md** - Aprèn sobre el sistema de plugins
5. **LIMITATIONS.md** - Coneix les limitacions actuals

**Experimenta!** NEXE és un projecte d'aprenentatge. Prova coses, trenca coses, aprèn.

---

**Nota:** Aquesta documentació també està indexada al RAG de NEXE. Pots preguntar-li sobre si mateix!

```bash
./nexe chat --rag

Tu: Com puc cercar a la memòria?
NEXE: Pots usar la comanda `./nexe memory search "query"`...
```
