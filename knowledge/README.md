# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Visió general de NEXE 0.8, servidor IA local amb memòria persistent. Cobreix backends (MLX, llama.cpp, Ollama), funcionalitats, arquitectura, models disponibles, casos d'ús i roadmap. Projecte educatiu de Jordi Goy."
tags: [overview, nexe, backends, rag, memory, arquitectura, roadmap, models, instal·lació]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# NEXE 0.8 - Servidor IA Local amb Memòria

**Versió:** 0.8.0
**Port per defecte:** 9119
**Autor:** Jordi Goy
**Llicència:** Apache 2.0

## Què és NEXE?

NEXE és un **projecte personal d'aprenentatge** (learning by doing) que explora com construir un servidor d'Intel·ligència Artificial que funciona completament en local, amb una característica diferencial: **memòria persistent integrada** mitjançant RAG (Retrieval-Augmented Generation).

**Important:** No és un producte acabat ni intenta competir amb eines madures com ChatGPT, Claude, Ollama o LM Studio. És un experiment per aprendre sobre:
- Sistemes RAG i memòria vectorial
- Integració de diferents backends LLM
- Arquitectura modular amb plugins
- APIs REST i servidors amb FastAPI
- Gestió d'embeddings i cerca semàntica

## Per què NEXE si ja existeix Ollama/LM Studio?

NEXE **no substitueix** Ollama, LM Studio o similars. De fet, pot usar Ollama com a backend!

**Backends disponibles:**
1. **MLX** - Natiu per Apple Silicon (mlx-community)
2. **llama.cpp** - Universal, amb acceleració Metal a Mac
3. **Ollama** - Bridge a Ollama si ja el tens instal·lat

**Backends futurs considerats:**
- LM Studio bridge
- vLLM per inferència optimitzada
- Altres engines segons necesitat

**Què aporta NEXE?**
- Una **capa RAG experimental** sobre aquests backends
- Sistema de **memòria persistent** entre converses
- API unificada per canviar de backend fàcilment
- Aprendre construint un sistema complet
- [Futur] Experimentar amb integració Claude Code + RAG local

## Estat del projecte

### ✅ Què funciona (testat)

**Plataforma:**
- macOS (Apple Silicon i Intel) - Única plataforma provada

**Backends LLM:**
- MLX backend per Apple Silicon
- llama.cpp amb Metal
- Bridge a Ollama

**Funcionalitats:**
- Sistema RAG amb Qdrant (3 col·leccions especialitzades)
- API REST parcialment compatible OpenAI (/v1/chat/completions)
- CLI interactiu (`./nexe`) amb subcomandes
- Web UI bàsica experimental
- Sistema de seguretat (dual-key auth, rate limiting, sanitització)
- Indexació de documents (knowledge ingest)
- Memòria persistent (768-dim embeddings)

### ⚠️ Què és teòric (codi implementat però NO testat)

- **Raspberry Pi** - L'instal·lador té detecció però mai provat en RPi real
- **Linux x86_64** - Hauria de funcionar amb llama.cpp, NO testat
- **Windows** - Teòricament possible amb llama.cpp, NO testat

### 🔨 Què està en desenvolupament o pendent

- **claude_code_module** (v0.9) - Integració experimental amb Claude Code per usar RAG local
- **LM Studio bridge** - Integració amb LM Studio com a backend alternatiu
- **Web UI avançada** - La UI actual és molt bàsica
- **Gestió avançada de documents** - Millor indexació, metadata, etc.

## Instal·lació ràpida

**Requisits mínims:**
- macOS 12+ (recomanat: macOS 14+ amb Apple Silicon)
- Python 3.9+ (recomanat: 3.11+)
- 8 GB RAM (recomanat: 16+ GB)
- 10 GB espai lliure en disc

**Instal·lació guiada:**

```bash
cd server-nexe
python3 install_nexe.py
```

L'instal·lador interactiu et guiarà per:
1. Detectar el teu hardware (CPU, RAM, GPU)
2. Seleccionar el backend adequat (MLX, llama.cpp o Ollama)
3. Triar un model LLM segons la teva RAM
4. Configurar el sistema
5. Iniciar el servidor automàticament

