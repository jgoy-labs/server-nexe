# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-limitations

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentacion honesta de las limitaciones de server-nexe 0.8.2. Cubre soporte de plataformas (macOS testeado, Linux parcial, Windows no soportado), calidad de modelos vs nube (GPT-4/Claude), limitaciones de RAG (embeddings, chunking, arranque en frio, contradicciones), compatibilidad parcial de API OpenAI, rendimiento (instancia unica, concurrencia), restricciones de seguridad y carencias funcionales (sin multi-usuario, sin sincronizacion, sin fine-tuning)."
tags: [limitaciones, plataforma, modelos, rag, rendimiento, seguridad, api, compatibilidad, honesto]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Limitaciones — server-nexe 0.8.2

Este documento describe honestamente lo que server-nexe no puede hacer o no hace bien.

## Plataforma

| Plataforma | Estado |
|------------|--------|
| macOS Apple Silicon | Testeado, los 3 backends |
| macOS Intel | Testeado, llama.cpp + Ollama (sin MLX) |
| Linux x86_64 | Parcial — tests unitarios pasan (3901/3901), CI verde, no testeado en produccion |
| Linux ARM64 | Docker soportado, no testeado directamente |
| Windows | No soportado |

## Calidad de los modelos

Los modelos locales son menos capaces que los modelos en la nube (GPT-4, Claude, etc.). Este es el compromiso a cambio de la privacidad.

- **Modelos pequenos (2-4B):** Buenos para tareas simples, respuestas cortas. Razonamiento limitado.
- **Modelos medianos (7-8B):** Adecuados para la mayoria de tareas cotidianas. Alucinaciones ocasionales.
- **Modelos grandes (32B+):** Buena calidad, pero requieren 32+ GB de RAM y carga lenta.
- **Catalan:** Los modelos Salamandra (BSC/AINA) son los mejores para catalan. Otros modelos tienen soporte limitado de catalan.

## Limitaciones del RAG

- **Homonimos:** "banco" (asiento) vs "banco" (finanzas) obtienen embeddings similares. Misma palabra, diferentes significados.
- **Negaciones:** "No me gusta Python" ≈ "Me gusta Python" en el espacio de embeddings.
- **Arranque en frio:** Memoria vacia = el RAG no aporta nada. Es necesario poblarla primero.
- **Fallos de Top-K:** Si tienes muchos datos, la informacion relevante puede no estar en los Top-3/5 resultados.
- **Informacion contradictoria:** El RAG puede recuperar hechos conflictivos de diferentes periodos temporales.
- **Limites de chunk:** La informacion dividida entre limites de chunks puede recuperarse parcialmente.
- **Modelo de embeddings:** Los vectores de 768 dimensiones capturan el significado bien pero no perfectamente. El vocabulario de dominios especializados puede tener menor precision.

## Compatibilidad de API

Parcialmente compatible con el formato de API de OpenAI:

| Funcionalidad | Estado |
|---------------|--------|
| /v1/chat/completions | Funcional (messages, temperature, max_tokens, stream) |
| /v1/embeddings (estandar) | No implementado (usar /v1/embeddings/encode en su lugar) |
| /v1/models | No implementado |
| /v1/completions (legacy) | No implementado |
| /v1/fine-tuning | No implementado |
| Function calling | No implementado |
| Vision/multimodal | No implementado |

## Rendimiento

- **Instancia unica:** Un proceso de servidor, sin cluster.
- **Concurrencia:** Limitada por la inferencia del modelo (una peticion a la vez por backend).
- **Tiempo de arranque:** 5-15 segundos (Qdrant + carga de modulos + ingestion de conocimiento en la primera ejecucion).
- **Carga de modelo:** 10-60 segundos dependiendo del tamano del modelo y el backend.
- **Consumo de RAM:** Modelo + Qdrant + Python = significativo. 8GB de RAM es justo para modelos 7B.
- **Disco:** Modelos (1-40 GB) + vectores Qdrant + logs. Estimar 10-50 GB en total.

## Seguridad

- **Inyeccion de prompt:** Los modelos locales pueden seguir instrucciones inyectadas. El sanitizer detecta patrones comunes (69 patrones jailbreak) pero no todos.
- **Sin TLS por defecto:** HTTP en localhost. Usar reverse proxy para HTTPS.
- **Usuario unico:** Sin aislamiento multi-usuario. Una API key = acceso completo.
- **Qdrant sin cifrar:** Vectores en disco en texto plano. Usar cifrado de disco.
- **Bug de Ollama keep_alive:** keep_alive:0 no siempre libera la VRAM (problema conocido de Ollama).

## Carencias funcionales

- **Sin sincronizacion multi-dispositivo** — Solo local, sin sincronizacion en la nube.
- **Sin fine-tuning de modelos** — No se pueden entrenar ni ajustar modelos.
- **Sin OCR** — No se puede extraer texto de imagenes o PDFs escaneados.
- **Sin multi-usuario** — Una sola API key, sin cuentas de usuario.
- **Sin colaboracion en tiempo real** — Diseno de usuario unico y sesion unica.
- **Sin tareas programadas** — Sin automatizacion tipo cron integrada.
- **La Web UI es funcional pero basica** — No es una app de chat con todas las funciones. Tiene streaming, subidas, memoria, i18n, pero sin edicion de mensajes, sin ramificacion, sin exportacion.

## Lo que server-nexe NO es

- NO es un reemplazo de ChatGPT, Claude o servicios de IA en la nube
- NO es un producto enterprise con SLA
- NO es una plataforma multi-usuario
- NO se garantiza libre de bugs (es un proyecto personal open-source)
- NO es npm nexe (compilador de Node.js — completamente no relacionado)
