# === METADATA RAG ===
versio: "2.0"
data: 2026-04-02
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "server-nexe es un servidor d'IA local amb memoria RAG persistent creat per Jordi Goy. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Funcionalitats: MEM_SAVE, i18n (ca/es/en), Docker, aillament de sessions, encriptacio at-rest. 15 models disponibles, 3 metodes d'instal-lacio (DMG, CLI, Docker), documentacio AI-ready. macOS testejat, Linux parcial."
tags: [overview, server-nexe, backends, rag, memory, mem_save, i18n, models, installation, architecture, ollama, mlx, llama-cpp, encryption, ai-ready, jordi-goy]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# server-nexe 0.9.0 pre-release — Servidor d'IA local amb memoria persistent

**Versio:** 0.9.0 pre-release
**Port per defecte:** 9119
**Autor:** Jordi Goy (Barcelona)
**Llicencia:** Apache 2.0
**Plataformes:** macOS (testejat), Linux (parcial), Docker (suportat)
**Web:** https://server-nexe.org | https://server-nexe.com

## Que es server-nexe

server-nexe es un servidor d'IA local amb memoria persistent via RAG (Retrieval-Augmented Generation). S'executa completament a la maquina de l'usuari. Sense nuvol, sense telemetria, sense crides a APIs externes. Les converses, documents i embeddings no surten mai del dispositiu.

NO es npm nexe (un compilador de Node.js). NO es un producte de servidor Windows. NO es un substitut d'Ollama — pot utilitzar Ollama com un dels seus backends.

## Capacitats principals

1. **100% local i privat** — Tota la inferencia, memoria i emmagatzematge passen al dispositiu. Zero dependencia del nuvol.
2. **Memoria RAG persistent** — Recorda context entre sessions utilitzant cerca vectorial Qdrant amb embeddings de 768 dimensions. Tres col·leccions: nexe_documentation (docs del sistema), user_knowledge (documents pujats), nexe_web_ui (memoria de conversa).
3. **Memoria automatica (MEM_SAVE)** — El model extreu fets de les converses automaticament (nom, feina, preferencies) i els guarda a memoria. Zero latencia extra (mateixa crida LLM). Suporta intents de guardar, esborrar i recuperar en 3 idiomes.
4. **Inferencia multi-backend** — MLX (natiu Apple Silicon), llama.cpp (GGUF, universal amb Metal), Ollama (bridge). Mateixa API compatible amb OpenAI, backends intercanviables.
5. **Sistema modular de plugins** — Seguretat, web UI, RAG, cada backend — tot es un plugin amb manifests independents. Auto-descobriment a l'arrencada.
6. **Multilingue (ca/es/en)** — i18n complet: UI, prompts del sistema, etiquetes de context RAG, missatges d'error, instal·lador. El servidor es la font de veritat per a la seleccio d'idioma.
7. **Pujada de documents amb aillament de sessio** — Puja documents via la Web UI. Indexats a user_knowledge amb metadades de session_id. Els documents nomes son visibles dins la sessio on s'han pujat.
8. **Encriptacio at-rest (opt-in)** — Encriptacio AES-256-GCM per a SQLite (via SQLCipher), sessions de xat (.enc) i text de documents RAG (TextStore). Els payloads de Qdrant contenen nomes vectors i IDs, sense text. Gestio de claus via OS Keyring, variable d'entorn o fitxer. Recentment afegida — encara no provada en batalla en produccio.
9. **Validacio d'input completa** — Tots els endpoints (API i Web UI) tenen rate limiting, validacio d'input (`validate_string_input`) i sanititzacio de context RAG. 6 detectors d'injeccio amb normalitzacio Unicode. 47 patrons de jailbreak.
10. **Suport Docker** — Dockerfile + docker-compose.yml amb Qdrant embegut. Python 3.12-slim, usuari no-root, Linux amd64/arm64.

## Stack tecnologic

