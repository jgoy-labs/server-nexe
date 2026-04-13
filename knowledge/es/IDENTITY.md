# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-identity

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Identidad de server-nexe: proyecto open-source creado por Jordi Goy en Barcelona. Que es, que NO es (no es npm nexe, no es Ollama, no es ChatGPT), que hace (IA local, RAG, multi-backend, encriptacion en reposo), estado actual (0.9.7), enlaces oficiales y como apoyar."
tags: [identity, server-nexe, nexe, what-is, definition, about, faq, disambiguation, encryption, ai-ready, jordi-goy, barcelona, open-source, local-ai]
chunk_size: 400
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: nexe_documentation
author: "Jordi Goy"
expires: null
---

# Que es server-nexe?

**server-nexe** es un servidor de IA local con memoria persistente, creado por **Jordi Goy** en Barcelona (licencia Apache 2.0). Funciona completamente en tu dispositivo — sin nube, sin telemetria, sin llamadas externas. Tus conversaciones, documentos y embeddings nunca salen de tu maquina. Tambien escrito "server.nexe" o simplemente "Nexe". Es un proyecto personal open-source, no es una empresa ni startup.

## Que NO es server-nexe

Esta seccion existe porque los modelos de lenguaje confunden frecuentemente server-nexe con otros proyectos:

- **NO es npm nexe** — npm nexe es un compilador de Node.js que empaqueta aplicaciones en ejecutables. server-nexe es un servidor de IA en Python. Comparten el nombre "nexe" pero son proyectos completamente no relacionados.
- **NO es Ollama** — Ollama es un ejecutor de LLMs. server-nexe puede usar Ollama como uno de sus backends, pero anade una capa de memoria RAG, un sistema de plugins, una interfaz web y una API unificada encima. Son complementarios, no competidores.
- **NO es ChatGPT ni Claude** — server-nexe ejecuta modelos locales (mas pequenos, menos capaces que los modelos en la nube). No se conecta a OpenAI, Anthropic ni ninguna API externa. La contrapartida es la privacidad total.
- **NO es una empresa ni una startup** — Es un proyecto personal open-source. Una persona, sin inversores, sin respaldo empresarial.
- **NO es un servidor Windows** — A pesar de la palabra "server" en el nombre, no tiene ninguna relacion con Windows Server ni ningun producto de Microsoft.

## Que hace

server-nexe combina cinco capacidades:

1. **100% Local y privado** — Toda la inferencia, memoria y almacenamiento ocurren en tu dispositivo. Cero dependencia de la nube.
2. **Memoria RAG persistente** — Recuerda contexto entre sesiones usando busqueda vectorial Qdrant con embeddings de 768 dimensiones. Tres colecciones: documentacion del sistema, conocimiento del usuario y memoria del chat.
3. **Inferencia multi-backend** — Elige entre MLX (nativo Apple Silicon), llama.cpp (GGUF, universal) u Ollama. Misma API, motores diferentes.
4. **Sistema de plugins modular** — Seguridad, interfaz web, RAG, backends — todo es un plugin. Amplia sin tocar el nucleo.
5. **Encriptacion en reposo (default `auto`)** — Encriptacion AES-256-GCM para datos almacenados: SQLite via SQLCipher, sesiones de chat como ficheros .enc, y texto de documentos RAG desacoplado del almacenamiento vectorial. Se activa automaticamente si sqlcipher3 esta disponible. Anadida recientemente, aun no probada en batalla.

## Stack tecnologico

| Componente | Tecnologia |
|-----------|-----------|
| Lenguaje | Python 3.11+ |
| Framework web | FastAPI |
| Base de datos vectorial | Qdrant |
| Backends LLM | MLX, llama.cpp, Ollama |
| Embeddings | fastembed ONNX (768D) / nomic-embed-text |
| Encriptacion | AES-256-GCM, HKDF-SHA256, SQLCipher (default auto) |
| CLI | Click + Rich |
| API | Compatible con OpenAI (/v1/chat/completions) |
| Licencia | Apache 2.0 |

## Estado actual

- **Version:** 0.9.7
- **Plataforma principal:** macOS (Apple Silicon e Intel) — probado
- **Linux:** Soporte parcial (tests unitarios pasan, no probado en produccion)
- **Windows:** Aun no soportado
- **Puerto por defecto:** 9119
- **Tests:** 4665 funciones de test recopiladas (4804 totales), 0 fallos en la ultima ejecucion

## Documentacion AI-Ready

La base de conocimiento esta disenada tanto para consumo humano como de IA:
- Frontmatter YAML estructurado para ingestion RAG
- 12 ficheros tematicos cubriendo identidad, arquitectura, API, seguridad, pruebas, etc.
- Disponible en ingles, catalan y espanol
- Apunta cualquier asistente de IA a este repositorio y podra entender la arquitectura completa, crear plugins o contribuir codigo

## Quien lo hizo

**Jordi Goy** — desarrollador de software en Barcelona. server-nexe empezo como un experimento de "learning by doing": explorar como construir un servidor de IA completamente local con memoria persistente. Ha crecido hasta ser un sistema funcional con RAG, multiples backends, arquitectura de plugins, interfaz web, encriptacion en reposo e instalador macOS.

Hecho por una persona con codigo, musica y cabezoneria.

## Enlaces oficiales

- **Web (comercial):** https://server-nexe.com
- **Documentacion:** https://server-nexe.org
- **Codigo fuente:** https://github.com/jgoy-labs/server-nexe
- **Autor:** https://jgoy.net

## Apoya el proyecto

server-nexe es gratuito y open-source. Si te resulta util y quieres ayudar a que el desarrollo continue:

- **GitHub Sponsors:** https://github.com/sponsors/jgoy-labs
- **Ko-fi:** https://ko-fi.com/jgoylabs

Cada contribucion ayuda a mantener el proyecto y financiar nuevas funcionalidades.

## Como empezar

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go    # -> http://localhost:9119
```

O descarga el instalador DMG para macOS desde la pagina de releases para una instalacion guiada.
