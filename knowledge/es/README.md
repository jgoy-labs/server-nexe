# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Visión general de server-nexe 0.8.2, servidor IA local con memoria persistente RAG. Cubre qué es, backends (MLX, llama.cpp, Ollama), funcionalidades (MEM_SAVE, i18n, Docker, aislamiento por sesión), arquitectura, 17 modelos disponibles, stack tecnológico, métodos de instalación (wizard SwiftUI, CLI, Docker) y soporte actual de plataformas."
tags: [overview, nexe, server-nexe, backends, rag, memory, mem_save, i18n, docker, models, instalacion, arquitectura, funcionalidades, ollama, mlx, llama-cpp]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# server-nexe 0.8.2 — Servidor IA Local con Memoria Persistente

**Versión:** 0.8.2
**Puerto por defecto:** 9119
**Autor:** Jordi Goy (Barcelona)
**Licencia:** Apache 2.0
**Plataformas:** macOS (testeado), Linux (parcial), Docker (soportado)
**Web:** https://server-nexe.org | https://server-nexe.com

## Qué es server-nexe

server-nexe es un servidor de IA local con memoria persistente vía RAG (Retrieval-Augmented Generation). Funciona completamente en el dispositivo del usuario. Sin cloud, sin telemetría, sin llamadas a APIs externas. Las conversaciones, documentos y embeddings nunca salen del dispositivo.

NO es npm nexe (un compilador de Node.js). NO es un producto de servidor Windows. NO es un sustituto de Ollama — puede usar Ollama como uno de sus backends.

## Capacidades principales

1. **100% Local y Privado** — Toda la inferencia, memoria y almacenamiento ocurren en el dispositivo. Cero dependencia del cloud.
2. **Memoria RAG Persistente** — Recuerda contexto entre sesiones usando búsqueda vectorial Qdrant con embeddings de 768 dimensiones. Tres colecciones: nexe_documentation (docs del sistema), user_knowledge (documentos subidos), nexe_web_ui (memoria de conversación).
3. **Memoria Automática (MEM_SAVE)** — El modelo extrae hechos de las conversaciones automáticamente (nombre, trabajo, preferencias) y los guarda en memoria. Cero latencia extra (misma llamada LLM). Soporta intenciones de guardar, borrar y recordar en 3 idiomas.
4. **Inferencia Multi-Backend** — MLX (nativo Apple Silicon), llama.cpp (GGUF, universal con Metal), Ollama (bridge). Misma API compatible OpenAI, backends intercambiables.
5. **Sistema de Plugins Modular** — Seguridad, UI web, RAG, cada backend — todo es un plugin con manifests independientes. Auto-descubiertos al arrancar.
6. **Multilingüe (ca/es/en)** — i18n completo: UI, system prompts, etiquetas contexto RAG, mensajes de error, instalador. El servidor es fuente de verdad para la selección de idioma.
7. **Subida de Documentos con Aislamiento por Sesión** — Sube documentos vía Web UI. Indexados en user_knowledge con metadata session_id. Documentos solo visibles dentro de la sesión donde se subieron.
8. **Indicador de Carga de Modelo** — Spinner en tiempo real con cronómetro al cambiar de modelo. Funciona con los 3 backends. Muestra el tamaño del modelo en GB en el dropdown.
9. **Ollama Auto-start y Fallback** — Ollama arranca automáticamente al boot (en segundo plano). Si el backend configurado está desconectado, auto-selecciona el primer backend disponible con modelos cargados.
10. **Soporte Docker** — Dockerfile + docker-compose.yml con Qdrant embebido. Python 3.12-slim, usuario no-root, Linux amd64/arm64.

## Stack tecnológico

| Componente | Tecnología |
|-----------|-----------|
| Lenguaje | Python 3.11+ (bundled 3.12 en instalador) |
| Framework web | FastAPI 0.128+ |
| Base de datos vectorial | Qdrant (binario embebido) |
| Backends LLM | MLX, llama.cpp (llama-cpp-python), Ollama |
| Embeddings | nomic-embed-text (Ollama) / paraphrase-multilingual-mpnet-base-v2 (fallback offline) |
| Dimensiones embeddings | 768 |
| CLI | Click + Rich |
| API | Compatible OpenAI (/v1/chat/completions) |
| Autenticación | X-API-Key (dual-key con rotación) |
| Seguridad | 6 detectores de inyección, 69 patrones jailbreak, rate limiting, cabeceras CSP |
| Containerización | Docker + docker-compose (Nexe + Ollama) |

## Arquitectura

```
server-nexe/
├── core/                  # Servidor FastAPI, endpoints, CLI
│   ├── endpoints/         # API REST (chat dividido en 8 submódulos)
│   ├── cli/               # Comandos CLI
│   ├── server/            # Patrón factory, lifespan
│   ├── ingest/            # Ingesta de documentos (docs + knowledge)
│   └── lifespan*.py       # Startup/shutdown (dividido en 3 submódulos)
├── plugins/               # Sistema de plugins modular
│   ├── mlx_module/        # Backend Apple Silicon
│   ├── llama_cpp_module/  # Backend GGUF universal
│   ├── ollama_module/     # Bridge Ollama + auto-start + VRAM cleanup
│   ├── security/          # Auth, rate limiting, detección de inyecciones
│   └── web_ui_module/     # Interfaz web (routes dividido en 6 submódulos)
├── memory/                # Sistema RAG (Qdrant + embeddings + persistencia)
├── knowledge/             # Documentación para ingesta RAG (ca/es/en)
├── personality/           # System prompts, module manager, i18n, server.toml
├── installer/             # Wizard SwiftUI, constructor DMG, tray app, instalador headless
├── storage/               # Datos runtime (modelos, logs, vectores qdrant)
├── tests/                 # Suite de tests (3901 tests, 0 fallos)
└── nexe                   # Ejecutable CLI principal
```

