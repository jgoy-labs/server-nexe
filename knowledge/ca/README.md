# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-overview
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "server-nexe es un servidor d'IA local amb memoria RAG persistent creat per Jordi Goy. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Funcionalitats: MEM_SAVE, i18n (ca/es/en), aillament de sessions, encriptacio at-rest, thinking toggle. Models per tiers (8GB a 32GB, 16 models 4 tiers), 2 metodes d'instal-lacio (DMG offline 1.2GB, CLI). macOS 14+ Apple Silicon only, Linux parcial."
tags: [overview, server-nexe, backends, rag, memory, mem_save, i18n, models, installation, architecture, ollama, mlx, llama-cpp, encryption, ai-ready, jordi-goy]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# server-nexe 1.0.0-beta — Servidor d'IA local amb memoria persistent

**Versio:** 1.0.0-beta
**Port per defecte:** 9119
**Autor:** Jordi Goy (Barcelona)
**Llicencia:** Apache 2.0
**Plataformes:** macOS 14 Sonoma+ Apple Silicon (M1+) — testejat. Linux x86_64 (parcial).
**Web:** https://server-nexe.org | https://server-nexe.com

## Que es server-nexe

server-nexe es un servidor d'IA local amb memoria persistent via RAG (Retrieval-Augmented Generation). S'executa completament a la maquina de l'usuari. Sense nuvol, sense telemetria, sense crides a APIs externes. Les converses, documents i embeddings no surten mai del dispositiu.

## Intencio de disseny

El que va começar com un learning-by-doing i un monstre d'espagueti gegant va derivar, en diversos refactors, cap a l'objectiu de construir un nucli mínim, agnòstic i modular on la seguretat i la memòria estiguin resoltes a la base — perquè construir a sobre sigui ràpid i còmode — en col·laboració humà-IA. Si s'ha aconseguit, ho ha de dir la comunitat (la IA diu que sí, però què vols que digui 🤪).

NO es npm nexe (un compilador de Node.js). NO es un producte de servidor Windows. NO es un substitut d'Ollama — pot utilitzar Ollama com un dels seus backends.

## Capacitats principals

1. **100% local i privat** — Tota la inferencia, memoria i emmagatzematge passen al dispositiu. Zero dependencia del nuvol.
2. **Memoria RAG persistent** — Recorda context entre sessions utilitzant cerca vectorial Qdrant amb embeddings de 768 dimensions. Tres col·leccions: nexe_documentation (docs del sistema), user_knowledge (documents pujats), personal_memory (memoria de conversa).
3. **Memoria automatica (MEM_SAVE)** — El model extreu fets de les converses automaticament (nom, feina, preferencies) i els guarda a memoria. Zero latencia extra (mateixa crida LLM). Suporta intents de guardar, esborrar i recuperar en 3 idiomes.
4. **Inferencia multi-backend** — MLX (natiu Apple Silicon), llama.cpp (GGUF, universal amb Metal), Ollama (bridge). Mateixa API compatible amb OpenAI, backends intercanviables.
5. **Sistema modular de plugins** — Seguretat, web UI, RAG, cada backend — tot es un plugin amb manifests independents. Auto-descobriment a l'arrencada.
6. **Multilingue (ca/es/en)** — i18n complet: UI, prompts del sistema, etiquetes de context RAG, missatges d'error, instal·lador. El servidor es la font de veritat per a la seleccio d'idioma.
7. **Pujada de documents amb aillament de sessio** — Puja documents via la Web UI. Indexats a user_knowledge amb metadades de session_id. Els documents nomes son visibles dins la sessio on s'han pujat.
8. **Encriptacio at-rest (default `auto`)** — Encriptacio AES-256-GCM per a SQLite (via SQLCipher), sessions de xat (.enc) i text de documents RAG (TextStore). S'activa automaticament si sqlcipher3 esta disponible. Gestio de claus via OS Keyring, variable d'entorn o fitxer. Recentment afegida — encara no provada en batalla en produccio.
9. **Validacio d'input completa** — Tots els endpoints (API i Web UI) tenen rate limiting, validacio d'input (`validate_string_input`) i sanititzacio de context RAG. 6 detectors d'injeccio amb normalitzacio Unicode. 47 patrons de jailbreak.

## Stack tecnologic

