# === METADATA RAG ===
versio: "2.0"
data: 2026-07-04
id: nexe-overview
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "server-nexe es un servidor de IA local con memoria RAG persistente creado por Jordi Goy. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Funcionalidades: MEM_SAVE, i18n (ca/es/en), aislamiento de sesiones, encriptacion en reposo, thinking toggle. Modelos por tiers (8GB a 32GB, 14 modelos 4 tiers), 3 metodos de instalacion (nexe-app Tauri desktop recomendado, CLI, DMG SwiftUI legacy). macOS 14+ Apple Silicon, Linux (Ollama, CPU) y Windows ARM64 (nuevo en 1.0.7; installer NSIS sin firmar, backend Ollama)."
tags: [overview, server-nexe, backends, rag, memory, mem_save, i18n, models, installation, architecture, ollama, mlx, llama-cpp, encryption, ai-ready, jordi-goy]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# server-nexe 1.0.7 — Servidor de IA local con memoria persistente

**Version:** 1.0.7
**Puerto por defecto:** 9119
**Autor:** Jordi Goy (Barcelona)
**Licencia:** Apache 2.0
**Plataformas:** macOS 14 Sonoma+ Apple Silicon (M1+) — probado. Linux ARM64 y x86_64 — soportado (Ollama, CPU). Windows ARM64 — soportado desde v1.0.7 (installer NSIS sin firmar; SmartScreen avisa; backend Ollama).
**Web:** https://server-nexe.org | https://server-nexe.com

## Que es server-nexe

server-nexe es un servidor de IA local con memoria persistente via RAG (Retrieval-Augmented Generation). Se ejecuta completamente en la maquina del usuario. Sin nube, sin telemetria, sin llamadas a APIs externas. Las conversaciones, documentos y embeddings nunca salen del dispositivo.

NO es npm nexe (un compilador de Node.js). NO es un producto de servidor Windows. NO es un sustituto de Ollama — puede usar Ollama como uno de sus backends.

## Intencion de diseño

Lo que empezó como un learning-by-doing y un monstruo de espagueti gigante derivó, en varios refactors, hacia el objetivo de construir un núcleo mínimo, agnóstico y modular donde la seguridad y la memoria estén resueltas en la base — para que construir encima sea rápido y cómodo — en colaboración humano-IA. Si se ha conseguido, lo tiene que decir la comunidad (la IA dice que sí, pero qué quieres que diga 🤪).

## Capacidades principales

1. **100% Local y privado** — Toda la inferencia, memoria y almacenamiento ocurren en el dispositivo. Cero dependencia de la nube.
2. **Memoria RAG persistente** — Recuerda el contexto entre sesiones usando busqueda vectorial Qdrant con embeddings de 768 dimensiones. Tres colecciones: nexe_documentation (documentacion del sistema), user_knowledge (documentos subidos), personal_memory (memoria de conversaciones).
3. **Memoria automatica (MEM_SAVE)** — El modelo extrae hechos de las conversaciones automaticamente (nombre, trabajo, preferencias) y los guarda en memoria. Cero latencia adicional (misma llamada LLM). Soporta intenciones de guardar, borrar y recuperar en 3 idiomas.
4. **Inferencia multi-backend** — MLX (nativo Apple Silicon), llama.cpp (GGUF, universal con Metal), Ollama (bridge). Misma API compatible con OpenAI, backends intercambiables.
5. **Sistema modular de plugins** — Seguridad, web UI, RAG, cada backend — todo es un plugin con manifests independientes. Auto-descubrimiento al arrancar.
6. **Multilingue (ca/es/en)** — i18n completo: UI, system prompts, etiquetas de contexto RAG, mensajes de error, instalador. El servidor es la fuente de verdad para la seleccion de idioma.
7. **Upload de documentos con aislamiento de sesion** — Sube documentos via la Web UI. Indexados en user_knowledge con metadatos session_id. Los documentos solo son visibles dentro de la sesion donde fueron subidos.
8. **Encriptacion en reposo (default `auto`)** — Encriptacion AES-256-GCM para SQLite (via SQLCipher), sesiones de chat (.enc), y texto de documentos RAG (TextStore). Se activa automaticamente si sqlcipher3 esta disponible. Gestion de claves via OS Keyring, variable de entorno, o fichero. Anadida recientemente — aun no probada en batalla en produccion.
9. **Validacion de entrada completa** — Todos los endpoints (API y Web UI) tienen rate limiting, validacion de entrada (`validate_string_input`), y sanitizacion de contexto RAG. 6 detectores de inyeccion con normalizacion Unicode. 49 patrones de jailbreak.

