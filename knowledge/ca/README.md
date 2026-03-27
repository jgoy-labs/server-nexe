# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Visió general de server-nexe 0.8.2, servidor IA local amb memòria persistent RAG. Cobreix què és, backends (MLX, llama.cpp, Ollama), funcionalitats (MEM_SAVE, i18n, Docker, aïllament per sessió), arquitectura, 17 models disponibles, stack tecnològic, mètodes d'instal·lació (wizard SwiftUI, CLI, Docker) i suport actual de plataformes."
tags: [overview, server-nexe, backends, rag, memory, mem_save, i18n, docker, models, installacio, arquitectura, funcionalitats, ollama, mlx, llama-cpp]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# server-nexe 0.8.2 — Servidor IA Local amb Memòria Persistent

**Versió:** 0.8.2
**Port per defecte:** 9119
**Autor:** Jordi Goy (Barcelona)
**Llicència:** Apache 2.0
**Plataformes:** macOS (testat), Linux (parcial), Docker (suportat)
**Web:** https://server-nexe.org | https://server-nexe.com

## Què és server-nexe

server-nexe és un servidor d'IA local amb memòria persistent via RAG (Retrieval-Augmented Generation). Corre completament al dispositiu de l'usuari. Sense cloud, sense telemetria, sense crides a APIs externes. Les converses, documents i embeddings mai surten del dispositiu.

NO és npm nexe (un compilador de Node.js). NO és un producte de servidor Windows. NO és un substitut d'Ollama — pot usar Ollama com un dels seus backends.

## Capacitats principals

1. **100% Local i Privat** — Tota la inferència, memòria i emmagatzematge passen al dispositiu. Zero dependència del cloud.
2. **Memòria RAG Persistent** — Recorda context entre sessions usant cerca vectorial Qdrant amb embeddings de 768 dimensions. Tres col·leccions: nexe_documentation (docs del sistema), user_knowledge (documents pujats), nexe_web_ui (memòria de conversa).
3. **Memòria Automàtica (MEM_SAVE)** — El model extreu fets de les converses automàticament (nom, feina, preferències) i els guarda a memòria. Zero latència extra (mateixa crida LLM). Suporta intencions de guardar, esborrar i recordar en 3 idiomes.
4. **Inferència Multi-Backend** — MLX (natiu Apple Silicon), llama.cpp (GGUF, universal amb Metal), Ollama (bridge). Mateixa API compatible OpenAI, backends intercanviables.
5. **Sistema de Plugins Modular** — Seguretat, UI web, RAG, cada backend — tot és un plugin amb manifests independents. Auto-descoberts a l'arrancar.
6. **Multilingüe (ca/es/en)** — i18n complet: UI, system prompts, etiquetes context RAG, missatges d'error, instal·lador. El servidor és font de veritat per la selecció d'idioma.
7. **Pujada Documents amb Aïllament per Sessió** — Puja documents via Web UI. Indexats a user_knowledge amb metadata session_id. Documents només visibles dins la sessió on es van pujar.
8. **Indicador de Càrrega de Model** — Spinner en temps real amb cronòmetre quan es canvia de model. Funciona amb els 3 backends. Mostra la mida del model en GB al dropdown.
9. **Ollama Auto-start i Fallback** — Ollama arrenca automàticament al boot (en segon pla). Si el backend configurat està desconnectat, auto-selecciona el primer backend disponible amb models carregats.
10. **Suport Docker** — Dockerfile + docker-compose.yml amb Qdrant embedit. Python 3.12-slim, usuari no-root, Linux amd64/arm64.

## Stack tecnològic

