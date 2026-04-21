# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-usage-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Como usar server-nexe 1.0.2-beta: CLI (nexe go, nexe chat, nexe memory, nexe knowledge, nexe status), Web UI (http://localhost:9119) con thinking toggle, memoria automatica MEM_SAVE, MEM_DELETE (threshold 0.20) con confirmacion clear_all 2-turnos, subida de documentos PDF/TXT, comandos de encriptacion. Ejemplos de API con curl y Python. Como instalar modelos, cambiar idioma (NEXE_LANG), gestionar memoria."
tags: [usage, cli, web-ui, chat, memory, knowledge, upload, i18n, loading-indicator, mem-save, api-examples, use-cases, encryption, how-to, commands]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Guia de uso — server-nexe 1.0.2-beta

## Tabla de contenidos

- [Iniciar el servidor](#iniciar-el-servidor)
- [Comandos CLI](#comandos-cli)
- [Web UI](#web-ui)
  - [Funcionalidades](#funcionalidades)
  - [Subida de documentos](#subida-de-documentos)
- [MEM_SAVE — Memoria automatica](#mem_save--memoria-automatica)
  - [Borrado total (`CLEAR_ALL`) — confirmacion 2-turnos](#borrado-total-clear_all--confirmacion-2-turnos)
- [Encriptacion](#encriptacion)
- [Uso de la API](#uso-de-la-api)
  - [Chat (curl)](#chat-curl)
  - [Chat (Python)](#chat-python)
  - [Guardar en memoria](#guardar-en-memoria)
- [Casos de uso](#casos-de-uso)
- [Consejos](#consejos)

## En 30 segundos

- **CLI:** `./nexe go` arranca servidor + Qdrant + tray
- **Web UI** en `http://127.0.0.1:9119/ui` (chat, subida de documentos, sesiones)
- **API compatible con OpenAI:** `/v1/chat/completions`
- **MEM_SAVE automatico** (el modelo guarda hechos de la conversacion)
- **Menu en el system tray** para start/stop, logs, uninstall

---

## Icono de Nexe en la barra de menú (tray)

El icono de Nexe aparece junto al reloj (barra de menú de macOS). Permite controlar el servidor sin abrir ningún terminal.

**Opciones del menú:**

| Opción | Qué hace |
|--------|----------|
| Parar / Iniciar servidor | Enciende o apaga Nexe con un clic |
| Abrir Web UI | Abre el chat en el navegador (`http://127.0.0.1:9119/ui`) |
| Abrir logs | Muestra el fichero de logs si hay errores |
| Server RAM | Muestra cuánta memoria usa el modelo cargado |
| Tiempo activo | Cuánto tiempo lleva el servidor en marcha |
| Documentación | Abre la documentación oficial |
| Configuración → Desinstalar Nexe | Elimina Nexe con copia de seguridad automática |
| Salir | Para el servidor y cierra el icono del tray |

El icono es **verde** cuando el servidor está activo y **gris** cuando está parado. Se refresca cada 5 segundos.

---

## Iniciar el servidor

```bash
./nexe go    # Iniciar servidor -> http://127.0.0.1:9119
```

En macOS con la app de bandeja instalada, el servidor arranca automaticamente al iniciar sesion.

## Comandos CLI

| Comando | Descripcion |
|---------|-------------|
| `./nexe go` | Iniciar servidor (Qdrant + FastAPI + bandeja) |
| `./nexe chat` | Chat interactivo por CLI |
| `./nexe chat --rag` | Chat con memoria RAG activada |
| `./nexe chat --verbose` | Chat con detalles de peso RAG por fuente |
| `./nexe status` | Estado del servidor |
| `./nexe modules` | Listar modulos y CLIs cargados |
| `./nexe memory store "texto"` | Guardar texto en memoria |
| `./nexe memory recall "consulta"` | Buscar en memoria |
| `./nexe memory stats` | Estadisticas de memoria |
| `./nexe knowledge ingest` | Indexar documentos de la carpeta knowledge/ |
| `./nexe health` | Health check |
| `./nexe encryption status` | Comprobar estado de encriptacion |
| `./nexe encryption encrypt-all` | Migrar datos a formato encriptado |
| `./nexe encryption export-key` | Exportar clave maestra para backup |

## Web UI

Accesible en `http://127.0.0.1:9119/ui`. Requiere API key (almacenada en localStorage tras el primer login).

### Funcionalidades

- **Chat con streaming:** Streaming de tokens en tiempo real con los 3 backends
- **Indicador de carga de modelo:** Spinner azul con cronometro al cambiar de modelo. Transiciona a verde "Modelo cargado (Xs)" permanentemente en la conversacion.
- **Tamanos de modelo en el desplegable:** Muestra GB junto a cada nombre de modelo (Ollama via /api/tags, MLX via safetensors, llama.cpp via tamano del fichero gguf)
- **Panel info RAG:** Boton toggle junto al slider de umbral. Muestra explicacion de lo que hace el filtro RAG.
- **Barras de peso RAG:** Puntuaciones de relevancia con codigo de colores (verde > 0.7, amarillo 0.4-0.7, naranja < 0.4). Expandible para mostrar fuentes individuales.
- **Slider de umbral:** Ajusta el umbral de similitud RAG en tiempo real. Etiquetas: "Mas info" (umbral bajo) / "Filtro alto" (umbral alto).
- **Selector de idioma:** Desplegable en el footer CA/ES/EN. Cambia todo el texto de la UI al instante via `applyI18n()`. El servidor es la fuente de verdad (POST /ui/lang).
- **Desplegable de backend:** Muestra todos los backends configurados. Marca los backends desconectados. Auto-fallback al primer backend disponible si el seleccionado esta caido.
- **Tokens de razonamiento:** Auto-scroll de la caja de pensamiento para modelos como qwen3.5 que emiten tokens de razonamiento.
- **Thinking toggle por sesion (v0.9.9):** Icono ✨ sparkles junto al input + dropdown 🧠 en la cabecera de la sesion para activar/desactivar el modo thinking (reasoning tokens) para esa sesion. Solo disponible para familias compatibles (`THINKING_CAPABLE`: qwen3.5, qwen3, qwq, deepseek-r1, gemma3/4, llama4, gpt-oss). Default OFF. Si el modelo actual no soporta thinking, la UI muestra mensaje de aviso y ofrece retry automatico sin thinking. Endpoint interno: `PATCH /ui/session/{id}/thinking`.
- **Overlay de subida:** Spinner + temporizador + nombre de fichero durante la subida de documentos. Entrada bloqueada hasta completar. Muestra recuento de chunks y tiempo tras completar.
- **Persistencia de sesion:** API key y preferencias en localStorage. Las sesiones sobreviven a la recarga de pagina.
- **Auto-scroll:** Las cajas de chat y pensamiento hacen auto-scroll al fondo durante el streaming.
- **Sidebar colapsable:** Toggle con icono panel-left, estado persistente en localStorage. (nuevo 2026-04-01)
- **Renombrar sesiones:** Boton lapiz para renombrar inline via endpoint PATCH. (nuevo 2026-04-01)
- **Boton copiar texto:** Copia respuestas al portapapeles con feedback visual copy/check. (nuevo 2026-04-01)
- **Toggles de colecciones:** Checkboxes en la sidebar para activar/desactivar Memory/Knowledge/Docs individualmente. Persistente en localStorage. CLI: `--collections`. (nuevo 2026-04-01)
- **Pantalla de bienvenida:** Features clicables ("Chat" foca input, "Documentos" abre upload). (nuevo 2026-04-02)
- **Bloque MEM_SAVE azul:** Memorias guardadas se muestran como `<details>` azul colapsable (como thinking naranja). (nuevo 2026-04-01)
- **Aviso de documento truncado:** Notificacion amarilla cuando un documento es demasiado grande para el contexto. (nuevo 2026-04-02)
- **Modo claro/oscuro automatico:** Detecta preferencia del sistema via `matchMedia`. (existente)

### Subida de documentos

Subir documentos via el boton de clip en la entrada del chat. Soportados: .txt, .md, .pdf.

- Los documentos se indexan en la coleccion `user_knowledge` con session_id
- Solo visibles dentro de la sesion que los subio (sin contaminacion entre sesiones)
- Metadatos generados sin LLM (instantaneo, sin bloqueo de modelo)
- Muestra mensaje "Cargado (N fragmentos, Xs)" tras completar
- Los documentos se marcan "per-chat" para indicar aislamiento de sesion

## MEM_SAVE — Memoria automatica

El modelo extrae y guarda automaticamente hechos de las conversaciones:

- El usuario dice "Me llamo Jordi" -> el modelo guarda `[MEM_SAVE: name=Jordi]`
- El usuario dice "Olvida mi nombre" -> MEM_DELETE: busqueda por similitud (**threshold 0.20** desde v0.9.9, antes 0.70), borra la coincidencia mas cercana, guard anti-re-save
- Siguiente conversacion: "Como me llamo?" -> RAG recupera "name=Jordi" -> el modelo responde correctamente

No se necesitan comandos extra. Funciona tanto en CLI como en Web UI. Indicadores: badge `[MEM:N]` muestra el recuento de hechos guardados.

### Borrado total (`CLEAR_ALL`) — confirmacion 2-turnos

Si pides borrar **toda** la memoria ("borralo todo", "forget everything", "olvida todo"), el sistema **no borra inmediatamente**. Sigue un flujo de 2 turnos:

1. **Turno 1:** Detecta el patron y pide confirmacion ("¿Estas seguro? Esto borrara toda la memoria. Responde 'si' para confirmar.").
2. **Turno 2:** Si respondes `si`/`confirma`/`ok`, se ejecuta el borrado. Cualquier otra respuesta cancela la operacion.

Esto evita perdidas masivas accidentales por un mensaje ambiguo o por inyeccion desde un documento.

## Encriptacion

La encriptacion en reposo es `auto` por defecto — se activa automaticamente si `sqlcipher3` esta disponible. Para forzarla o gestionarla manualmente:

```bash
# Comprobar estado actual
./nexe encryption status

# Activar y migrar datos existentes
export NEXE_ENCRYPTION_ENABLED=true
./nexe encryption encrypt-all

# Exportar clave maestra (para backup — guardar de forma segura!)
./nexe encryption export-key
```

Que se encripta: bases de datos SQLite (memories.db via SQLCipher), sesiones de chat (.json -> .enc), texto de documentos RAG (TextStore). Los payloads de Qdrant ya no contienen texto (solo vectores + IDs).

## Uso de la API

### Chat (curl)
```bash
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hola"}], "use_rag": true}'
```

### Chat (Python)
```python
import requests

response = requests.post(
    "http://127.0.0.1:9119/v1/chat/completions",
    headers={"X-API-Key": "YOUR_KEY"},
    json={"messages": [{"role": "user", "content": "Hola"}], "use_rag": True}
)
print(response.json()["choices"][0]["message"]["content"])
```

### Guardar en memoria
```bash
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "La fecha limite del proyecto es el 30 de marzo", "collection": "user_knowledge"}'
```

## Casos de uso

Consulta **[[USE_CASES|casos de uso practicos]]** para la lista completa con contexto detallado (asistente personal, base de conocimiento privada, dev con Cursor/Continue/Zed, busqueda semantica, experimentacion con modelos, IA local segura) y guia de **cuando server-nexe NO es la mejor herramienta**.

## Consejos

- **Primera ejecucion:** La memoria esta vacia. Habla con el servidor, sube documentos, o usa `nexe knowledge ingest` para poblar el RAG.
- **Primera respuesta lenta:** La carga del modelo tarda tiempo (10-60s). El indicador de carga muestra el progreso.
- **Backend desconectado:** El servidor hace auto-fallback al primer backend disponible. Comprueba con `./nexe status`.
- **Modelos grandes:** Los modelos de 32B+ necesitan 32+ GB de RAM y pueden tardar minutos en cargar. El timeout es de 600s.
- **Encriptacion:** Activa la encriptacion pronto — migrar grandes conjuntos de datos luego lleva tiempo. Exporta y guarda la clave maestra de forma segura.