| Component | Tecnologia |
|-----------|-----------|
| Llenguatge | Python 3.11+ (3.12 inclos a l'instal·lador) |
| Framework web | FastAPI 0.115+ |
| Base de dades vectorial | Qdrant (binari embegut) |
| Backends LLM | MLX, llama.cpp (llama-cpp-python 0.3.19 pinned), Ollama |
| Embeddings | **fastembed ONNX (paraphrase-multilingual-mpnet-base-v2, 768D) — principal offline** / nomic-embed-text via Ollama (opcional) |
| Dimensions d'embedding | 768 |
| Encriptacio | AES-256-GCM, HKDF-SHA256, SQLCipher (default auto) |
| CLI | Click + Rich |
| API | Compatible amb OpenAI (/v1/chat/completions) |
| Autenticacio | X-API-Key (dual-key amb rotacio) |
| Seguretat | 6 detectors d'injeccio + normalitzacio Unicode, 47 patrons de jailbreak, rate limiting, capcaleres CSP |

## Arquitectura

```
server-nexe/
├── core/                  # Servidor FastAPI, endpoints, CLI, crypto
│   ├── endpoints/         # API REST (chat separat en 8 submoduls)
│   ├── crypto/            # Encriptacio at-rest (AES-256-GCM, SQLCipher)
│   ├── cli/               # Comandes CLI
│   ├── server/            # Patro factory, lifespan
│   ├── ingest/            # Ingestio de documents (docs + knowledge)
│   └── lifespan*.py       # Arrencada/aturada (separat en 4 submoduls)
├── plugins/               # Sistema modular de plugins
│   ├── mlx_module/        # Backend Apple Silicon
│   ├── llama_cpp_module/  # Backend universal GGUF
│   ├── ollama_module/     # Bridge Ollama + auto-arrencada + neteja VRAM
│   ├── security/          # Auth, rate limiting, deteccio d'injeccions
│   └── web_ui_module/     # Interficie web (rutes separades en 6 submoduls)
├── memory/                # Sistema RAG (Qdrant + embeddings + persistencia + TextStore)
├── knowledge/             # Documentacio per a ingestio RAG (ca/es/en)
├── personality/           # Prompts del sistema, module manager, i18n, server.toml
├── installer/             # Wizard SwiftUI, constructor de DMG, app de safata, instal·lador headless
├── storage/               # Dades en temps d'execucio (models, logs, vectors Qdrant)
├── tests/                 # Suite de tests (4842 col·lectades / 4990 totals)
└── nexe                   # Executable CLI principal
```

**Flux de dades:**
```
Usuari -> CLI/API/Web UI -> Auth -> Rate Limit -> Validar Input -> Core -> Plugin -> LLM
                                                    |                           |
                                                    v                           v
                                             Memoria (RAG) -> Qdrant      MEM_SAVE -> Qdrant
                                                    |
                                            _sanitize_rag_context
```

## Documentacio AI-Ready

La base de coneixement (`knowledge/`) esta dissenyada tant per a consum huma com per a IA:
- **Frontmatter YAML estructurat** per a ingestio RAG (chunk_size, tags, priority)
- **13 fitxers tematics** que cobreixen identitat, arquitectura, API, seguretat, testing, casos d'us, etc.
- **Disponible en angles, catala i castella**
- Apunta qualsevol assistent d'IA a aquest repositori i podra entendre l'arquitectura completa, crear plugins o contribuir codi

## Models disponibles (per tiers de RAM)

16 models testejats empiricament, 4 tiers. Cada tier te 2 models recomanats (un per Ollama, un per MLX). Icones: 👁 = visio (imatges), 🧠 = thinking (raonament pas a pas).

### tier_8 (8 GB RAM)
- 👁 🧠 **Gemma 3 4B** — Google DeepMind, 2025. Ollama + MLX. **Recomanat MLX.**
- 👁 🧠 Qwen3.5 4B — Alibaba, 2026. Ollama nomes (MLX requereix torch). **Recomanat Ollama.**
- Qwen3 4B — Alibaba, 2025. Text, Ollama + MLX.

### tier_16 (16 GB RAM)
- 👁 🧠 **Gemma 4 E4B** — Google, 2026. Ollama + MLX. **Recomanat MLX.**
- Salamandra 7B — BSC/AINA, 2025. Ollama + llama.cpp (GGUF). El millor per catala.
- 👁 🧠 Qwen3.5 9B — Alibaba, 2026. Ollama nomes (MLX requereix torch). **Recomanat Ollama.**
- 👁 🧠 Gemma 3 12B — Google DeepMind, 2025. Ollama + MLX.

### tier_24 (24 GB RAM)
- 👁 🧠 **Gemma 4 31B** — Google, 2026. Ollama + MLX. **Recomanat.**
- 🧠 **Qwen3 14B** — Alibaba, 2025. Ollama + MLX. **Recomanat.**
- 🧠 GPT-OSS 20B — OpenAI, 2025. Ollama + MLX. Apache 2.0.

### tier_32 (32 GB RAM)
- 👁 🧠 Qwen3.5 27B — Alibaba, 2026. Ollama nomes (MLX requereix torch).
- 👁 🧠 Gemma 3 27B — Google DeepMind, 2025. MLX + llama.cpp (GGUF).
- 🧠 DeepSeek R1 Distill 32B — DeepSeek, 2025. Ollama + llama.cpp (MLX no suportat: qwen2 arch).
- 👁 🧠 **Gemma 4 31B** — Google, 2026. Ollama + MLX. **Recomanat MLX.**
- 👁 🧠 Qwen3.5 35B-A3B (MoE) — Alibaba, 2026. Ollama nomes.
- **ALIA-40B Instruct** — BSC, 2026. Ollama + llama.cpp (GGUF). 9 idiomes iberics. **Recomanat iberic.**

### Notes sobre compatibilitat backends (verificat 2026-04-16)

- **Familia Qwen3.5 a MLX**: requereix PyTorch i torchvision per al VideoProcessor. Funciona perfectament via Ollama sense dependencies extra. Opcional: `pip install torch torchvision` al venv per desbloquejar MLX (~2 GB). Afecta: Qwen3.5 2B/4B/9B/27B/35B-A3B/122B-A10B.
- **DeepSeek R1 Distill a MLX**: error "Unsupported model: qwen2". Usar Ollama o GGUF via llama.cpp.
- **Gemma 4 E4B a MLX**: pot ser inestable (loops repetitius) en models petits. Funciona be per a visio.
- **Gemma 4 31B a MLX**: requereix descàrrega completa 8-bit (~33 GB, 7 shards). Verificar integritat.
- **ALIA-40B**: 42 GB Q8_0. Verificar integritat despres de descarregar (cas tensor truncat detectat).

Tambe es suporten models personalitzats via Ollama (per nom) o Hugging Face (repositori GGUF).

## Metodes d'instal·lacio

### 1. Instal·lador DMG per a macOS (recomanat)
Wizard natiu SwiftUI amb 6 pantalles: benvinguda, carpeta de desti, seleccio de model (deteccio de maquinari per tiers), confirmacio, progres, finalitzacio. Inclou Python 3.12.

### 2. CLI headless
```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go
```

## Inici rapid

```bash
./nexe go                    # Arrencar servidor -> http://127.0.0.1:9119
./nexe chat                  # Xat interactiu per CLI
./nexe chat --rag            # Xat amb memoria RAG
./nexe memory store "text"   # Guardar a memoria
./nexe memory recall "query" # Recuperar de memoria
./nexe status                # Estat del sistema
./nexe knowledge ingest      # Indexar documents
./nexe encryption status     # Comprovar estat d'encriptacio
```

Web UI: `http://127.0.0.1:9119/ui`
Docs de l'API: `http://127.0.0.1:9119/docs`
Health check: `http://127.0.0.1:9119/health`

Autenticacio requerida: capcalera `X-API-Key` amb el valor de `.env` (`NEXE_PRIMARY_API_KEY`).

## Suport de plataformes

| Plataforma | Estat |
|----------|--------|
| macOS 14 Sonoma+ Apple Silicon (M1+) | Testejat (tots 3 backends) |
| macOS 13 Ventura | **NO suportat** (eliminat a v0.9.9) |
| macOS Intel | **NO suportat** (eliminat a v0.9.9 — wheels arm64-only) |
| Linux x86_64 | Parcial (tests unitaris passen, CI verd, no testejat en produccio) |
| Windows | Encara no suportat |

## Limitacions actuals

- Els models locals son menys capacos que GPT-4, Claude, etc. — la contrapartida es la privacitat.
- RAG requereix temps d'indexacio inicial. Memoria buida = sense context RAG.
- Sense sincronitzacio multi-dispositiu.
- Sense fine-tuning de models.
- L'API es parcialment compatible amb OpenAI (falten /v1/embeddings, /v1/models).
- L'encriptacio at-rest es `auto` per defecte (s'activa si sqlcipher3 disponible) — nova, encara no provada en batalla.
- Projecte d'un sol desenvolupador amb auditories assistides per IA, sense auditoria formal.

## Documentacio relacionada

Altres documents de coneixement en aquesta carpeta:
- IDENTITY.md — Que es server-nexe i que NO es (desambiguacio)
- INSTALLATION.md — Guia d'instal·lacio detallada
- USAGE.md — Exemples d'us i casos practics
- ARCHITECTURE.md — Arquitectura tecnica en detall
- RAG.md — Com funciona el sistema de memoria
- PLUGINS.md — Sistema de plugins
- API.md — Referencia de l'API REST
- SECURITY.md — Seguretat i autenticacio
- LIMITATIONS.md — Limitacions tecniques
- ERRORS.md — Errors comuns i solucions
- TESTING.md — Estrategia de tests i cobertura

## Enllacos

- Codi font: https://github.com/jgoy-labs/server-nexe
- Documentacio: https://server-nexe.org
- Web comercial: https://server-nexe.com
- Autor: https://jgoy.net
- Suport: https://github.com/sponsors/jgoy-labs | https://ko-fi.com/jgoylabs