| Component | Tecnologia |
|-----------|-----------|
| Llenguatge | Python 3.11+ (bundled 3.12 a l'instal·lador) |
| Framework web | FastAPI 0.128+ |
| Base de dades vectorial | Qdrant (binari embedit) |
| Backends LLM | MLX, llama.cpp (llama-cpp-python), Ollama |
| Embeddings | nomic-embed-text (Ollama) / paraphrase-multilingual-mpnet-base-v2 (fallback offline) |
| Dimensions embeddings | 768 |
| CLI | Click + Rich |
| API | Compatible OpenAI (/v1/chat/completions) |
| Autenticació | X-API-Key (dual-key amb rotació) |
| Seguretat | 6 detectors d'injecció, 69 patrons jailbreak, rate limiting, capçaleres CSP |
| Containerització | Docker + docker-compose (Nexe + Ollama) |

## Arquitectura

```
server-nexe/
├── core/                  # Servidor FastAPI, endpoints, CLI
│   ├── endpoints/         # API REST (chat dividit en 8 submòduls)
│   ├── cli/               # Comandes CLI
│   ├── server/            # Patró factory, lifespan
│   ├── ingest/            # Ingesta documents (docs + knowledge)
│   └── lifespan*.py       # Startup/shutdown (dividit en 3 submòduls)
├── plugins/               # Sistema de plugins modular
│   ├── mlx_module/        # Backend Apple Silicon
│   ├── llama_cpp_module/  # Backend GGUF universal
│   ├── ollama_module/     # Bridge Ollama + auto-start + VRAM cleanup
│   ├── security/          # Auth, rate limiting, detecció d'injeccions
│   └── web_ui_module/     # Interfície web (routes dividit en 6 submòduls)
├── memory/                # Sistema RAG (Qdrant + embeddings + persistència)
├── knowledge/             # Documentació per ingesta RAG (ca/es/en)
├── personality/           # System prompts, module manager, i18n, server.toml
├── installer/             # Wizard SwiftUI, constructor DMG, tray app, instal·lador headless
├── storage/               # Dades runtime (models, logs, vectors qdrant)
├── tests/                 # Suite de tests (3901 tests, 0 fallades)
└── nexe                   # Executable CLI principal
```

**Flux de dades:**
```
Usuari -> CLI/API/Web UI -> Core -> Plugin (MLX/llama.cpp/Ollama) -> Model LLM
                             |                                          |
                             v                                          v
                      Memory (RAG) -> Qdrant -> Context augmentat    MEM_SAVE -> Qdrant
```

## Models disponibles (17 al catàleg de l'instal·lador)

### Petits (8 GB RAM)
- Qwen3 1.7B (1.1 GB) — Alibaba, 2025
- Qwen3.5 2B (1.5 GB) — Alibaba, 2025 (només Ollama, multimodal incompatible amb MLX)
- Phi-3.5 Mini (2.4 GB) — Microsoft, 2024
- Salamandra 2B (1.5 GB) — BSC/AINA, 2024, optimitzat per català
- Qwen3 4B (2.5 GB) — Alibaba, 2025

### Mitjans (12-16 GB RAM)
- Mistral 7B (4.1 GB) — Mistral AI, 2023
- Salamandra 7B (4.9 GB) — BSC/AINA, 2024, millor per català
- Llama 3.1 8B (4.7 GB) — Meta, 2024
- Qwen3 8B (5.0 GB) — Alibaba, 2025
- Gemma 3 12B (7.6 GB) — Google DeepMind, 2025

### Grans (32+ GB RAM)
- Qwen3.5 27B (17 GB) — Alibaba, 2025 (només Ollama)
- Qwen3 32B (20 GB) — Alibaba, 2025, raonament híbrid
- Gemma 3 27B (17 GB) — Google DeepMind, 2025
- DeepSeek R1 32B (20 GB) — DeepSeek, 2025, raonament avançat
- Llama 3.1 70B (40 GB) — Meta, 2024

Models personalitzats suportats via Ollama (nom) o Hugging Face (repo GGUF).

## Mètodes d'instal·lació

### 1. Instal·lador DMG macOS (recomanat)
Wizard natiu SwiftUI amb 6 pantalles: benvinguda, carpeta destí, selecció model (17 models amb detecció hardware), confirmació, progrés, completat. Inclou Python 3.12 bundled. 8-30 minuts segons descàrrega del model.

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
Inclou Nexe + Ollama com a serveis separats. Qdrant embedit.

## Inici ràpid

```bash
./nexe go                    # Arrenca servidor -> http://127.0.0.1:9119
./nexe chat                  # Chat interactiu CLI
./nexe chat --rag            # Chat amb memòria RAG
./nexe memory store "text"   # Guardar a memòria
./nexe memory recall "query" # Recordar de memòria
./nexe status                # Estat del sistema
./nexe knowledge ingest      # Indexar documents
```

Web UI: `http://127.0.0.1:9119/ui`
Docs API: `http://127.0.0.1:9119/docs`
Health check: `http://127.0.0.1:9119/health`

Autenticació requerida: capçalera `X-API-Key` amb valor de `.env` (`NEXE_PRIMARY_API_KEY`).

## Suport de plataformes

| Plataforma | Estat |
|----------|--------|
| macOS Apple Silicon | Testat (3 backends) |
| macOS Intel | Testat (llama.cpp + Ollama) |
| Linux x86_64 | Parcial (tests unitaris passen, CI verd, no testat en producció) |
| Linux ARM64 | Docker suportat |
| Windows | Encara no suportat |

## Limitacions actuals

- Els models locals són menys capaços que GPT-4, Claude, etc. — el compromís és la privacitat.
- El RAG requereix temps d'indexació inicial. Memòria buida = sense context RAG.
- No hi ha sync multi-dispositiu.
- No hi ha fine-tuning de models.
- L'API és parcialment compatible amb OpenAI (falta /v1/embeddings, /v1/models).
- El keep_alive:0 d'Ollama no sempre allibera VRAM (bug conegut d'Ollama).
- No hi ha OCR ni parsing avançat de documents.

## Documentació relacionada

Altres documents de knowledge en aquesta carpeta:
- IDENTITY.md — Què és i què NO és server-nexe (desambiguació)
- INSTALLATION.md — Guia d'instal·lació detallada
- USAGE.md — Exemples d'ús i casos pràctics
- ARCHITECTURE.md — Arquitectura tècnica en detall
- RAG.md — Com funciona el sistema de memòria
- PLUGINS.md — Sistema de plugins
- API.md — Referència API REST
- SECURITY.md — Seguretat i autenticació
- LIMITATIONS.md — Limitacions tècniques
- ERRORS.md — Errors comuns i solucions
- TESTING.md — Estratègia de testing i cobertura

## Enllaços

- Codi font: https://github.com/jgoy-labs/server-nexe
- Documentació: https://server-nexe.org
- Web comercial: https://server-nexe.com
- Autor: https://jgoy.net
- Suport: https://github.com/sponsors/jgoy-labs | https://ko-fi.com/jgoylabs