## Stack tecnologico

| Componente | Tecnologia |
|-----------|-----------|
| Lenguaje | Python 3.11+ (3.12 bundled en instalador) |
| Framework web | FastAPI 0.136.3 (pinned) |
| Base de datos vectorial | Qdrant (binario embebido) |
| Backends LLM | MLX, llama.cpp (llama-cpp-python 0.3.19 pinned), Ollama |
| Embeddings | **fastembed ONNX (paraphrase-multilingual-mpnet-base-v2, 768D) — principal offline** / nomic-embed-text via Ollama (opcional) |
| Dimensiones de embedding | 768 |
| Encriptacion | AES-256-GCM, HKDF-SHA256, SQLCipher (default auto) |
| CLI | Click + Rich |
| API | Compatible con OpenAI (/v1/chat/completions) |
| Autenticacion | X-API-Key (dual-key con rotacion) |
| Seguridad | 6 detectores de inyeccion + normalizacion Unicode, 49 patrones de jailbreak, rate limiting, cabeceras CSP |

## Arquitectura

```
server-nexe/
├── core/                  # Servidor FastAPI, endpoints, CLI, crypto
│   ├── endpoints/         # REST API (chat dividido en 8 submodulos)
│   ├── crypto/            # Encriptacion en reposo (AES-256-GCM, SQLCipher)
│   ├── cli/               # Comandos CLI
│   ├── server/            # Patron factory, lifespan
│   ├── ingest/            # Ingestion de documentos (docs + knowledge)
│   └── lifespan*.py       # Arranque/apagado (dividido en 8 submodulos)
├── plugins/               # Sistema modular de plugins
│   ├── mlx_module/        # Backend Apple Silicon
│   ├── llama_cpp_module/  # Backend universal GGUF
│   ├── ollama_module/     # Bridge Ollama + auto-arranque + limpieza VRAM
│   ├── security/          # Auth, rate limiting, deteccion de inyecciones
│   └── web_ui_module/     # Interfaz web (rutas divididas en 6 submodulos)
├── memory/                # Sistema RAG (Qdrant + embeddings + persistencia + TextStore)
├── knowledge/             # Documentacion para ingestion RAG (ca/es/en)
├── personality/           # System prompts, module manager, i18n, server.toml
├── installer/             # Wizard SwiftUI, constructor DMG, tray app, instalador headless, installer Windows (NSIS)
├── storage/               # Datos en tiempo de ejecucion (modelos, logs, vectores qdrant)
├── tests/                 # Suite de tests (cifras actualizadas en TESTING.md)
└── nexe                   # Ejecutable CLI principal
```

**Flujo de datos:**
```
Usuario -> CLI/API/Web UI -> Auth -> Rate Limit -> Validar Entrada -> Core -> Plugin -> LLM
                                                       |                           |
                                                       v                           v
                                                Memory (RAG) -> Qdrant      MEM_SAVE -> Qdrant
                                                       |
                                               _sanitize_rag_context
```

## Documentacion AI-Ready