## Començament ràpid

### Iniciar el servidor

```bash
./nexe go
```

El servidor s'iniciarà al port 9119:
- API: `http://localhost:9119`
- Web UI: `http://localhost:9119/ui`
- Health check: `http://localhost:9119/health`
- Documentació API: `http://localhost:9119/docs`

**Nota:** L'API requereix autenticació amb `X-API-Key` header (configurat a `.env` com `NEXE_PRIMARY_API_KEY`).

### Chat interactiu

```bash
# Chat simple
./nexe chat

# Chat amb memòria RAG activada
./nexe chat --rag
```

### Gestió de memòria

```bash
# Guardar informació a la memòria
./nexe memory store "La capital de Catalunya és Barcelona"

# Recuperar de la memòria
./nexe memory recall "capital Catalunya"

# Estat del sistema
./nexe status

# Estadístiques de memòria
./nexe memory stats
```

## Arquitectura bàsica

```
server-nexe/
├── core/              # Servidor FastAPI + endpoints + CLI
│   ├── endpoints/     # API REST
│   ├── cli/           # Comandes CLI
│   ├── server/        # Factory, lifespan
│   └── loader/        # Càrrega de models
├── plugins/           # Sistema de plugins (backends modulars)
│   ├── mlx_module/
│   ├── llama_cpp_module/
│   ├── ollama_module/
│   ├── security/
│   └── web_ui_module/
├── memory/            # Sistema RAG (Qdrant + SQLite + embeddings)
├── knowledge/         # Documents auto-ingestats (aquesta carpeta!)
├── personality/       # Personalitat i comportament de l'IA
└── nexe               # Executable CLI principal
```

**Flux bàsic:**
```
Usuari → CLI/API → Core → Plugin (MLX/llama.cpp/Ollama) → Model LLM
                     ↓
                   Memory (RAG) → Qdrant → Context augmentat
```

## Models disponibles

L'instal·lador ofereix diversos models segons la teva RAM disponible:

### Models petits (8GB RAM)
- **Phi-3.5 Mini** (2.4 GB) - Microsoft, ràpid, multilingüe
- **Salamandra 2B** (1.5 GB) - BSC/AINA, optimitzat per català i llengües ibèriques

### Models mitjans (12-16GB RAM)
- **Mistral 7B** (4.1 GB) - Mistral AI, bon equilibri qualitat/velocitat
- **Salamandra 7B** (4.9 GB) - BSC/AINA, excel·lent per català
- **Llama 3.1 8B** (4.7 GB) - Meta, molt popular, alta qualitat

### Models grans (32GB+ RAM)
- **Mixtral 8x7B** (26 GB) - Mistral AI, model MoE (Mixture of Experts)
- **Llama 3.1 70B** (40 GB) - Meta, qualitat professional

**Nota:** Els models catalans (Salamandra) són especialment interessants per aquest projecte fet a Catalunya.

## Stack tecnològic

| Component | Tecnologia | Versió |
|-----------|------------|--------|
| Backend | FastAPI | 0.104+ |
| Python | CPython | 3.9+ |
| Servidor LLM | MLX / llama.cpp / Ollama | - |
| Base de dades vectorial | Qdrant | Latest |
| Base de dades relacional | SQLite | 3 |
| Embeddings | Ollama (nomic-embed-text) + sentence-transformers | Latest |
| CLI | Click + Rich | - |
| API | Parcialment compatible OpenAI | v1 |
| Autenticació | X-API-Key (dual-key rotation) | - |

## Casos d'ús experimentals

### 1. Assistent personal amb memòria
NEXE pot recordar informació entre sessions: projectes, preferències, context personal.

### 2. Base de coneixement privada
Indexa documents locals (MD, PDF, TXT) i consulta'ls en llenguatge natural sense enviar-los al cloud.

### 3. Desenvolupament amb IA
Usa models locals per coding, experimentació, sense dependre de serveis externs.