| Component | Tecnologia |
|-----------|-----------|
| Llenguatge | Python 3.11+ (3.12 inclos a l'instal·lador) |
| Framework web | FastAPI 0.115+ |
| Base de dades vectorial | Qdrant (binari embegut) |
| Backends LLM | MLX, llama.cpp (llama-cpp-python), Ollama |
| Embeddings | nomic-embed-text (Ollama) / paraphrase-multilingual-mpnet-base-v2 (fallback offline) |
| Dimensions d'embedding | 768 |
| Encriptacio | AES-256-GCM, HKDF-SHA256, SQLCipher (opt-in) |
| CLI | Click + Rich |
| API | Compatible amb OpenAI (/v1/chat/completions) |
| Autenticacio | X-API-Key (dual-key amb rotacio) |
| Seguretat | 6 detectors d'injeccio + normalitzacio Unicode, 47 patrons de jailbreak, rate limiting, capcaleres CSP |
| Contenidors | Docker + docker-compose (Nexe + Ollama) |

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
├── tests/                 # Suite de tests (4143 funcions de test)
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
- **12 fitxers tematics** que cobreixen identitat, arquitectura, API, seguretat, testing, etc.
- **Disponible en angles, catala i castella**
- Apunta qualsevol assistent d'IA a aquest repositori i podra entendre l'arquitectura completa, crear plugins o contribuir codi

## Models disponibles (15 al cataleg de l'instal·lador)

### Petits (8 GB RAM)
- Qwen3 1.7B (1.1 GB) — Alibaba, 2025
- Qwen3.5 2B (1.5 GB) — Alibaba, 2025 (nomes Ollama)
- Phi-3.5 Mini (2.4 GB) — Microsoft, 2024
- Salamandra 2B (1.5 GB) — BSC/AINA, 2024, optimitzat per al catala
- Qwen3 4B (2.5 GB) — Alibaba, 2025

### Mitjans (12-16 GB RAM)
- Mistral 7B (4.1 GB) — Mistral AI, 2023
- Salamandra 7B (4.9 GB) — BSC/AINA, 2024, el millor per al catala
- Llama 3.1 8B (4.7 GB) — Meta, 2024
- Qwen3 8B (5.0 GB) — Alibaba, 2025
- Gemma 3 12B (7.6 GB) — Google DeepMind, 2025

### Grans (32+ GB RAM)
- Qwen3.5 27B (17 GB) — Alibaba, 2025 (nomes Ollama)
- Qwen3 32B (20 GB) — Alibaba, 2025, raonament hibrid
- Gemma 3 27B (17 GB) — Google DeepMind, 2025
- DeepSeek R1 32B (20 GB) — DeepSeek, 2025, raonament avancat
- Llama 3.1 70B (40 GB) — Meta, 2024

Tambe es suporten models personalitzats via Ollama (per nom) o Hugging Face (repositori GGUF).

## Metodes d'instal·lacio

### 1. Instal·lador DMG per a macOS (recomanat)
Wizard natiu SwiftUI amb 6 pantalles: benvinguda, carpeta de desti, seleccio de model (15 models amb deteccio de maquinari), confirmacio, progres, finalitzacio. Inclou Python 3.12.

### 2. CLI headless
```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go
```

### 3. Docker
```bash
docker-compose up
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
| macOS Apple Silicon | Testejat (tots 3 backends) |
| macOS Intel | Testejat (llama.cpp + Ollama) |
| Linux x86_64 | Parcial (tests unitaris passen, CI verd, no testejat en produccio) |
| Linux ARM64 | Docker suportat |
| Windows | Encara no suportat |

## Limitacions actuals

- Els models locals son menys capacos que GPT-4, Claude, etc. — la contrapartida es la privacitat.
- RAG requereix temps d'indexacio inicial. Memoria buida = sense context RAG.
- Sense sincronitzacio multi-dispositiu.
- Sense fine-tuning de models.
- L'API es parcialment compatible amb OpenAI (falten /v1/embeddings, /v1/models).
- L'encriptacio at-rest es opt-in i nova — encara no provada en batalla.
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