La base de conocimiento (`knowledge/`) esta disenada tanto para consumo humano como de IA:
- **Frontmatter YAML estructurado** para ingestion RAG (chunk_size, tags, priority)
- **14 ficheros tematicos** cubriendo identidad, arquitectura, API, seguridad, pruebas, casos de uso, etc.
- **Disponible en ingles, catalan y espanol**
- Apunta cualquier asistente de IA a este repositorio y podra entender la arquitectura completa, crear plugins o contribuir codigo

## Modelos disponibles (por tiers de RAM)

14 modelos testeados empiricamente, 4 tiers. Iconos: 👁 = vision (imagenes), 🧠 = thinking (razonamiento paso a paso).

### tier_8 (8 GB RAM)
- 👁 🧠 **Qwen3.5 4B** — Alibaba, 2026. Ollama + MLX. **Recomendado.**

### tier_16 (16 GB RAM)
- 👁 🧠 Qwen3.5 9B — Alibaba, 2026. Ollama + MLX.
- 👁 🧠 Qwen3.5 4B (8-bit) — Alibaba, 2026. MLX (Apple Silicon, solo macOS). Precision 8-bit (mas fiel que el 4B base).
- 👁 🧠 Gemma 4 E4B — Google, 2026. Ollama + MLX.
- 🧠 Mistral Nemo 12B — Mistral AI, 2024. Ollama + MLX.
- Salamandra 7B — BSC/AINA, 2025. Ollama + llama.cpp (GGUF). El mejor para catalan.

### tier_24 (24 GB RAM)
- 👁 🧠 Qwen3.5 27B — Alibaba, 2026. Ollama + MLX.
- 👁 🧠 Mistral Small 3.2 24B — Mistral AI, 2025. Ollama + MLX.
- 🧠 GPT-OSS 20B — OpenAI, 2025. Ollama + MLX. Apache 2.0.

### tier_32 (32 GB RAM)
- 👁 🧠 Qwen3.5 35B-A3B (MoE) — Alibaba, 2026. Ollama + MLX.
- 👁 🧠 Gemma 4 31B — Google, 2026. Ollama + MLX.
- 🧠 Mixtral 8x7B (MoE) — Mistral AI, 2023. Ollama + MLX.
- 🧠 DeepSeek R1 Distill 32B — DeepSeek, 2025. Ollama + llama.cpp (MLX no soportado: arch qwen2).
- **ALIA-40B Instruct** — BSC, 2026. Ollama + llama.cpp (GGUF). 9 idiomas ibericos. **Recomendado iberico.**

### Notas de compatibilidad backends (verificado 2026-05-24)

- **DeepSeek R1 Distill en MLX**: error "Unsupported model: qwen2". Usar Ollama o GGUF via llama.cpp.
- **Gemma 4 E4B en MLX**: puede ser inestable (loops repetitivos) en modelos pequenos. Funciona bien para vision.
- **Gemma 4 31B en MLX**: requiere descarga completa 8-bit (~33 GB, 7 shards). Verificar integridad.
- **ALIA-40B**: 42 GB Q8_0. Verificar integridad despues de descargar (caso tensor truncado detectado).

Tambien se soportan modelos personalizados via Ollama (nombre) o Hugging Face (repo GGUF).

## Metodos de instalacion