**Flujo de datos:**
```
Usuario -> CLI/API/Web UI -> Core -> Plugin (MLX/llama.cpp/Ollama) -> Modelo LLM
                              |                                          |
                              v                                          v
                       Memory (RAG) -> Qdrant -> Contexto aumentado   MEM_SAVE -> Qdrant
```

## Modelos disponibles (17 en el catálogo del instalador)

### Pequeños (8 GB RAM)
- Qwen3 1.7B (1.1 GB) — Alibaba, 2025
- Qwen3.5 2B (1.5 GB) — Alibaba, 2025 (solo Ollama, multimodal incompatible con MLX)
- Phi-3.5 Mini (2.4 GB) — Microsoft, 2024
- Salamandra 2B (1.5 GB) — BSC/AINA, 2024, optimizado para catalán
- Qwen3 4B (2.5 GB) — Alibaba, 2025

### Medianos (12-16 GB RAM)
- Mistral 7B (4.1 GB) — Mistral AI, 2023
- Salamandra 7B (4.9 GB) — BSC/AINA, 2024, mejor para catalán
- Llama 3.1 8B (4.7 GB) — Meta, 2024
- Qwen3 8B (5.0 GB) — Alibaba, 2025
- Gemma 3 12B (7.6 GB) — Google DeepMind, 2025

### Grandes (32+ GB RAM)
- Qwen3.5 27B (17 GB) — Alibaba, 2025 (solo Ollama)
- Qwen3 32B (20 GB) — Alibaba, 2025, razonamiento híbrido
- Gemma 3 27B (17 GB) — Google DeepMind, 2025
- DeepSeek R1 32B (20 GB) — DeepSeek, 2025, razonamiento avanzado
- Llama 3.1 70B (40 GB) — Meta, 2024

Modelos personalizados soportados vía Ollama (nombre) o Hugging Face (repo GGUF).

## Métodos de instalación

### 1. Instalador DMG macOS (recomendado)
Wizard nativo SwiftUI con 6 pantallas: bienvenida, carpeta destino, selección de modelo (17 modelos con detección de hardware), confirmación, progreso, completado. Incluye Python 3.12 bundled. 8-30 minutos según descarga del modelo.

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
Incluye Nexe + Ollama como servicios separados. Qdrant embebido.

## Inicio rápido

```bash
./nexe go                    # Arranca servidor -> http://127.0.0.1:9119
./nexe chat                  # Chat interactivo CLI
./nexe chat --rag            # Chat con memoria RAG
./nexe memory store "texto"  # Guardar en memoria
./nexe memory recall "query" # Recordar de memoria
./nexe status                # Estado del sistema
./nexe knowledge ingest      # Indexar documentos
```

Web UI: `http://127.0.0.1:9119/ui`
Docs API: `http://127.0.0.1:9119/docs`
Health check: `http://127.0.0.1:9119/health`

Autenticación requerida: cabecera `X-API-Key` con valor de `.env` (`NEXE_PRIMARY_API_KEY`).

## Soporte de plataformas

| Plataforma | Estado |
|----------|--------|
| macOS Apple Silicon | Testeado (3 backends) |
| macOS Intel | Testeado (llama.cpp + Ollama) |
| Linux x86_64 | Parcial (tests unitarios pasan, CI verde, no testeado en producción) |
| Linux ARM64 | Docker soportado |
| Windows | Aún no soportado |

## Limitaciones actuales

- Los modelos locales son menos capaces que GPT-4, Claude, etc. — la contrapartida es la privacidad.
- El RAG requiere tiempo de indexación inicial. Memoria vacía = sin contexto RAG.
- No hay sync multi-dispositivo.
- No hay fine-tuning de modelos.
- La API es parcialmente compatible con OpenAI (falta /v1/embeddings, /v1/models).
- El keep_alive:0 de Ollama no siempre libera VRAM (bug conocido de Ollama).
- No hay OCR ni parsing avanzado de documentos.

## Documentación relacionada

Otros documentos de knowledge en esta carpeta:
- IDENTITY.md — Qué es y qué NO es server-nexe (desambiguación)
- INSTALLATION.md — Guía de instalación detallada
- USAGE.md — Ejemplos de uso y casos prácticos
- ARCHITECTURE.md — Arquitectura técnica en detalle
- RAG.md — Cómo funciona el sistema de memoria
- PLUGINS.md — Sistema de plugins
- API.md — Referencia API REST
- SECURITY.md — Seguridad y autenticación
- LIMITATIONS.md — Limitaciones técnicas
- ERRORS.md — Errores comunes y soluciones
- TESTING.md — Estrategia de testing y cobertura

## Enlaces

- Código fuente: https://github.com/jgoy-labs/server-nexe
- Documentación: https://server-nexe.org
- Web comercial: https://server-nexe.com
- Autor: https://jgoy.net
- Soporte: https://github.com/sponsors/jgoy-labs | https://ko-fi.com/jgoylabs
