# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-limitations

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentacion honesta de las limitaciones de server-nexe 0.8.5 pre-release. Cubre soporte de plataformas (macOS probado, Linux parcial, Windows no soportado), calidad de modelos vs nube (GPT-4/Claude), limitaciones de RAG (embeddings, chunking, arranque en frio, contradicciones), compatibilidad parcial de API OpenAI, rendimiento (instancia unica, concurrencia), restricciones de seguridad, advertencias sobre encriptacion (opt-in, nueva, no probada en batalla), y carencias funcionales (sin multi-usuario, sin sincronizacion, sin fine-tuning)."
tags: [limitations, platform, models, rag, performance, security, api, compatibility, honest, encryption]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Limitaciones — server-nexe 0.8.5 pre-release

Este documento describe honestamente lo que server-nexe no puede hacer o no hace bien.

## Plataforma

| Plataforma | Estado |
|------------|--------|
| macOS Apple Silicon | Probado, los 3 backends |
| macOS Intel | Probado, llama.cpp + Ollama (sin MLX) |
| Linux x86_64 | Parcial — tests unitarios pasan, CI verde, no probado en produccion |
| Linux ARM64 | Docker soportado, no probado directamente |
| Windows | No soportado |

## Calidad de los modelos

Los modelos locales son menos capaces que los modelos en la nube (GPT-4, Claude, etc.). Esta es la contrapartida a cambio de la privacidad.

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

- **Inyeccion de prompt:** Los modelos locales pueden seguir instrucciones inyectadas. El sanitizer detecta patrones comunes (47 patrones de jailbreak, 6 detectores de inyeccion con normalizacion Unicode) pero no todos.
- **Sin TLS por defecto:** HTTP en localhost. Usar reverse proxy para HTTPS.
- **Usuario unico:** Sin aislamiento multi-usuario. Una API key = acceso completo.
- **Auditorias IA, no auditorias externas:** La seguridad ha sido revisada por sesiones autonomas de IA, no por empresas de seguridad externas. Esto es exhaustivo pero no completo.
- **Bug Ollama keep_alive:** keep_alive:0 no siempre libera la VRAM (problema conocido de Ollama).

## Advertencias sobre encriptacion

- **Opt-in:** La encriptacion en reposo no esta activada por defecto. Los usuarios deben activarla explicitamente.
- **Funcionalidad nueva:** Anadida en v0.8.5. Probada (68 tests, 0 fallos) pero aun no probada en batalla en produccion con usuarios reales.
- **Gestion de claves:** Clave maestra almacenada en OS Keyring, variable de entorno, o fichero. Si se pierde la clave, los datos encriptados no se pueden recuperar.
- **Dependencia SQLCipher:** Requiere el paquete `sqlcipher3`. Cae a SQLite en texto plano con aviso si no esta instalado.
- **Migracion:** Migrar grandes conjuntos de datos (muchas memorias, muchas sesiones) puede llevar tiempo. Hacer backup antes de migrar.

## Carencias funcionales

- **Sin sincronizacion multi-dispositivo** — Solo local, sin sincronizacion en la nube.
- **Sin fine-tuning de modelos** — No se pueden entrenar ni ajustar modelos.
- **Sin OCR** — No se puede extraer texto de imagenes o PDFs escaneados.
- **Sin multi-usuario** — Una sola API key, sin cuentas de usuario.
- **Sin colaboracion en tiempo real** — Diseno de usuario unico y sesion unica.
- **Sin tareas programadas** — Sin automatizacion tipo cron integrada.
- **La Web UI es funcional pero basica** — No es una app de chat con todas las funciones. Tiene streaming, subidas, memoria, i18n, pero sin edicion de mensajes, sin ramificacion, sin exportacion.

## Realidad del proyecto

- **Un desarrollador** — Construido por una sola persona con desarrollo y auditoria asistidos por IA.
- **Un solo usuario real** — Solo el desarrollador lo ha usado hasta ahora. No hay feedback de usuarios externos ni pruebas multi-usuario.
- **No es de grado empresarial** — Es un proyecto personal open-source, no un producto con SLA ni garantias de soporte.
- **Desarrollo activo** — Las cosas cambian. Las APIs pueden evolucionar. La documentacion puede ir por detras del codigo.

## Lo que server-nexe NO es

- NO es un reemplazo de ChatGPT, Claude o servicios de IA en la nube
- NO es un producto empresarial con SLA
- NO es una plataforma multi-usuario
- NO se garantiza libre de bugs (es un proyecto personal open-source)
- NO es npm nexe (compilador de Node.js — completamente no relacionado)
