# === METADATA RAG ===
versio: "2.0"
data: 2026-04-02
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Como usar server-nexe: CLI (nexe go, nexe chat, nexe memory, nexe knowledge, nexe status), Web UI (http://localhost:9119), memoria automatica MEM_SAVE, subida de documentos PDF/TXT, comandos de encriptacion. Ejemplos de API con curl y Python. Como instalar modelos, cambiar idioma (NEXE_LANG), gestionar memoria."
tags: [usage, cli, web-ui, chat, memory, knowledge, upload, i18n, loading-indicator, mem-save, api-examples, use-cases, encryption, how-to, commands]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Guia de uso — server-nexe 0.9.0 pre-release

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
- El usuario dice "Olvida mi nombre" -> MEM_DELETE: busqueda por similitud (threshold 0.70), borra la coincidencia mas cercana, guard anti-re-save
- Siguiente conversacion: "Como me llamo?" -> RAG recupera "name=Jordi" -> el modelo responde correctamente

No se necesitan comandos extra. Funciona tanto en CLI como en Web UI. Indicadores: badge `[MEM:N]` muestra el recuento de hechos guardados.

## Encriptacion

La encriptacion en reposo es opt-in. Activala para encriptar tus datos almacenados:

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

## Casos de uso practicos

1. **Asistente personal con memoria:** Pregunta sobre tus proyectos, preferencias, fechas limite. MEM_SAVE recuerda el contexto automaticamente.
2. **Base de conocimiento privada:** Sube documentos tecnicos, consultalos en lenguaje natural. Aislado por sesion en cada conversacion.
3. **Desarrollo asistido por IA:** La API compatible con OpenAI funciona con Cursor, Continue, Zed. Apuntalos a http://127.0.0.1:9119/v1.
4. **Busqueda semantica:** Usa /v1/memory/search para recuperacion de documentos basada en similitud sin coincidencia exacta de palabras clave.
5. **Experimentacion con modelos:** Cambia entre backends MLX, llama.cpp y Ollama para comparar velocidad y calidad.
6. **IA local segura:** Activa la encriptacion en reposo para manejar datos sensibles sin ninguna dependencia de la nube.

## Consejos

- **Primera ejecucion:** La memoria esta vacia. Habla con el servidor, sube documentos, o usa `nexe knowledge ingest` para poblar el RAG.
- **Primera respuesta lenta:** La carga del modelo tarda tiempo (10-60s). El indicador de carga muestra el progreso.
- **Backend desconectado:** El servidor hace auto-fallback al primer backend disponible. Comprueba con `./nexe status`.
- **Modelos grandes:** Los modelos de 32B+ necesitan 32+ GB de RAM y pueden tardar minutos en cargar. El timeout es de 600s.
- **Encriptacion:** Activa la encriptacion pronto — migrar grandes conjuntos de datos luego lleva tiempo. Exporta y guarda la clave maestra de forma segura.