### 4. Experimentació amb LLMs
Prova diferents models i backends, compara resultats, aprèn com funcionen.

### 5. [Futur experimental] Claude Code amb RAG
Quan s'implementi el claude_code_module, es podrà experimentar amb Claude Code usant memòria local.

## Filosofia del projecte

NEXE **no intenta competir** amb ChatGPT, Claude, o altres assistents professionals.

**L'objectiu és aprendre i demostrar que:**

1. Una IA útil amb memòria persistent és possible en local
2. La privacitat total és possible (zero dades surten del teu Mac)
3. Els models locals poden cobrir molts casos d'ús quotidians
4. L'arquitectura modular permet experimentar amb diferents backends
5. El codi obert permet entendre com funciona tot plegat

**És un projecte educatiu** que pot ser útil per:
- Aprendre sobre RAG i sistemes d'IA
- Tenir un assistent local per tasques bàsiques
- Experimentar amb models sense costos d'API
- Mantenir privacitat absoluta de les converses

## Limitacions actuals

### Tècniques
- **Només testat en macOS** (malgrat tenir codi multi-plataforma)
- **Els models locals són menys capaços** que GPT-4, Claude Opus, etc.
- **El RAG requereix temps** d'indexació per volums grans de dades
- **Qualitat variable** segons el model seleccionat
- **Consum de RAM** important amb models grans

### Funcionals
- **Web UI molt bàsica** (no és prioritat ara)
- **claude_code_module no implementat** encara
- **No hi ha sync multi-dispositiu**
- **Gestió de documents simple** (no OCR, no parsing avançat)
- **No hi ha fine-tuning** de models
- **API parcialment compatible OpenAI** (falta /v1/embeddings, /v1/models)
- **CLI limitat** (comandes bàsiques: go, status, chat, memory, knowledge)

### Experiència
- És un projecte **experimental i en evolució**
- Pot tenir bugs i comportaments inesperats
- No hi ha suport professional ni SLA
- La documentació està en construcció

## Roadmap (flexible)

| Versió | Objectiu | Estat | Data aprox. |
|--------|----------|-------|-------------|
| 0.8 | Base + RAG + 3 backends | ✅ | Completat |
| 0.9 | claude_code_module experimental | 🔨 | Febrer 2026 |
| 1.0 | Demo pública, docs completes | 📅 | Març 2026 |
| 1.x | LM Studio, millores RAG | 💡 | TBD |

**Nota:** Les dates són orientatives. És un projecte personal fet en temps lliure.

## Recursos i documentació

**En aquesta carpeta (knowledge/):**
- **INSTALLATION.md** - Guia d'instal·lació detallada
- **USAGE.md** - Exemples d'ús i casos pràctics
- **ARCHITECTURE.md** - Arquitectura tècnica detallada
- **RAG.md** - Com funciona el sistema de memòria
- **PLUGINS.md** - Sistema de plugins i com crear-ne
- **API.md** - Referència completa de l'API REST
- **SECURITY.md** - Sistema de seguretat i autenticació
- **LIMITATIONS.md** - Limitacions tècniques i casos no suportats

**Web:**
- **Autor:** Jordi Goy - [jgoy.net](https://jgoy.net)

## Començar a explorar

Després de llegir aquest README, el flux recomanat és:

1. **INSTALLATION.md** - Instal·la el sistema
2. **USAGE.md** - Prova les funcionalitats bàsiques
3. **RAG.md** - Entén com funciona la memòria
4. **ARCHITECTURE.md** - Aprofundeix en l'arquitectura
5. **SECURITY.md** - Entén el sistema de seguretat i autenticació
6. **API.md** - Si vols integrar-lo amb altres eines
7. **LIMITATIONS.md** - Per saber què NO pot fer

---

**Nota important:** Aquesta documentació s'auto-ingesta al sistema RAG de NEXE durant la instal·lació. Si preguntes a NEXE sobre si mateix, les seves capacitats o limitacions, usarà aquesta informació per respondre honestament.

**Learning by doing** - Aquest projecte és un experiment d'aprenentatge continu. Errors, millores i evolució són part del procés.
