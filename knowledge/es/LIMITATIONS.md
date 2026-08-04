# === METADATA RAG ===
versio: "2.0"
data: 2026-07-04
id: nexe-limitations
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentacion honesta de las limitaciones de server-nexe 1.0.7. Cubre soporte de plataformas (macOS 14+ Apple Silicon, Linux ARM64, Windows ARM64 (nuevo en 1.0.7; installer sin firmar — SmartScreen avisa; backend Ollama), Intel NO soportado), calidad de modelos vs nube (GPT-4/Claude), limitaciones de RAG (embeddings, chunking, arranque en frio, contradicciones), compatibilidad parcial de API OpenAI, rendimiento (instancia unica, concurrencia), restricciones de seguridad, advertencias sobre encriptacion (default auto, nueva, no probada en batalla), y carencias funcionales (sin multi-usuario, sin sincronizacion, sin fine-tuning)."
tags: [limitations, platform, models, rag, performance, security, api, compatibility, honest, encryption]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Limitaciones — server-nexe 1.0.7

Este documento describe honestamente lo que server-nexe no puede hacer o no hace bien.

## Plataforma

| Plataforma | Estado |
|------------|--------|
| macOS 14 Sonoma+ Apple Silicon (M1+) | **Target principal** — probado, los 3 backends |
| macOS 13 Ventura | **NO soportado** (eliminado en v0.9.9 por dependencias arm64-only del stack) |
| macOS Intel | **NO soportado** (eliminado en v0.9.9 — wheels arm64-only, sin MLX) |
| Linux ARM64 | Soportado (Ollama, CPU) — testeado en VM Ubuntu 24.04 ARM64 (UTM). Instalacion CLI o nexe-app (Tauri). Rutas XDG. |
| Linux x86_64 | Soportado (Ollama, CPU) — tests unitarios pasan, CLI validada. |
| Windows ARM64 | Soportado desde v1.0.7 (**NUEVO**) — installer NSIS (WebView2, wizard ca/es/en); solo backend Ollama; installer sin firmar — SmartScreen avisa |

## Calidad de los modelos

Los modelos locales son menos capaces que los modelos en la nube (GPT-4, Claude, etc.). Esta es la contrapartida a cambio de la privacidad.

- **Modelos pequenos (2-4B):** Buenos para tareas simples, respuestas cortas. Razonamiento limitado.
- **Modelos medianos (7-8B):** Adecuados para la mayoria de tareas cotidianas. Alucinaciones ocasionales.
- **Modelos grandes (32B+):** Buena calidad, pero requieren 32+ GB de RAM y carga lenta.
- **Catalan:** Los modelos Salamandra (BSC/AINA) son los mejores para catalan. Otros modelos tienen soporte limitado de catalan.

### Repeticion en respuestas largas encadenadas (modelos pequenos)

En generaciones largas encadenadas — pedir un texto muy detallado y despues
decir "continua" un par de veces — **los modelos pequenos se repiten**: reemiten
el mismo parrafo o el mismo elemento de lista varias veces seguidas, y a veces
vuelven atras a una seccion ya escrita.

Medido con el mismo patron de conversacion (4 turnos, 2048 tokens por respuesta,
3 repeticiones) sobre la familia Qwen3.5, contando elementos de lista identicos
repetidos dentro de una respuesta:

| Modelo | Turnos con repeticion literal |
|---|---|
| 2B | 8 de 12 |
| 4B | 3 de 12 |
| 9B | **0 de 12** |
| 27B | **0 de 12** |

- **No es un defecto de server-nexe.** Se reproduce igual con el motor pelado,
  sin RAG, sin memoria, sin compactacion de contexto y sin reuso de cache.
- **No se arregla con `repetition_penalty`:** medido a 1,05 y 1,10 sin ninguna
  diferencia.
- **Que hacer:** para textos largos encadenados, usar **9B o superior**. Con
  modelos de 2-4B, es mejor pedir secciones cortas en preguntas separadas que un
  texto largo con "continua".

## Modelos multimodales (VLM)

