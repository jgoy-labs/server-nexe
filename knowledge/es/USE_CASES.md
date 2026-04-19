# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-use-cases
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Casos de uso practicos de server-nexe 1.0.1-beta: asistente personal con memoria, base de conocimiento privada, desarrollo asistido (Cursor/Continue/Zed), busqueda semantica, experimentacion con backends, IA local segura para compliance. Incluye guia de cuando server-nexe tiene sentido (privacidad, offline, control) y cuando NO (multi-usuario, modelos frontier, hardware limitado, fine-tuning, SLA)."
tags: [use-cases, casos-de-uso, asistente, rag, cursor, continue, zed, api, privacy, privacidad, local, compliance]
chunk_size: 600
priority: P2

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Casos de uso — server-nexe 1.0.1-beta

server-nexe esta pensado para escenarios donde **privacidad, control local y memoria persistente** tienen valor concreto. Esta es la lista de los casos de uso mas probados, con contexto practico para cada uno.

## 1. Asistente personal con memoria

**Para quien:** usuarios que quieren un asistente que aprenda de sus conversaciones sin enviar datos a la nube.

Pregunta sobre proyectos en curso, preferencias, fechas limite. El sistema **MEM_SAVE** recuerda el contexto automaticamente (nombres, trabajos, plazos, decisiones) y lo recupera en sesiones futuras via RAG. La memoria es persistente, encriptada en reposo, y solo vive en tu dispositivo.

**Ejemplo:** "Recuerda que el proximo lunes tengo reunion con Xiri." → Semanas despues: *"¿Cuando quede con Xiri?"* → el sistema lo recuerda.

## 2. Base de conocimiento privada

**Para quien:** profesionales que trabajan con documentos sensibles (legal, medico, consultoria) y no pueden subirlos a servicios cloud.

Sube `.txt`, `.md` o `.pdf` y se indexan automaticamente en el RAG. Consultalos en lenguaje natural. Cada documento queda **aislado por sesion** — no se cruza contexto entre conversaciones sin querer.

**Ejemplo:** sube contratos y pregunta *"¿Que clausulas de rescision mencionan penalizacion economica?"*

## 3. Desarrollo asistido por IA (Cursor, Continue, Zed)

**Para quien:** desarrolladores que quieren IA en su IDE sin enviar codigo propietario a terceros.

La API compatible con OpenAI (`/v1/chat/completions`) funciona con cualquier herramienta que acepte un endpoint OpenAI-like. Configura la URL base a `http://127.0.0.1:9119/v1` y la clave API de tu `.env`.

**Ejemplo config Cursor:** Settings → Models → Add Model → OpenAI-compatible → Base URL `http://127.0.0.1:9119/v1` + cabecera `X-API-Key` con el valor de `NEXE_PRIMARY_API_KEY`.

## 4. Busqueda semantica

**Para quien:** equipos que quieren buscar documentos por *significado*, no por palabras clave exactas.

`POST /v1/memory/search` devuelve los fragmentos mas similares a tu consulta, con puntuacion de similitud. Los embeddings multilingues (fastembed, 768-dim, ONNX) funcionan en catalan, castellano e ingles sin cambiar la config.

**Ejemplo:** busca *"como hacer el deploy"* → encuentra docs que hablan de *"publicacion"*, *"release process"*, *"push a produccion"*, *"despliegue"*, etc.

## 5. Experimentacion con modelos

**Para quien:** usuarios que quieren comparar empiricamente velocidad y calidad de distintos backends y modelos locales.

Cambia entre **MLX** (nativo Apple Silicon), **llama.cpp** (GGUF universal) y **Ollama** (gestion facil) con un cambio de config. Catalogo de 16 modelos en 4 tiers de RAM — desde Gemma 3 4B hasta ALIA-40B.

**Ejemplo:** prueba Qwen3.5 9B (Ollama, tier_16) vs Gemma 4 E4B (MLX, tier_16) para saber cual encaja mejor con tu hardware y caso de uso.

## 6. IA local segura (compliance, datos sensibles)

**Para quien:** organizaciones con requisitos de compliance (RGPD, HIPAA, secreto profesional) que no pueden enviar datos a un proveedor externo.

Activa la encriptacion en reposo (`NEXE_ENCRYPTION_ENABLED=auto`, fail-closed desde v0.9.2) y todos los datos quedan cifrados con AES-256-GCM: base de datos SQLite (via SQLCipher), sesiones de chat (`.enc`) y texto de documentos RAG.

**Nota compliance:** server-nexe NO ha pasado certificaciones externas. La encriptacion es fuerte pero el sistema es un proyecto open-source de un desarrollador, no un producto enterprise con auditorias profesionales.

---

## Cuando server-nexe NO es la mejor herramienta

Se honesto sobre las limitaciones. Hay casos de uso donde otras opciones son mejores:

| Si necesitas... | Prueba... |
|-----------------|-----------|
| Modelos frontier (GPT-5, Claude Opus 4.5, Gemini 3) | Servicios cloud oficiales — los modelos locales aun son menos capaces |
| Multi-usuario con sync entre dispositivos | server-nexe es **mono-usuario por diseno**. Considera un despliegue client-server externo |
| Soporte Windows o Linux arm64 de produccion | server-nexe requiere **macOS 14+ Apple Silicon** desde v0.9.9 |
| Fine-tuning o entrenamiento de modelos | No es funcion de server-nexe. Usa MLX, transformers o Axolotl directamente |
| Garantia de uptime y SLA | Es un proyecto open-source mantenido por una persona — no hay SLA |
| Auditoria de seguridad profesional | Las auditorias actuales son IA-asistidas (Claude, Gemini, Codex), no por empresas humanas especializadas |

## Referencias

- [[INSTALLATION|Como instalar]] — metodos DMG y CLI
- [[API|API completa]] — todos los endpoints
- [[USAGE|Uso diario]] — comandos CLI y Web UI
- [[IDENTITY|Que es server-nexe]]
- [[LIMITATIONS|Limitaciones tecnicas]]
