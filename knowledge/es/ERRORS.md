# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-errors-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Errores comunes y soluciones para server-nexe 1.0.2-beta. Cubre errores de instalacion, arranque del servidor, Web UI, autenticacion API, carga de modelos, memoria/RAG, streaming, errores de encriptacion y fixes de Bug #19 (MEK fallback, personal_memory wipe)."
tags: [errors, troubleshooting, debugging, installation, startup, web-ui, api, models, memory, streaming, encryption]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Errores comunes — server-nexe 1.0.2-beta

## Errores de instalacion

| Error | Causa | Solucion |
|-------|-------|----------|
| Python 3.11+ not found | Python del sistema demasiado antiguo | Instalar Python 3.11+ via Homebrew, o usar el instalador DMG (incluye 3.12) |
| Permission denied on setup.sh | Falta permiso de ejecucion | `chmod +x setup.sh` |
| ModuleNotFoundError | Dependencias no instaladas | Activar venv: `source venv/bin/activate`, luego `pip install -r requirements.txt` |
| rumps import error on Linux | Dependencia exclusiva de macOS | Normal en Linux — rumps esta en requirements-macos.txt, no en requirements.txt |

## Errores de arranque del servidor

| Error | Causa | Solucion |
|-------|-------|----------|
| Port 9119 already in use | Otro proceso en ese puerto | `lsof -i :9119` y matar, o cambiar puerto en server.toml |
| Qdrant connection refused | Qdrant embedded no se ha inicializado correctamente | Reinicia el servidor con `./nexe go`. Si persiste, revisa los logs en `storage/logs/`. |
| Ollama not available | Ollama no instalado o no ejecutandose | Instalar desde ollama.com. El servidor auto-arrancara Ollama al iniciar. |
| asyncio.Lock deadlock | Problema de event loop en Python 3.12 | Corregido en v0.8.2 via inicializacion lazy en module_lifecycle.py. Actualizar a la ultima version. |
| Servidor ya en ejecucion (PID X) | Otra instancia activa del servidor | Usa "Quit" en el tray, o `pkill -9 server-nexe`. Verifica: `lsof -iTCP:9119` |
| Servidor huerfano (Quit del tray no funciona) | Bug pre-v0.9.0 (corregido) — el tray no enviaba SIGTERM al servidor | Actualizar a v0.9.9. Workaround: `pkill -f "core.app"` o `lsof -iTCP:9119 -sTCP:LISTEN` → `kill -9 <PID>` |

## Errores de Web UI

| Error | Causa | Solucion |
|-------|-------|----------|
| 401 Unauthorized | API key incorrecta o ausente | Comprobar que la clave en localStorage coincide con `.env` NEXE_PRIMARY_API_KEY |
| 403 CSRF | Discrepancia de token CSRF | Limpiar cache del navegador y recargar |
| Chat not responding | Modelo cargandose (primer mensaje) | Esperar al indicador de carga. Puede tardar 10-60s en la primera carga. |
| Streaming stops at 2nd message | Bug de _renderTimer (pre-v0.8.2) | Corregido en v0.8.2. Actualizar a la ultima version. |
| Old JS/CSS cached | Cache agresiva del navegador | Corregido con cache-busting (?v=timestamp). Recarga forzada: Cmd+Shift+R |
| 429 Too Many Requests | Rate limit excedido | Esperar y reintentar. Limites por endpoint (5-30/min para UI). |

## Errores de API

| Error | Causa | Solucion |
|-------|-------|----------|
| 401 Missing X-API-Key | Sin cabecera de autenticacion | Anadir `-H "X-API-Key: YOUR_KEY"` a la peticion |
| 429 Rate Limited | Demasiadas peticiones | Esperar y reintentar. Comprobar limites de rate en `.env` |
| 408 Timeout | Inferencia del modelo demasiado lenta | Aumentar timeout de NEXE_DEFAULT_MAX_TOKENS. Los modelos grandes necesitan 600s. |
| Empty error message | httpx.ReadTimeout tiene str() vacio | Corregido con repr(e). Comprobar logs del servidor. |

## Errores de modelo

