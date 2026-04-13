# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-errors-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Errores comunes y soluciones para server-nexe 0.9.7. Cubre errores de instalacion, arranque del servidor, Web UI, autenticacion API, carga de modelos, memoria/RAG, streaming y errores de encriptacion."
tags: [errors, troubleshooting, debugging, installation, startup, web-ui, api, models, memory, streaming, encryption]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy"
expires: null
---

# Errores comunes — server-nexe 0.9.7

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
| Servidor huerfano (Quit del tray no funciona) | Bug pre-v0.9.0 (corregido) — el tray no enviaba SIGTERM al servidor | Actualizar a v0.9.7. Workaround: `pkill -f "core.app"` o `lsof -iTCP:9119 -sTCP:LISTEN` → `kill -9 <PID>` |

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
| Qwen3.5 fails on MLX (versiones < v0.9.7) | Modelo multimodal incompatible | Desde v0.9.7 el backend MLX soporta VLM via mlx_vlm. Si falla, usar el backend Ollama como alternativa. |

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

