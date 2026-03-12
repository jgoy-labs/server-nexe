# === METADATA RAG ===
versio: "1.0"
data: 2026-03-12
id: nexe-errors

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guía de errores comunes de NEXE 0.8: mensajes de error, causas y soluciones. Cubre errores de instalación, arranque, Web UI, autenticación, modelo, memoria y API."
tags: [errores, troubleshooting, soluciones, debug, 401, 403, 404, qdrant, mlx, model, web-ui, instalación]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# NEXE 0.8 — Errores comunes y soluciones

Recopilación de los errores más habituales de NEXE, con las causas probables y las soluciones recomendadas.

---

## Errores de instalación

### `No s'ha pogut trobar Python 3.10+`
**Causa:** Python no instalado o versión demasiado antigua.
**Solución:** `brew install python@3.12` y vuelve a ejecutar `./setup.sh`

### `Permission denied: ./setup.sh` o `./nexe`
**Causa:** El script no tiene permisos de ejecución.
**Solución:** `chmod +x setup.sh nexe`

### `ModuleNotFoundError`
**Causa:** El entorno virtual no se creó correctamente o no se instalaron las dependencias.
**Solución:** Vuelve a ejecutar `./setup.sh` — reinstala el entorno desde cero.

### `NameError: name 'DIM' is not defined`
**Causa:** Bug en `installer/installer_setup_env.py` en una versión antigua — la constante ANSI `DIM` no estaba importada.
**Solución:** `git pull` para obtener la versión corregida y vuelve a ejecutar `./setup.sh`.

### `Python version error` / `requires Python 3.10+`
**Causa:** Python 3.9 o anterior instalado en el sistema.
**Solución:** `brew install python@3.11` o `brew install python@3.12`.

---

## Errores de arranque del servidor

### `Port 9119 already in use`
**Causa:** Ya hay una instancia de NEXE (u otro proceso) usando el puerto 9119.
**Solución:**
```bash
./nexe status
lsof -ti:9119 | xargs kill
./nexe go
```

### `Qdrant connection refused`
**Causa:** El servicio Qdrant no está en ejecución.
**Solución:** `./nexe go` lo inicia automáticamente si `NEXE_AUTOSTART_QDRANT=true` en `.env`. Si el problema persiste: `./nexe stop` y `./nexe go` de nuevo.

### `MLX not found` / `No module named 'mlx'`
**Causa:** MLX no instalado o el procesador no es Apple Silicon.
**Solución:** MLX requiere Apple Silicon (M1/M2/M3/M4). Si tienes Mac Intel o Linux, cambia a `llama_cpp` o `ollama` en `.env`:
```
NEXE_MODEL_ENGINE=llama_cpp
```

### El servidor arranca pero no responde
**Causa:** El modelo se está cargando (puede tardar 10–30 s) o hay un error silencioso.
**Solución:** Espera hasta que el modelo esté cargado. Comprueba con:
```bash
curl http://localhost:9119/health
./nexe logs
```

### `OOM killed` / `Killed` (proceso muerto)
**Causa:** El modelo es demasiado grande para la RAM disponible.
**Solución:** Elige un modelo más pequeño en `.env`. Referencia orientativa:
- 8 GB RAM → Qwen3 1.7B o Qwen3 4B
- 16 GB RAM → Qwen3 8B o Mistral 7B
- 32 GB+ RAM → Qwen3 32B o Llama 3.1 70B

---

## Errores de Web UI

### Pantalla de login aparece pero la clave no funciona (`Clau incorrecta`)
**Causa 1:** La clave introducida es incorrecta.
**Solución:** Encuentra la clave correcta con:
```bash
grep NEXE_PRIMARY_API_KEY .env
```
Cópiala exactamente, sin espacios ni saltos de línea.

**Causa 2:** El servidor está corriendo una versión antigua (sin el sistema de login).
**Solución:**
```bash
git pull
lsof -ti:9119 | xargs kill
./nexe go
```

### `GET /ui/auth 404 Not Found` en los logs
**Causa:** El servidor no tiene el endpoint `/ui/auth` — versión antigua del código.
**Solución:** `git pull` y reinicia el servidor.

### `POST /ui/chat 403 Forbidden` en los logs
**Causa:** Error CSRF — la cookie de sesión no coincide o es de versión anterior.
**Solución:** Abre la Web UI en modo incógnito o borra las cookies para `localhost:9119`. Con la versión actual (login con API key) este error ya no debería aparecer.

### La Web UI carga pero el chat no responde
**Causa:** El modelo todavía se está cargando, o Qdrant no está activo.
**Solución:** Espera 10–30 s y comprueba:
```bash
curl http://localhost:9119/health
```

---

## Errores de autenticación API

### `401 Unauthorized` en las peticiones API
**Causa:** La API key no se ha enviado o es incorrecta.
**Solución:**
```bash
curl -H "X-API-Key: $(grep NEXE_PRIMARY_API_KEY .env | cut -d= -f2)" \
  http://localhost:9119/v1/chat/completions
```

### La clave API ha expirado
**Causa:** `NEXE_PRIMARY_KEY_EXPIRES` en `.env` es una fecha pasada.
**Solución:** Genera una nueva clave y actualiza `.env`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Errores de modelo

### Descarga muy lenta
**Causa:** Conexión lenta o modelo muy grande (modelos 7B+ ocupan 4–20 GB).
**Solución:** Espera o elige un modelo más pequeño.

### El modelo responde muy lentamente
**Causa:** Modelo demasiado grande para la RAM/GPU disponibles.
**Solución:** En Apple Silicon M1 de 8 GB, Qwen3 4B es el máximo recomendado.

---

## Errores de memoria / RAG

### La memoria no recuerda información guardada
**Causa:** La información se guardó en una sesión diferente, o Qdrant reinició y perdió el índice.
**Solución:**
```bash
./nexe memory stats
./nexe memory recall "palabra clave de la info guardada"
```

---

## Errores generales

### Los cambios en el código no se reflejan en el servidor
**Causa:** El servidor en ejecución usa el código antiguo (no se ha reiniciado).
**Solución:**
```bash
lsof -ti:9119 | xargs kill
./nexe go
```