| Error | Causa | Solucion |
|-------|-------|----------|
| OOM Killed | Modelo demasiado grande para la RAM | Usar modelo mas pequeno. 8GB RAM -> modelos 2B maximo. |
| Model loading very slow | Modelo grande o GPU fria | Normal para modelos 32B+. El indicador de carga muestra el progreso. |
| MLX not available | Mac Intel o Linux | MLX es solo para Apple Silicon. Usar llama.cpp u Ollama. |
| Qwen3.5 fails on MLX (versiones < v0.9.7) | Modelo multimodal incompatible | Desde v0.9.7 el backend MLX soporta VLM via mlx_vlm. Desde v0.9.8 el detector "any-of" cubre mas arquitecturas. Si falla, usar el backend Ollama como alternativa. |

## Errores de memoria/RAG

| Error | Causa | Solucion |
|-------|-------|----------|
| RAG returns nothing | Memoria vacia (arranque en frio) | Subir documentos, usar `nexe knowledge ingest`, o chatear para poblar MEM_SAVE. |
| Wrong RAG results | Umbral demasiado alto | Bajar umbral via el slider de la UI o variables de entorno NEXE_RAG_*_THRESHOLD. |
| Duplicate memories | Problema de umbral de deduplicacion | La deduplicacion comprueba similitud > 0.80. Entradas muy similares pero diferentes pueden guardarse ambas. |
| Documents not visible | Sesion incorrecta | Los documentos estan aislados por sesion. Subir en la misma sesion donde estas chateando. |

## Errores de encriptacion

| Error | Causa | Solucion |
|-------|-------|----------|
| Keyring not available | Keyring del SO no configurado (Linux sin Secret Service) | Configurar variable de entorno `NEXE_MASTER_KEY` o crear fichero `~/.nexe/master.key` (chmod 600) |
| sqlcipher3 not installed | Dependencia faltante | `pip install sqlcipher3`. Cae a SQLite en texto plano con aviso. |
| Cannot decrypt data | Clave maestra incorrecta | Asegurar que se usa la misma clave. Exportar con `./nexe encryption export-key`. |
| Migration failed | Base de datos corrupta o migracion interrumpida | El fichero de backup .bak se preserva. Restaurar desde backup y reintentar. |
| Encryption status: disabled | Funcionalidad no activada | Configurar `NEXE_ENCRYPTION_ENABLED=true` en .env o en el entorno |

## Errores historicos corregidos en v0.9.9

### Bug #18 — MEM_DELETE no borraba hechos (P0)

**Sintoma (pre-v0.9.9):** El usuario decia "olvida que me llamo Jordi" y el sistema no borraba el hecho de la memoria. El DELETE_THRESHOLD de `0.70` era demasiado alto y ninguna coincidencia superaba el umbral.

**Fix (v0.9.9):**
- **`DELETE_THRESHOLD` ajustado de `0.70` a `0.20`** (descubierto empiricamente con 8 tests e2e reales contra Qdrant embedded + fastembed).
- **`_filter_rag_injection`** neutraliza patrones `[MEM_SAVE:…]`, `[MEM_DELETE:…]`, `[OLVIDA|OBLIT|FORGET:…]`, `[MEMORIA:…]` tanto en ingest como en retrieval para evitar que el modelo auto-borre por efecto rebote.
- **Confirmacion `clear_all` en 2 turnos:** si el usuario pide borrar TODO (no un hecho concreto), el sistema pide confirmacion en el siguiente turno (`session._pending_clear_all`). Evita perdidas masivas accidentales.

### Bug #19a — `personal_memory` se wipeaba al reiniciar

**Sintoma (pre-v0.9.9):** Cada reinicio del servidor disparaba una rama defensiva de "dim-check" que borraba silenciosamente la coleccion `personal_memory`. Los usuarios perdian la memoria entre sesiones.

**Fix (v0.9.9):** Eliminada la rama defensiva. Ahora la memoria persiste entre reinicios sin autorizacion explicita del usuario.

### Bug #19b — sesiones `.enc` sobreviven al reset del Keychain

**Sintoma (pre-v0.9.9):** Si el usuario reiniciaba el Keychain de macOS (o lo perdia), el CryptoProvider no podia recuperar la MEK (Master Encryption Key) y las sesiones `.enc` quedaban irrecuperables aunque `~/.nexe/master.key` estuviera en disco.

