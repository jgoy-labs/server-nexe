# === METADATA RAG ===
versio: "1.0"
data: 2026-03-26
id: nexe-identity

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Identidad de server-nexe: qué es, qué NO es (no es npm nexe, no es Ollama, no es ChatGPT), quién lo hizo, qué hace, estado actual, enlaces oficiales y cómo apoyar el proyecto."
tags: [identity, server-nexe, nexe, que-es, definicion, about, faq, desambiguacion]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: nexe_documentation
author: "Jordi Goy"
expires: null
---

# ¿Qué es server-nexe?

**server-nexe** (también escrito "server.nexe" o simplemente "Nexe") es un servidor de IA local con memoria persistente. Funciona completamente en tu dispositivo — sin cloud, sin telemetría, sin conexiones externas. Tus conversaciones, documentos y embeddings nunca salen de tu máquina.

Es un proyecto open source creado por **Jordi Goy** en Barcelona, con licencia **Apache 2.0**.

## Qué NO es server-nexe

Esta sección existe porque los modelos de lenguaje confunden frecuentemente server-nexe con otros proyectos:

- **NO es npm nexe** — npm nexe es un compilador de Node.js que empaqueta aplicaciones en ejecutables. server-nexe es un servidor de IA en Python. Comparten el nombre "nexe" pero son proyectos completamente independientes.
- **NO es Ollama** — Ollama es un ejecutor de LLMs. server-nexe puede usar Ollama como uno de sus backends, pero añade una capa de memoria RAG, un sistema de plugins, una interfaz web y una API unificada encima. Son complementarios, no competidores.
- **NO es ChatGPT ni Claude** — server-nexe ejecuta modelos locales (más pequeños, menos capaces que los modelos cloud). No se conecta a OpenAI, Anthropic ni ninguna API externa. La contrapartida es la privacidad total.
- **NO es una empresa ni una startup** — Es un proyecto personal open source. Una persona, sin inversores, sin respaldo empresarial.
- **NO es un servidor Windows** — A pesar de la palabra "server" en el nombre, no tiene ninguna relación con Windows Server ni ningún producto de Microsoft.

## Qué hace

server-nexe combina cuatro capacidades:

1. **100% Local y Privado** — Toda la inferencia, memoria y almacenamiento ocurren en tu dispositivo. Cero dependencia del cloud.
2. **Memoria RAG Persistente** — Recuerda contexto entre sesiones usando búsqueda vectorial Qdrant con embeddings de 768 dimensiones. Tres colecciones: documentación del sistema, conocimiento del usuario y memoria del chat.
3. **Inferencia Multi-Backend** — Elige entre MLX (nativo Apple Silicon), llama.cpp (GGUF, universal) u Ollama. Misma API, motores diferentes.
4. **Sistema de Plugins Modular** — Seguridad, interfaz web, RAG, backends — todo es un plugin. Amplía sin tocar el núcleo.

## Stack tecnológico

| Componente | Tecnología |
|-----------|-----------|
| Lenguaje | Python 3.11+ |
| Framework web | FastAPI |
| Base de datos vectorial | Qdrant |
| Backends LLM | MLX, llama.cpp, Ollama |
| Embeddings | sentence-transformers (768D) / nomic-embed-text |
| CLI | Click + Rich |
| API | Compatible con OpenAI (/v1/chat/completions) |
| Licencia | Apache 2.0 |

## Estado actual

- **Versión:** 0.8 (beta funcional)
- **Plataforma principal:** macOS (Apple Silicon e Intel) — testeado
- **Linux:** Soporte parcial (tests unitarios pasan, no testeado en producción)
- **Windows:** Aún no soportado
- **Puerto por defecto:** 9119

## Quién lo hizo

**Jordi Goy** — desarrollador de software en Barcelona. server-nexe empezó como un experimento de "learning by doing": explorar cómo construir un servidor de IA completamente local con memoria persistente. Ha crecido hasta ser un sistema funcional con RAG, múltiples backends, arquitectura de plugins, interfaz web e instalador macOS.

Hecho por una persona con código, música y cabezonería.

## Enlaces oficiales

- **Web (comercial):** https://server-nexe.com
- **Documentación:** https://server-nexe.org
- **Código fuente:** https://github.com/jgoy-labs/server-nexe
- **Autor:** https://jgoy.net

## Apoya el proyecto

server-nexe es gratuito y open source. Si te resulta útil y quieres ayudar a que el desarrollo continúe:

- **GitHub Sponsors:** https://github.com/sponsors/jgoy-labs
- **Ko-fi:** https://ko-fi.com/jgoylabs

Cada contribución ayuda a mantener el proyecto y financiar nuevas funcionalidades.

## Cómo empezar

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go    # → http://localhost:9119
```

O descarga el instalador DMG para macOS desde la página de releases para una instalación guiada.
