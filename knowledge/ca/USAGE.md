# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia pràctica d'ús de NEXE. Inici i parada del servidor, comandes CLI, xat interactiu amb pipeline unificat CLI+UI, sistema de memòria, pujada de documents amb /upload, RAG adaptatiu per mida de document, ús de l'API i casos d'ús pràctics."
tags: [ús, cli, chat, memory, rag, api, web-ui, upload, capçalera-rag, pipeline-unificat]
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
4. [Pujar documents al chat](#pujar-documents-al-chat)
5. [Sistema de memòria (RAG)](#sistema-de-memòria-rag)
6. [Capçaleres RAG per a documents](#capçaleres-rag-per-a-documents)
7. [Gestió de documents](#gestió-de-documents)
8. [Ús de l'API](#ús-de-lapi)
9. [Web UI](#web-ui)
10. [Casos d'ús pràctics](#casos-dús-pràctics)
11. [Consells i bones pràctiques](#consells-i-bones-pràctiques)

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

```bash
./nexe stop              # atura Nexe Server + Qdrant
./nexe stop --force      # sense confirmació
```

Si està en primer pla, també pots usar `Ctrl+C`.

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

El CLI usa exactament el **mateix pipeline que el Web UI**: sessions servidor, memòria automàtica i cerca semàntica activa per defecte. No cal cap flag `--rag`.

### Iniciar el chat

```bash
./nexe chat
```

**Exemple de sessió:**
```
  🚀 Nexe Chat
  Engine: mlx  |  Model: Qwen3-32B-4bit  |  Memòria: ✅ Activa
  ─────────────────────────────────────────
  Commands: /upload <ruta> · /save <text> · /recall <query> · /help
  Type "exit" or Ctrl+C to quit

Tu: Hola, qui ets?
  ⠹ 1.2s
Nexe: Hola! Sóc Nexe, l'assistent expert de Server Nexe.
En què et puc ajudar?

Tu: Quins projectes tinc actius?
  ⠸ 2.8s
Nexe: Segons el que tinc a la memòria, estàs treballant
en NEXE 0.8 i NAT7...
```

El **spinner amb temporitzador** (`⠹ 2.8s`) indica que el sistema està buscant al RAG i carregant el model. Desapareix quan arriba el primer token.

Al final de cada resposta apareix el **temps total** en gris:
```
Nexe: El document tracta de...
  [34.7s]
```

### Comandes dins del chat

| Comanda | Descripció |
|---------|------------|
| `/upload <ruta>` | Puja un document per analitzar |
| `/save <text>` | Guarda informació a la memòria persistent |
| `/recall <query>` | Cerca directa a la memòria |
| `/help` | Mostra totes les comandes |
| `clear` | Reinicia la sessió (nou context, RAG intacte) |
| `exit` / `sortir` | Surt del chat |

### Context de sessió

Dins d'una mateixa sessió de chat, el model **recorda tot el que has dit**. El context es manté fins que fas `clear` o tanques el chat.

- `clear` → nova sessió, historial net. **El RAG no s'esborra**: els documents pujats anteriorment segueixen accessibles per cerca semàntica.
- Tancar el chat i tornar-lo a obrir → nova sessió, però la memòria RAG persisteix entre sessions.

### Opcions de la comanda

```bash
# Engine específic
./nexe chat --engine mlx

# Nota: --rag i --system s'ignoren (el pipeline UI els gestiona sempre)
```

---

## Pujar documents al chat

Pots pujar documents directament al chat CLI i fer-hi preguntes. Funciona igual que arrossegar un fitxer al Web UI.

### Comanda /upload

```bash
# Dins del chat:
Tu: /upload /ruta/al/fitxer.pdf
📎 Pujant fitxer.pdf...
✅ fitxer.pdf indexat (24 parts). Ara pots fer preguntes sobre el document.

Tu: fes-me un resum executiu
Nexe: El document tracta de...
```

**Rutes amb espais:** usa `\ ` per escapar els espais:
```
/upload /Users/jordi/Documents/Que\ es\ NAT/QUE_ES_NAT.md
```

**Pregunta directa després del upload:** pots afegir la pregunta al mateix comando:
```
Tu: /upload /ruta/NEGOCI.md fes-me un resum executiu
📎 Pujant NEGOCI.md...
✅ NEGOCI.md indexat (28 parts).
Nexe: El document és un pla de negoci que...
```

### Formats suportats

`.pdf`, `.txt`, `.md`, `.markdown` i altres formats de text.

### Com funciona la pujada

1. **Slot de sessió**: el document s'adjunta a la sessió actual. El primer missatge el rep com a context complet (fins a 50 parts).
2. **Indexació RAG**: tots els chunks es guarden a `nexe_web_ui`. Persisteixen entre sessions i es recuperen per cerca semàntica.

### Múltiples documents

```
/upload doc1.pdf          → indexat + adjuntat a sessió
Tu: resum de doc1?        → rep doc1 com a context complet
/upload doc2.pdf          → indexat + sobreescriu slot de sessió
Tu: resum de doc2?        → rep doc2 com a context complet
Tu: compara doc1 i doc2   → ambdós accessibles via RAG semàntic
```

**Recomanació:** fes la pregunta principal **just després de cada `/upload`** per aprofitar el context complet. Les preguntes posteriors accedeixen via RAG.

---

## Sistema de memòria (RAG)

NEXE guarda automàticament cada missatge de l'usuari a Qdrant (`nexe_web_ui`). Abans de generar cada resposta, fa una cerca semàntica per recuperar el context rellevant.

### Com funciona l'auto-save

**Cada missatge que envies** es guarda automàticament si:
- Té 8 o més caràcters
- No és una salutació pura ("hola", "gràcies", "ok"...)
- No és duplicat d'alguna cosa ja guardada (similaritat > 80%)

```
Tu: "Em dic Aran i treballo a NatSystem"
  → guardat automàticament a Qdrant

Tu (nova sessió): "Saps com em dic?"
  → cerca semàntica troba "Em dic Aran..."
  → model respon: "Et dius Aran"
```

La icona **bookmark verd** als stats de cada missatge indica que s'ha guardat.

### Guardar explícitament

Pots forçar un save amb frases com:
- "Em dic Aran, **pots guardar-ho**?"
- "Treballo a NatSystem, **guarda-ho**"
- "Prefereixo Python, **ho pots guardar a la memòria**?"

### Recuperar de la memòria (CLI)

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
Col·leccions: 3 (nexe_web_ui, nexe_documentation, user_knowledge)

Model d'embeddings: nomic-embed-text (Ollama) + fallbacks
Dimensió vectors: 768

Última actualització: fa 2 hores
```

### Precisió RAG (threshold)

Quan el sistema busca a la memòria, filtra els resultats per **similitud semàntica**. El llindar de precisió controla quant ha de semblar-se un record a la teva pregunta per ser inclòs al context.

**Valor per defecte: 0.6**

| Valor | Comportament |
|-------|-------------|
| 0.3–0.5 | Ampli — inclou més context, risc d'al·lucinació |
| 0.6 | Equilibrat (recomanat) |
| 0.7–0.8 | Precís — menys context, respostes més curtes |
| 0.9+ | Molt estricte — quasi no recupera res |

**Web UI:** slider "Precisió RAG" al sidebar (sota el model). El valor es guarda entre sessions al `localStorage`. Passa `ⓘ` per veure l'explicació.

**CLI:** el threshold s'aplica automàticament amb el valor per defecte (0.6). No configurable en temps real des de la CLI.

> **Consell:** si el model al·lucina o barreja informació de documents no relacionats, puja el threshold a 0.7–0.75.

---

## Capçaleres RAG per a documents

La **capçalera RAG** és la clau per a una cerca semàntica de qualitat. Quan un document té capçalera, el sistema usa `chunk_size`, `abstract` i `tags` per indexar-lo de manera òptima. Sense capçalera, el sistema en genera una d'automàtica.

### Chunk size adaptatiu (sense capçalera)

Quan puges un document sense capçalera (via `/upload` o Web UI), el sistema tria automàticament el `chunk_size` segons la mida:

| Mida del document | Chunk size | Equivalent |
|-------------------|-----------|------------|
| < 20.000 chars | 800 | ~7 pàgines |
| < 100.000 chars | 1.000 | ~33 pàgines |
| < 300.000 chars | 1.200 | ~100 pàgines |
| ≥ 300.000 chars | 1.500 | > 100 pàgines |

Un document de 170 pàgines (~510.000 chars) usarà `chunk_size: 1500` automàticament.

### Format de la capçalera RAG

Per a la millor qualitat possible, afegeix una capçalera al teu document `.md` o `.txt`:

```markdown
# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: nom-unic-del-document

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Descripció concisa del contingut. Màx 500 chars. El model usa això per entendre de quà tracta el document."
tags: [tag1, tag2, tag3]
chunk_size: 1200
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Autor"
expires: null
---

[Contingut del document aquí...]
```

### Camps de la capçalera

| Camp | Obligatori | Valors | Descripció |
|------|-----------|--------|------------|
| `id` | Sí | text únic | Identificador del document |
| `abstract` | Sí | text (màx 500) | Resum per al model |
| `tags` | Sí | [llista] | Paraules clau de cerca |
| `chunk_size` | Sí | 400–2000 | Mida dels fragments (800 = doc normal, 1500 = doc gran) |
| `priority` | Sí | P0–P3 | P0 = màxima prioritat, P3 = baixa |
| `lang` | No | ca/es/en/multi | Idioma del document |
| `type` | No | docs/tutorial/api/faq/notes | Tipus |
| `collection` | No | user_knowledge | On s'indexa |

### Prioritats recomanades

- **P0**: Documentació crítica (especificacions, contractes)
- **P1**: Documentació important (guies, tutorials)
- **P2**: Notes generals (per defecte per uploads sense capçalera)
- **P3**: Material de referència secundari

### Exemple per a un informe de 170 pàgines

```markdown
# === METADATA RAG ===
versio: "1.0"
data: 2026-03-13
id: informe-INF-2026-00007

abstract: "Informe tècnic INF-2026-00007. Anàlisi de rendiment del sistema NAT7 per al Q1 2026. Inclou mètriques, conclusions i recomanacions."
tags: [informe, NAT7, rendiment, Q1-2026, anàlisi]
chunk_size: 1500
priority: P1

lang: ca
type: docs
collection: user_knowledge
---

[Contingut de l'informe...]
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
# - Text pla (.txt, .text)
# - PDF (.pdf)
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

NEXE inclou una interfície web completa accessible des del navegador.

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

- Chat interactiu amb streaming i raonament (`<think>` blocks)
- Historial de converses persistent entre sessions
- Memòria automàtica: cada missatge (≥8 chars) es guarda a Qdrant
- **Icona bookmark verda** quan un missatge s'ha desat a la memòria
- Puja documents (.txt, .md, .pdf) per consultar-los directament al xat
- Estadístiques per missatge: tokens, velocitat, model
- Responsive i accessible des de mòbil (Tailscale)

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
