# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-overview

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Visión general de NEXE 0.8, servidor IA local con memoria persistente. Cubre backends (MLX, llama.cpp, Ollama), funcionalidades, arquitectura, modelos disponibles, casos de uso y roadmap. Proyecto educativo de Jordi Goy."
tags: [overview, nexe, backends, rag, memory, arquitectura, roadmap, models, instal·lació]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# NEXE 0.8 - Servidor IA Local con Memoria

**Versión:** 0.8.0
**Puerto por defecto:** 9119
**Autor:** Jordi Goy
**Licencia:** Apache 2.0

## ¿Qué es NEXE?

NEXE es un **proyecto personal de aprendizaje** (learning by doing) que explora cómo construir un servidor de Inteligencia Artificial que funciona completamente en local, con una característica diferencial: **memoria persistente integrada** mediante RAG (Retrieval-Augmented Generation).

**Importante:** No es un producto acabado ni intenta competir con herramientas maduras como ChatGPT, Claude, Ollama o LM Studio. Es un experimento para aprender sobre:
- Sistemas RAG y memoria vectorial
- Integración de diferentes backends LLM
- Arquitectura modular con plugins
- APIs REST y servidores con FastAPI
- Gestión de embeddings y búsqueda semántica

## ¿Por qué NEXE si ya existe Ollama/LM Studio?

NEXE **no sustituye** a Ollama, LM Studio o similares. ¡De hecho, puede usar Ollama como backend!

**Backends disponibles:**
1. **MLX** - Nativo para Apple Silicon (mlx-community)
2. **llama.cpp** - Universal, con aceleración Metal en Mac
3. **Ollama** - Bridge a Ollama si ya lo tienes instalado

**Backends futuros considerados:**
- LM Studio bridge
- vLLM para inferencia optimizada
- Otros engines según necesidad

**¿Qué aporta NEXE?**
- Una **capa RAG experimental** sobre estos backends
- Sistema de **memoria persistente** entre conversaciones
- API unificada para cambiar de backend fácilmente
- Aprender construyendo un sistema completo
- [Futuro] Experimentar con integración Claude Code + RAG local

## Estado del proyecto

### ✅ Qué funciona (testado)

**Plataforma:**
- macOS (Apple Silicon e Intel) - Única plataforma probada

**Backends LLM:**
- MLX backend para Apple Silicon
- llama.cpp con Metal
- Bridge a Ollama

**Funcionalidades:**
- Sistema RAG con Qdrant (3 colecciones especializadas)
- API REST parcialmente compatible OpenAI (/v1/chat/completions)
- CLI interactivo (`./nexe`) con subcomandos
- Web UI básica experimental
- Sistema de seguridad (dual-key auth, rate limiting, sanitización)
- Indexación de documentos (knowledge ingest)
- Memoria persistente (768-dim embeddings)

### ⚠️ Qué es teórico (código implementado pero NO testado)

- **Raspberry Pi** - El instalador tiene detección pero nunca probado en RPi real
- **Linux x86_64** - Debería funcionar con llama.cpp, NO testado
- **Windows** - Teóricamente posible con llama.cpp, NO testado

### 🔨 Qué está en desarrollo o pendiente

- **claude_code_module** (v0.9) - Integración experimental con Claude Code para usar RAG local
- **LM Studio bridge** - Integración con LM Studio como backend alternativo
- **Web UI avanzada** - La UI actual es muy básica
- **Gestión avanzada de documentos** - Mejor indexación, metadata, etc.

## Instalación rápida

**Requisitos mínimos:**
- macOS 12+ (recomendado: macOS 14+ con Apple Silicon)
- Python 3.9+ (recomendado: 3.11+)
- 8 GB RAM (recomendado: 16+ GB)
- 10 GB espacio libre en disco

**Instalación guiada:**

```bash
cd server-nexe
python3 install_nexe.py
```

El instalador interactivo te guiará por:
1. Detectar tu hardware (CPU, RAM, GPU)
2. Seleccionar el backend adecuado (MLX, llama.cpp u Ollama)
3. Elegir un modelo LLM según tu RAM
4. Configurar el sistema
5. Iniciar el servidor automáticamente

## Inicio rápido

### Iniciar el servidor

```bash
./nexe go
```

El servidor se iniciará en el puerto 9119:
- API: `http://localhost:9119`
- Web UI: `http://localhost:9119/ui`
- Health check: `http://localhost:9119/health`
- Documentación API: `http://localhost:9119/docs`

**Nota:** La API requiere autenticación con cabecera `X-API-Key` (configurado en `.env` como `NEXE_PRIMARY_API_KEY`).

### Chat interactivo

```bash
# Chat simple
./nexe chat

# Chat con memoria RAG activada
./nexe chat --rag
```

### Gestión de memoria

```bash
# Guardar información en la memoria
./nexe memory store "La capital de Catalunya és Barcelona"

# Recuperar de la memoria
./nexe memory recall "capital Catalunya"

# Estado del sistema
./nexe status

# Estadísticas de memoria
./nexe memory stats
```

## Arquitectura básica

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

**Flujo básico:**
```
Usuario → CLI/API → Core → Plugin (MLX/llama.cpp/Ollama) → Modelo LLM
                     ↓
                   Memory (RAG) → Qdrant → Contexto aumentado
```

## Modelos disponibles

El instalador ofrece varios modelos según tu RAM disponible:

### Modelos pequeños (8GB RAM)
- **Phi-3.5 Mini** (2.4 GB) - Microsoft, rápido, multilingüe
- **Salamandra 2B** (1.5 GB) - BSC/AINA, optimizado para catalán y lenguas ibéricas