**Fix (v0.9.9):** MEK fallback order corregido a **file → keyring → env → generate**. Si el fichero local existe, se usa primero (antes fallaba directamente a keyring). Esto permite que las sesiones `.enc` sobrevivan a un reset de Keychain siempre que `~/.nexe/master.key` este intacto.

| Error | Causa | Solucion |
|-------|-------|----------|
| Memoria perdida tras reiniciar (pre-v0.9.9) | Bug #19a | Actualizar a v0.9.9. Sin workaround retroactivo: la memoria ya se habia perdido. |
| Sesiones .enc no desencriptan tras reset Keychain (pre-v0.9.9) | Bug #19b | Actualizar a v0.9.9. Si tienes el fichero `~/.nexe/master.key` o la variable de entorno `NEXE_MASTER_KEY`, ahora se recupera automaticamente. |

## Como reportar un error

Si te encuentras con un error que no esta cubierto en esta pagina (o que persiste a pesar del workaround), puedes reportarlo. Sigue estos 3 pasos.

### 1. Recoger evidencias desde el System Tray

El menu del tray (ver `INSTALLATION.md` — App de bandeja (NexeTray, macOS)) tiene acceso directo a los logs:

1. Abre el menu del tray (icono `server.nexe` en la barra de menu).
2. Haz clic en **"Abrir logs"** → abre `storage/logs/server.log` en el editor asociado a `.log`.
3. Identifica las lineas relevantes — normalmente las ultimas **50-100 lineas** antes del momento del error.
4. **Alternativa**: copia el log completo si quieres dar maximo contexto para el triaje.

### 2. ⚠️ Privacidad: revisa el log ANTES de enviarlo

**El log puede contener datos personales tuyos** porque captura la actividad real del servidor:

| Tipo de dato | Donde puede aparecer en el log |
|--------------|-------------------------------|
| **Conversaciones** | Fragmentos de mensajes que has enviado al chat (truncados a 200 caracteres por defecto, pero aun legibles) |
| **Resultados RAG** | Trozos de documentos que has subido (`.txt`, `.md`, `.pdf`) |
| **Memoria personal** | Hechos almacenados via MEM_SAVE (nombres, preferencias, proyectos) |
| **Paths locales** | `/Users/tu/...` y nombres de carpetas de tu equipo |
| **Session IDs** | Identificadores de actividad (util para correlacion, no personal per se) |
| **Stack traces** | Pueden incluir rutas internas de tu instalacion |

**Antes de enviar**, revisa y:
- Borra u ofusca nombres propios y datos sensibles
- Sustituye paths privados por `[PATH]` o `~/server-nexe/`
- Considera si quieres compartir el log completo o solo el fragmento relevante
- **Nunca compartas** `~/.nexe/master.key` ni el valor de `NEXE_MASTER_KEY` ni `NEXE_PRIMARY_API_KEY`

### 3. Canales de report

| Canal | Mejor para |
|-------|-----------|
| **GitHub Issues** · `github.com/jgoy-labs/server-nexe/issues` | Bugs tecnicos, stack traces, regressions, crashes. Requiere cuenta GitHub |
| **Foro** · `server-nexe.com` | Preguntas de uso, ayuda de la comunidad, discusiones de workflow, dudas sobre configuracion |

### Que incluir en el report (GitHub Issue)

- **Version**: la veras en el menu del tray como `server.nexe v1.0.2-beta` (o ejecuta `./nexe --version`)
- **SO + hardware**: `sw_vers` y `uname -m` (M1/M2/M3/M4)
- **Backend activo**: MLX / llama.cpp / Ollama (visible en `/ui/backends` o en el tray)
- **Modelo en uso**: nombre del modelo cargado
- **Pasos para reproducir**: que estabas haciendo justo antes del error
- **Resultado esperado vs obtenido**
- **Fragmento de log** (ya revisado por privacidad)
- **Captura de pantalla** si es un error visual (Web UI, tray)

Mas contexto = menos preguntas de seguimiento = resolucion mas rapida.