### 1. Aplicacion de escritorio — nexe-app (Tauri v2, recomendado)
Aplicacion de escritorio que integra server-nexe como sidecar Python dentro de un shell Tauri v2. Descarga el `nexe-app_*_aarch64.dmg` (macOS), el `.AppImage` (Linux ARM64) o el setup `.exe` NSIS (Windows ARM64, nuevo en 1.0.7 — installer sin firmar, SmartScreen avisa) desde la pagina de [Releases](https://github.com/jgoy-labs/server-nexe/releases/latest). Incluye wizard de onboarding, system tray y gestion automatica del sidecar.

### 2. CLI headless
```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go
```

### 3. Instalador DMG SwiftUI (legacy)
> **Estado:** reemplazado por la aplicacion de escritorio (Metodo 1). Documentado para instalaciones existentes.

Wizard nativo SwiftUI con 6 pantallas, Python 3.12 bundled, instalacion 100% offline (~1.2 GB). Solo Apple Silicon macOS.

## Inicio rapido

```bash
./nexe go                    # Arrancar servidor -> http://127.0.0.1:9119
./nexe chat                  # Chat interactivo por CLI (memoria RAG activa por defecto)
./nexe memory store "texto"  # Guardar en memoria
./nexe memory recall "query" # Recuperar de memoria
./nexe status                # Estado del sistema
./nexe knowledge ingest      # Indexar documentos
./nexe encryption status     # Comprobar estado de encriptacion
```

Web UI: `http://127.0.0.1:9119/ui`
Documentacion API: `http://127.0.0.1:9119/docs`
Health check: `http://127.0.0.1:9119/health`

Autenticacion requerida: cabecera `X-API-Key` con el valor de `.env` (`NEXE_PRIMARY_API_KEY`).

## Soporte de plataformas

| Plataforma | Estado |
|----------|--------|
| macOS 14 Sonoma+ Apple Silicon (M1+) | Probado (los 3 backends) |
| macOS 13 Ventura | **NO soportado** (eliminado en v0.9.9) |
| macOS Intel | **NO soportado** (eliminado en v0.9.9 — wheels arm64-only) |
| Linux ARM64 | Soportado (Ollama, CPU) — testeado en VM Ubuntu 24.04 ARM64 (UTM) |
| Linux x86_64 | Soportado (Ollama, CPU) — tests unitarios pasan, CLI validada |
| Windows ARM64 | Soportado desde v1.0.7 (NUEVO) — installer NSIS; solo backend Ollama (la app lo instala automaticamente); installer sin firmar (SmartScreen avisa: "Mas informacion" → "Ejecutar de todas formas") |

## Limitaciones actuales

- Los modelos locales son menos capaces que GPT-4, Claude, etc. — la contrapartida es la privacidad.
- RAG requiere tiempo de indexacion inicial. Memoria vacia = sin contexto RAG.
- Sin sincronizacion multi-dispositivo.
- Sin fine-tuning de modelos.
- La API es parcialmente compatible con OpenAI (faltan /v1/embeddings, /v1/models).
- La encriptacion en reposo es `auto` por defecto (se activa si sqlcipher3 disponible) — nueva, aun no probada en batalla.
- Proyecto de un solo desarrollador con auditorias asistidas por IA, no auditado formalmente.

## Documentacion relacionada

Otros documentos de knowledge en esta carpeta:
- IDENTITY.md — Que es server-nexe y que NO es (desambiguacion)
- INSTALLATION.md — Guia de instalacion detallada
- USAGE.md — Ejemplos de uso y casos practicos
- USE_CASES.md — Casos de uso y cuando server-nexe tiene (o no) sentido
- LANGUAGES.md — Deteccion de idioma por mensaje y directiva de respuesta
- ARCHITECTURE.md — Arquitectura tecnica en detalle
- RAG.md — Como funciona el sistema de memoria
- PLUGINS.md — Sistema de plugins
- API.md — Referencia de la REST API
- SECURITY.md — Seguridad y autenticacion
- THREAT_MODEL.md — Threat model formal STRIDE (boundaries, mitigaciones, riesgos residuales, apendice LINDDUN de privacidad)
- LIMITATIONS.md — Limitaciones tecnicas
- ERRORS.md — Errores comunes y soluciones
- TESTING.md — Estrategia de pruebas y cobertura

## Enlaces

- Codigo fuente: https://github.com/jgoy-labs/server-nexe
- Documentacion: https://server-nexe.org
- Sitio comercial: https://server-nexe.com
- Autor: https://jgoy.net
- Soporte: https://github.com/sponsors/jgoy-labs | https://ko-fi.com/servernexe