### Modelos medianos (12-16GB RAM)
- **Mistral 7B** (4.1 GB) - Mistral AI, buen equilibrio calidad/velocidad
- **Salamandra 7B** (4.9 GB) - BSC/AINA, excelente para catalán
- **Llama 3.1 8B** (4.7 GB) - Meta, muy popular, alta calidad

### Modelos grandes (32GB+ RAM)
- **Mixtral 8x7B** (26 GB) - Mistral AI, modelo MoE (Mixture of Experts)
- **Llama 3.1 70B** (40 GB) - Meta, calidad profesional

**Nota:** Los modelos en catalán (Salamandra) son especialmente interesantes para este proyecto hecho en Cataluña.

## Stack tecnológico

| Componente | Tecnología | Versión |
|-----------|------------|--------|
| Backend | FastAPI | 0.104+ |
| Python | CPython | 3.9+ |
| Servidor LLM | MLX / llama.cpp / Ollama | - |
| Base de datos vectorial | Qdrant | Latest |
| Base de datos relacional | SQLite | 3 |
| Embeddings | Ollama (nomic-embed-text) + sentence-transformers | Latest |
| CLI | Click + Rich | - |
| API | Parcialmente compatible OpenAI | v1 |
| Autenticación | X-API-Key (dual-key rotation) | - |

## Casos de uso experimentales

### 1. Asistente personal con memoria
NEXE puede recordar información entre sesiones: proyectos, preferencias, contexto personal.

### 2. Base de conocimiento privada
Indexa documentos locales (MD, PDF, TXT) y consúltalos en lenguaje natural sin enviarlos a la nube.

### 3. Desarrollo con IA
Usa modelos locales para coding, experimentación, sin depender de servicios externos.

### 4. Experimentación con LLMs
Prueba diferentes modelos y backends, compara resultados, aprende cómo funcionan.

### 5. [Futuro experimental] Claude Code con RAG
Cuando se implemente el claude_code_module, se podrá experimentar con Claude Code usando memoria local.

## Filosofía del proyecto

NEXE **no intenta competir** con ChatGPT, Claude u otros asistentes profesionales.

**El objetivo es aprender y demostrar que:**

1. Una IA útil con memoria persistente es posible en local
2. La privacidad total es posible (cero datos salen de tu Mac)
3. Los modelos locales pueden cubrir muchos casos de uso cotidianos
4. La arquitectura modular permite experimentar con diferentes backends
5. El código abierto permite entender cómo funciona todo

**Es un proyecto educativo** que puede ser útil para:
- Aprender sobre RAG y sistemas de IA
- Tener un asistente local para tareas básicas
- Experimentar con modelos sin costes de API
- Mantener privacidad absoluta de las conversaciones

## Limitaciones actuales

### Técnicas
- **Solo testado en macOS** (a pesar de tener código multiplataforma)
- **Los modelos locales son menos capaces** que GPT-4, Claude Opus, etc.
- **El RAG requiere tiempo** de indexación para grandes volúmenes de datos
- **Calidad variable** según el modelo seleccionado
- **Consumo de RAM** importante con modelos grandes

### Funcionales
- **Web UI muy básica** (no es prioridad ahora)
- **claude_code_module no implementado** todavía
- **No hay sync multi-dispositivo**
- **Gestión de documentos simple** (sin OCR, sin parsing avanzado)
- **No hay fine-tuning** de modelos
- **API parcialmente compatible OpenAI** (falta /v1/embeddings, /v1/models)
- **CLI limitado** (comandos básicos: go, status, chat, memory, knowledge)

### Experiencia
- Es un proyecto **experimental y en evolución**
- Puede tener bugs y comportamientos inesperados
- No hay soporte profesional ni SLA
- La documentación está en construcción

## Roadmap (flexible)

| Versión | Objetivo | Estado | Fecha aprox. |
|--------|----------|-------|-------------|
| 0.8 | Base + RAG + 3 backends | ✅ | Completado |
| 0.9 | claude_code_module experimental | 🔨 | Febrero 2026 |
| 1.0 | Demo pública, docs completas | 📅 | Marzo 2026 |
| 1.x | LM Studio, mejoras RAG | 💡 | TBD |

**Nota:** Las fechas son orientativas. Es un proyecto personal hecho en tiempo libre.

## Recursos y documentación

**En esta carpeta (knowledge/):**
- **INSTALLATION.md** - Guía de instalación detallada
- **USAGE.md** - Ejemplos de uso y casos prácticos
- **ARCHITECTURE.md** - Arquitectura técnica detallada
- **RAG.md** - Cómo funciona el sistema de memoria
- **PLUGINS.md** - Sistema de plugins y cómo crearlos
- **API.md** - Referencia completa de la API REST
- **SECURITY.md** - Sistema de seguridad y autenticación
- **LIMITATIONS.md** - Limitaciones técnicas y casos no soportados

**Web:**
- **Autor:** Jordi Goy - [jgoy.net](https://jgoy.net)

## Empezar a explorar

Después de leer este README, el flujo recomendado es:

1. **INSTALLATION.md** - Instala el sistema
2. **USAGE.md** - Prueba las funcionalidades básicas
3. **RAG.md** - Entiende cómo funciona la memoria
4. **ARCHITECTURE.md** - Profundiza en la arquitectura
5. **SECURITY.md** - Entiende el sistema de seguridad y autenticación
6. **API.md** - Si quieres integrarlo con otras herramientas
7. **LIMITATIONS.md** - Para saber qué NO puede hacer

---

**Nota importante:** Esta documentación se auto-ingesta en el sistema RAG de NEXE durante la instalación. Si le preguntas a NEXE sobre sí mismo, sus capacidades o limitaciones, usará esta información para responder honestamente.

**Learning by doing** - Este proyecto es un experimento de aprendizaje continuo. Errores, mejoras y evolución son parte del proceso.