El backend MLX soporta modelos de vision (imagen + texto) via `mlx-vlm 0.4.4`. Lista de arquitecturas detectadas: Qwen2-VL, Qwen2.5-VL, Qwen3-VL, Llava (todos), Gemma-3/4, PaliGemma, InternVL, MiniCPMV, Idefics2/3, Mllama y mas. Desde **v0.9.8** el detector "any-of" de 3 senales (architectures + vision_config en el `config.json` + weight_map en el `model.safetensors.index.json`) cubre arquitecturas nuevas sin claves clasicas.

Limitaciones actuales:
- **Familia Qwen3.5 (Omni VLM, tamanos 2B/4B/9B/27B):** Funciona via MLX y Ollama con vision. El bundle DMG y el venv de dev incluyen `PyTorch` + `torchvision` (wheels cp312 macOS-arm64, ~92 MB net). El detector VLM detecta arquitectura `Qwen3_5MoeForConditionalGeneration` + `vision_config` y carga via `mlx-vlm.load()`. Verificado empiricamente 2026-05-13 con `qwen3.5:4b` describiendo imagenes correctamente. **Aun no soportados en el pipeline:** `Qwen3-Omni` y `Kimi-VL` (audio/video branch en `mlx-vlm` no expuesto).
- **Modelo por defecto recomendado:** `gemma4:e4b` (4.5 GB) o `gemma4:31b` (18.5 GB). Imagen only, sin dependencias torch.
- **Audio/voz:** No soportado. Modelos como Qwen3-Omni, Kimi-VL o DeepSeek-VL-V2 tienen rama de audio en `mlx-vlm` pero el pipeline de server-nexe aun no lo expone.
- **Video nativamente:** No soportado (ver modelos omni).

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
| Vision/multimodal | Implementado desde v0.9.7 (Ollama, MLX, llama.cpp, Web UI) |

## Rendimiento

- **Instancia unica:** Un proceso de servidor, sin cluster.
- **Concurrencia:** Limitada por la inferencia del modelo (una peticion a la vez por backend).
- **Tiempo de arranque:** 5-15 segundos (Qdrant + carga de modulos + ingestion de conocimiento en la primera ejecucion).
- **Carga de modelo:** 10-60 segundos dependiendo del tamano del modelo y el backend.
- **Consumo de RAM:** Modelo + Qdrant + Python = significativo. 8GB de RAM es justo para modelos 7B.
- **Disco:** Modelos (1-40 GB) + vectores Qdrant + logs. Estimar 10-50 GB en total.

## Seguridad

- **Inyeccion de prompt:** Los modelos locales pueden seguir instrucciones inyectadas. El sanitizer detecta patrones comunes (49 patrones de jailbreak, 6 detectores de inyeccion con normalizacion Unicode) pero no todos.
- **Sin TLS por defecto:** HTTP en localhost. Usar reverse proxy para HTTPS.
- **Usuario unico:** Sin aislamiento multi-usuario. Una API key = acceso completo.
- **Auditorias IA, no auditorias externas:** La seguridad ha sido revisada por sesiones autonomas de IA, no por empresas de seguridad externas. Esto es exhaustivo pero no completo.
- **Bug Ollama keep_alive:** keep_alive:0 no siempre libera la VRAM (problema conocido de Ollama).

## Advertencias sobre encriptacion

- **Default `auto`:** La encriptacion en reposo se activa automaticamente si `sqlcipher3` esta disponible. Se puede forzar con `NEXE_ENCRYPTION_ENABLED=true` o desactivar con `false`.
- **Funcionalidad nueva:** Anadida en v0.9.0, disponible desde v0.9.7. Probada (72 tests, 0 fallos) pero aun no probada en batalla en produccion con usuarios reales.
- **Gestion de claves:** Clave maestra almacenada en OS Keyring, variable de entorno, o fichero. Si se pierde la clave, los datos encriptados no se pueden recuperar.
- **Dependencia SQLCipher:** Requiere el paquete de Python `sqlcipher3` — instala `sqlcipher3-binary` (wheel precompilado, recomendado) o `sqlcipher3` (necesita `libsqlcipher`, p. ej. via Homebrew en macOS). Cae a SQLite en texto plano con aviso si no esta instalado.
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
