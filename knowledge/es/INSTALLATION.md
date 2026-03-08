# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-installation-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guía completa de instalación de NEXE 0.8. macOS (testado), Linux y Windows (teórico). Requisitos, instalación guiada con setup.sh, configuración .env, backends MLX/llama.cpp/Ollama y resolución de problemas."
tags: [instalación, setup, macos, configuración, homebrew, python, venv]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: es
type: tutorial
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Guía de Instalación - NEXE 0.8

> **📝 Documento actualizado:** 2026-02-04
> **⚠️ IMPORTANTE:** Este documento ha sido revisado para reflejar el **código real** de Nexe 0.8 (setup.sh, install_nexe.py, variables de entorno, etc.).

Esta guía explica paso a paso cómo instalar NEXE en tu sistema.

## ⚠️ Plataformas soportadas

**Probado y funcionando:**
- ✅ macOS 12+ (Monterey o superior)
  - Apple Silicon (M1, M2, M3, M4)
  - Intel x86_64

**Teórico (código implementado pero NO probado):**
- ⚠️ Raspberry Pi 4/5 con Raspberry Pi OS
- ⚠️ Linux x86_64 (Ubuntu 20.04+, Debian, etc.)
- ⚠️ Windows 10/11 (con WSL2 recomendado)

**Si pruebas NEXE en RPi, Linux o Windows**, por favor reporta la experiencia. Es código no probado pero debería funcionar.

## Requisitos del sistema

### Mínimos (modelos pequeños)
- **CPU:** Cualquier CPU moderno (2+ cores)
- **RAM:** 8 GB
- **Disco:** 10 GB libres
- **Python:** 3.9+
- **Internet:** Para descargar modelos y dependencias

### Recomendados (modelos medianos)
- **CPU:** Apple Silicon (M1+) o CPU con AVX2
- **RAM:** 16 GB
- **Disco:** 20 GB libres
- **Python:** 3.11+
- **GPU:** Metal (Mac) o CUDA (Linux/Win) para aceleración

### Óptimos (modelos grandes)
- **CPU:** Apple Silicon M2+ o CPU moderno multinúcleo
- **RAM:** 32+ GB
- **Disco:** 50+ GB libres
- **GPU:** Obligatoria para modelos 70B

## Dependencias previas

### macOS

```bash
# Instalar Homebrew si no lo tienes
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Instalar Python 3.11 (recomendado)
brew install python@3.11

# Verificar instalación
python3 --version
```

### Linux (Ubuntu/Debian)

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Python y dependencias
sudo apt install python3.11 python3.11-venv python3-pip git curl -y

# Verificar instalación
python3.11 --version
```

### Raspberry Pi

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar dependencias
sudo apt install python3-pip python3-venv git curl -y

# Nota: Los modelos grandes NO funcionarán en RPi por limitaciones de RAM
```

## Descargar NEXE

**Opción 1: Clonar repositorio (recomendado)**

```bash
# Clonar el repositorio
git clone https://github.com/jgoy/nexe.git
cd nexe/server-nexe

# O si está en un path local
cd /path/to/server-nexe
```

**Opción 2: Descargar ZIP**

Si tienes NEXE como ZIP:
```bash
unzip server-nexe.zip
cd server-nexe
```

## Instalación guiada (recomendado)

NEXE incluye un instalador interactivo que detecta tu hardware y te guía por el proceso.

### Ejecutar el instalador

**Opción 1: Via setup.sh (RECOMENDADO)**

```bash
cd server-nexe
chmod +x setup.sh   # solo necesario la primera vez (ZIP de GitHub no preserva permisos)
./setup.sh
```

Este script:
- Limpia cache Python automáticamente
- Detiene procesos anteriores (Qdrant, Ollama, servidor)
- Ofrece opción de cleanup completo (venv, .env, storage)
- Llama a `install_nexe.py` con entorno limpio

**Opción 2: Directamente (menos robusto)**

```bash
cd server-nexe
python3 install_nexe.py
```

⚠️ **Nota:** Si tienes instalación previa, usa `./setup.sh` para garantizar una limpieza adecuada.

### ¿Qué hace el instalador?

El instalador te guiará por estas etapas:

#### 1. Selección de idioma
- Català (CA)
- Castellà (ES)
- English (EN)

#### 2. Detección de hardware

El instalador analiza:
- **Plataforma:** macOS, Linux, Raspberry Pi, Windows
- **CPU:** Arquitectura (ARM64, x86_64, armv7l)
- **RAM disponible:** Para recomendar modelos adecuados
- **Espacio en disco:** Para verificar que hay suficiente espacio
- **GPU/Metal:** Para decidir qué backend usar

**Ejemplo de salida:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Analizando tu hardware...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Plataforma: macOS (Darwin)
Arquitectura: arm64 (Apple Silicon)
RAM Disponible: 16 GB
Disc Disponible: 256 GB lliures
Suport Metal (GPU): Sí ✓

Recomanació: Backend MLX (optimitzat per Apple Silicon)
```

#### 3. Selección de backend

Según tu hardware, se te propondrán backends:

**Para Apple Silicon:**
- **MLX** (recomendado) - Nativo, optimizado, rápido
- llama.cpp - Universal, compatible
- Ollama - Si ya lo tienes instalado

**Para Intel Mac:**
- **llama.cpp** (recomendado) - Universal con Metal
- Ollama - Si ya lo tienes instalado

**Para Linux/RPi:**
- **llama.cpp** (única opción probada teóricamente)
- Ollama - Si ya lo tienes instalado

**Para Raspberry Pi:**
- **llama.cpp** (única opción viable)
- ⚠️ Solo modelos pequeños (Phi-3.5, Salamandra 2B)

#### 4. Selección de modelo

El instalador te mostrará modelos compatibles con tu RAM:

**Si tienes 8 GB RAM:**
```
Models disponibles:

[1] Phi-3.5 Mini (2.4 GB)
    Origin: Microsoft
    Idioma: Multilingüe
    Característiques: Molt ràpid, bo per tasques generals

[2] Salamandra 2B (1.5 GB) ⭐ RECOMANAT PER CATALÀ
    Origin: BSC/AINA (Catalunya)
    Idioma: Català, Castellà, Euskera, Gallec
    Característiques: Optimitzat per llengües ibèriques
```

**Si tienes 16+ GB RAM:**
```
Models disponibles:

[1] Mistral 7B (4.1 GB)
    Origin: Mistral AI
    Idioma: Multilingüe
    Característiques: Excel·lent equilibri qualitat/velocitat

[2] Salamandra 7B (4.9 GB) ⭐ RECOMANAT PER CATALÀ
    Origin: BSC/AINA (Catalunya)
    Idioma: Català, Castellà, Euskera, Gallec
    Característiques: El millor per català

[3] Llama 3.1 8B (4.7 GB)
    Origin: Meta
    Idioma: Multilingüe
    Característiques: Molt popular, excel·lent qualitat
```

**Si tienes 32+ GB RAM:**
También tendrás disponibles Mixtral 8x7B y Llama 3.1 70B.

#### 5. Descarga e instalación

El instalador:
1. Crea un entorno virtual Python
2. Instala las dependencias necesarias
3. Descarga el binario Qdrant (gestiona cuarentena macOS)
4. Descarga el modelo seleccionado (puede tardar según el tamaño)
5. Configura el fichero `.env` con las variables necesarias
6. Crea directorios `storage/` (qdrant, vectors, logs, models)
7. Marca auto-ingestión para la primera ejecución (no la realiza ahora)
8. Muestra instrucciones finales

**Nota:** La descarga del modelo puede tardar entre 5-30 minutos según tu conexión y el tamaño del modelo.

#### 6. Primera ejecución

Después de la instalación:

```bash
./nexe go
```

En el primer arranque:
- ✅ Qdrant se auto-arranca (subprocess gestionado por lifespan.py)
- ✅ Ollama se auto-arranca si está instalado
- ✅ Los módulos Memory se cargan (Memory, RAG, Embeddings)
- ✅ Los módulos Plugin se inicializan (MLX/LlamaCpp/Ollama, Security, WebUI)
- ✅ Auto-ingestión de `knowledge/` (solo primera vez, crea marker `.knowledge_ingested`)
- ✅ Se genera el Bootstrap token (si NEXE_ENV=development)

**No hay tests automáticos** - la verificación se hace manualmente (ver sección "Verificación post-instalación").

## Instalación manual (avanzado)

Si prefieres instalar manualmente o el instalador automático falla:

### 1. Crear entorno virtual

```bash
cd server-nexe
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows
```

### 2. Instalar dependencias

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configurar `.env`

Crea un fichero `.env` en la raíz de `server-nexe/`:

```bash
# ═══════════════════════════════════════════════════════════
# NEXE 0.8 - Variables d'Entorn (Configuration)
# ═══════════════════════════════════════════════════════════

# ─── MODEL ENGINE ───
# Opcions: mlx (Apple Silicon), llama_cpp (universal), ollama (bridge)
NEXE_MODEL_ENGINE=mlx

# ─── MODELS ───
# Path o ID del model per cada backend
NEXE_DEFAULT_MODEL=mlx-community/Phi-3.5-mini-instruct-4bit  # Model actiu
NEXE_MLX_MODEL=mlx-community/Phi-3.5-mini-instruct-4bit      # Específic MLX
NEXE_LLAMA_CPP_MODEL=storage/models/phi-3.5-mini.gguf        # Específic llama.cpp
NEXE_OLLAMA_MODEL=phi3:mini                                   # Específic Ollama

# ─── ENVIRONMENT ───
NEXE_ENV=development  # "production" o "development"

# ─── SECURITY (CRÍTIC EN PRODUCCIÓ) ───
# Dual-key support (rotación de claves)
NEXE_PRIMARY_API_KEY=your-primary-key-here
NEXE_PRIMARY_KEY_EXPIRES=2026-06-30T00:00:00Z  # ISO 8601 format
NEXE_SECONDARY_API_KEY=your-secondary-key-here  # Grace period rotation
NEXE_SECONDARY_KEY_EXPIRES=2026-01-31T00:00:00Z

# Retrocompatibilidad (clave única)
# NEXE_ADMIN_API_KEY=single-key-here

# CSRF Protection
NEXE_CSRF_SECRET=auto-generated-secret-32-chars

# ─── BOOTSTRAP (DEV MODE) ───
BOOTSTRAP_TTL=30  # Minutes
NEXE_BOOTSTRAP_DISPLAY=true  # Show token on startup

# ─── AUTOSTART SERVICES ───
NEXE_AUTOSTART_QDRANT=true   # Auto-start Qdrant local binary
NEXE_AUTOSTART_OLLAMA=true   # Auto-start Ollama if installed

# ─── QDRANT (AUTO-MANAGED) ───
# NO usar QDRANT_PATH (obsolet!)
# Paths auto-gestionats per lifespan.py:
#   - storage/qdrant/           → Qdrant data
#   - storage/vectors/          → Vector DBs (metadata_memory.db, qdrant_local/)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Variables internes Qdrant (auto-injectades per lifespan.py):
# QDRANT__STORAGE__STORAGE_PATH=storage/qdrant
# QDRANT__SERVICE__HTTP_PORT=6333
# QDRANT__SERVICE__DISABLE_TELEMETRY=true

# ─── TIMEOUTS (OPCIONAL) ───
NEXE_OLLAMA_HEALTH_TIMEOUT=5.0
NEXE_OLLAMA_UNLOAD_TIMEOUT=10.0
NEXE_QDRANT_HEALTH_TIMEOUT=2.0

# ─── PRODUCTION SECURITY (OPCIONAL) ───
# Module allowlist (només en production mode)
# NEXE_APPROVED_MODULES=security,mlx_module,memory,rag,embeddings

# ─── ADVANCED (NO TOCAR) ───
NEXE_FORCE_RELOAD=false  # Force rebuild app (testing only)
AUTO_CLEAN_ENABLED=false  # Auto-clean temp files
AUTO_CLEAN_DRY_RUN=true

# ─── LOGGING ───
# Configurat a personality/server.toml
# Logs a: storage/logs/
```

**Nota importante:**
- El servidor/puerto se configura en `personality/server.toml` (NO .env)
- Los paths `storage/*` se crean automáticamente
- En modo DEV, las API keys son opcionales (fail-open)
- En modo PRODUCTION, las API keys son obligatorias (fail-closed)

### 4. Inicializar Qdrant

**Qdrant se auto-arranca automáticamente** cuando ejecutas `./nexe go` (gestionado por `core/lifespan.py`).

**Si quieres arrancar Qdrant manualmente:**

```bash
# Variables de entorno necesarias
export QDRANT__STORAGE__STORAGE_PATH="storage/qdrant"
export QDRANT__SERVICE__HTTP_PORT="6333"
export QDRANT__SERVICE__DISABLE_TELEMETRY="true"

# Ejecutar binario
./qdrant --disable-telemetry &

# Verificar que está corriendo
curl http://localhost:6333/health
```

**Si no tienes el binario:**
```bash
# El instalador lo descarga automáticamente
# O descarga manualmente:
# Mac (arm64): https://github.com/qdrant/qdrant/releases
# Linux (x86_64): https://github.com/qdrant/qdrant/releases
```

⚠️ **Recomendación:** Deja que `./nexe go` gestione Qdrant automáticamente.

### 5. Iniciar el servidor

```bash
./nexe go

# O manualmente:
python3 -m uvicorn core.app:app --host 0.0.0.0 --port 9119
```

### 6. Verificar funcionamiento

```bash
# Test de health
curl http://localhost:9119/health

# Deberías ver:
# {"status": "ok", "version": "0.8.0"}
```

## Backends: Instalación específica

### Backend MLX (Apple Silicon)

```bash
pip install mlx mlx-lm
```

**Modelos MLX:**
- Se descargan automáticamente de HuggingFace
- Se guardan en `storage/models/` (NO `~/.cache/huggingface/`)
- Formato: Checkpoint nativo MLX (no GGUF)
- El instalador usa `snapshot_download(local_dir=storage/models/...)`

### Backend llama.cpp

```bash
pip install llama-cpp-python

# Para Metal (Mac):
CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

# Para CUDA (Linux con GPU NVIDIA):
CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
```

**Modelos llama.cpp:**
- Formato GGUF
- Se descargan de HuggingFace
- Se guardan en `storage/models/` (NO `./models/`)
- Variable `.env`: `NEXE_LLAMA_CPP_MODEL=storage/models/model.gguf`

### Backend Ollama

```bash
# 1. Instalar Ollama

# Mac: Descargar installer .pkg
# https://ollama.com/download
# (NO está disponible via Homebrew)

# Linux:
curl -fsSL https://ollama.com/install.sh | sh

# 2. Iniciar Ollama
ollama serve &

# 3. Descargar un modelo
ollama pull phi3:mini
# o
ollama pull mistral:7b

# 4. Configurar NEXE para usar Ollama
# En .env:
NEXE_MODEL_ENGINE=ollama
NEXE_OLLAMA_MODEL=phi3:mini
```

## Verificación post-instalación

### 1. Comprobar servidor

```bash
# Health check
curl http://localhost:9119/health

# Respuesta esperada:
# {
#   "status": "healthy",
#   "message": "Nexe 0.8 - All systems operational",
#   "version": "0.8.0",
#   "uptime": 123.45
# }

# Info del sistema (API endpoints disponibles)
curl http://localhost:9119/api/info

# Respuesta esperada:
# {
#   "version": "0.8.0",
#   "endpoints": [...],
#   "modules": [...]
# }
```

### 2. Test de chat

```bash
./nexe chat

# Prueba alguna pregunta:
# > Hola, ¿quién eres?
```

### 3. Test de memoria RAG

```bash
# Guardar información
./nexe memory store "Mi proyecto favorito es NEXE"

# Recuperar (NO "search", sino "recall")
./nexe memory recall "proyecto favorito"

# Otros comandos de memoria:
./nexe memory stats     # Estadísticas
./nexe memory cleanup   # Limpia entradas expiradas

# RAG search (diferente de memory):
./nexe rag search "proyecto favorito"
```

**Nota:**
- `memory` → Flat memory (store/recall/stats/cleanup)
- `rag` → RAG search (búsqueda semántica con vectores)

### 4. Acceder a Web UI

Abre el navegador en: `http://localhost:9119/ui`

### 5. Revisar logs

```bash
# Logs en tiempo real (path correcto)
tail -f storage/logs/nexe.log

# O via CLI (automático, encuentra logs en storage/logs/)
./nexe logs

# Ver logs específicos de módulo
./nexe logs --module mlx_module
./nexe logs --module security

# Últimas 100 líneas
./nexe logs --last 100
```

## Troubleshooting común

### Error: "Python version not supported"

```bash
# Verifica la versión
python3 --version

# Debe ser 3.9+, recomendado 3.11+
# Si es más antigua, instala una versión más nueva de Python
```

### Error: "No module named 'mlx'"

```bash
# Reactiva el entorno virtual
source venv/bin/activate

# Reinstala dependencias
pip install -r requirements.txt
```

### Error: "Qdrant connection refused"

```bash
# Verifica que Qdrant esté corriendo
ps aux | grep qdrant

# Si no está, inícialo:
./qdrant &

# Espera unos segundos y vuelve a intentar
```

### Error: "Out of memory" durante inferencia

**Solución:**
- Elige un modelo más pequeño
- Cierra otras aplicaciones
- Si es Mac, comprueba Activity Monitor
- En RPi, usa solo modelos 2B

### Error: "Model download failed"

**Solución:**
- Comprueba la conexión a internet
- HuggingFace puede estar temporalmente inactivo
- Prueba manualmente: visita el link del modelo en el navegador
- Elige un modelo alternativo

### El servidor arranca pero no responde

```bash
# Comprueba que el puerto no esté ocupado
lsof -i :9119

# Si hay otro proceso:
kill -9 <PID>

# O detén los procesos Nexe:
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"
pkill -f "ollama serve"

# Vuelve a iniciar
./nexe go
```

**Nota:** No existen los comandos `./nexe stop` ni `./nexe restart`. Usa:
- **Detener:** Ctrl+C o `pkill`
- **Reiniciar:** API endpoint `/admin/system/restart` (requiere API key)

### Rendimiento muy lento

**Posibles causas:**
- Modelo demasiado grande para tu RAM
- Backend no optimizado (prueba MLX si tienes Apple Silicon)
- CPU sobrecargada
- Disco lleno (la swap es lenta)

**Soluciones:**
- Elige un modelo más pequeño
- Cierra otras aplicaciones
- Verifica que Metal/GPU esté activo
- Libera espacio en disco

## Desinstalación

Si quieres desinstalar NEXE:

```bash
# 1. Detén el servidor (Ctrl+C o pkill)
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"
pkill -f "ollama serve"

# 2. Elimina el entorno virtual
rm -rf venv/

# 3. Elimina storage (datos, logs, vectores, modelos)
rm -rf storage/

# 4. Elimina ficheros de configuración
rm -f .env
rm -f .qdrant-initialized

# 5. Elimina snapshots legacy (si existe)
rm -rf snapshots/

# 6. (Opcional) Elimina la carpeta del proyecto
cd ..
rm -rf server-nexe/
```

**Nota:**
- Los modelos MLX están en `storage/models/`, NO en `~/.cache/huggingface/`
- Eliminar `storage/` elimina TODOS los datos (vectores, logs, modelos)

## Actualizaciones

Para actualizar NEXE a una nueva versión:

```bash
# 1. Haz backup de tu configuración
cp .env .env.backup
cp -r storage/ storage.backup/

# 2. Detén el servidor
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"

# 3. Descarga la nueva versión
git pull origin main

# 4. Actualiza dependencias
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 5. Reinicia el servidor
./nexe go

# O via API (si el servidor está running):
curl -X POST http://localhost:9119/admin/system/restart \
  -H "X-API-Key: your-api-key-here"
```

**Nota:** NO existe `./nexe restart`. Usa `./nexe go` o el endpoint API `/admin/system/restart`.

## Siguientes pasos

Ahora que tienes NEXE instalado:

1. **USAGE.md** - Aprende a usar las funcionalidades
2. **RAG.md** - Entiende cómo funciona la memoria
3. **API.md** - Integra NEXE con otras herramientas
4. **ARCHITECTURE.md** - Profundiza en la arquitectura

---

## Referencia rápida: Variables de entorno

| Variable | Valor por defecto | Descripción |
|----------|-------------------|-------------|
| **Model Engine** |||
| `NEXE_MODEL_ENGINE` | `mlx` | Backend LLM: mlx, llama_cpp, ollama |
| `NEXE_DEFAULT_MODEL` | - | Modelo activo (path o ID) |
| `NEXE_MLX_MODEL` | - | Modelo específico MLX |
| `NEXE_LLAMA_CPP_MODEL` | - | Modelo específico llama.cpp (GGUF) |
| `NEXE_OLLAMA_MODEL` | - | Modelo específico Ollama |
| **Security** |||
| `NEXE_PRIMARY_API_KEY` | - | API key principal (production) |
| `NEXE_PRIMARY_KEY_EXPIRES` | - | Expiry date ISO 8601 |
| `NEXE_SECONDARY_API_KEY` | - | API key secundaria (rotation) |
| `NEXE_SECONDARY_KEY_EXPIRES` | - | Expiry date ISO 8601 |
| `NEXE_ADMIN_API_KEY` | - | API key única (legacy) |
| `NEXE_CSRF_SECRET` | auto | Secret CSRF tokens |
| **Environment** |||
| `NEXE_ENV` | `development` | production o development |
| **Autostart** |||
| `NEXE_AUTOSTART_QDRANT` | `true` | Auto-start binario Qdrant |
| `NEXE_AUTOSTART_OLLAMA` | `true` | Auto-start Ollama si instalado |
| **Qdrant** |||
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| **Bootstrap** |||
| `BOOTSTRAP_TTL` | `30` | Token TTL (minutos) |
| `NEXE_BOOTSTRAP_DISPLAY` | `true` | Mostrar token en startup |
| **Production** |||
| `NEXE_APPROVED_MODULES` | - | Module allowlist (comma-separated) |

**Configuración servidor (personality/server.toml):**
- `core.server.host` → `127.0.0.1`
- `core.server.port` → `9119`
- `core.server.cors_origins` → `["http://localhost:3000"]`

---

## Changelog de actualización (2026-02-04)

### Cambios principales vs versión anterior:

1. **✅ Variables .env actualizadas**
   - `NEXE_BACKEND` → `NEXE_MODEL_ENGINE`
   - `MODEL_ID` → `NEXE_DEFAULT_MODEL`
   - `API_KEY` → `NEXE_PRIMARY_API_KEY` + `NEXE_SECONDARY_API_KEY`
   - Añadidas: `NEXE_ENV`, `NEXE_CSRF_SECRET`, `BOOTSTRAP_TTL`, etc.

2. **✅ Paths corregidos**
   - `snapshots/qdrant_storage/` → `storage/qdrant/`
   - `./models/` → `storage/models/`
   - `logs/nexe.log` → `storage/logs/*.log`
   - `~/.cache/huggingface/` → `storage/models/` (MLX)

3. **✅ Endpoints actualizados**
   - `/info` → `/api/info`
   - Respuesta `/health` corregida (añadido uptime, message)
   - `/metrics` → Prometheus text (JSON en `/metrics/json`)

4. **✅ CLI actualizado**
   - Recomendar `./setup.sh` (no `python3 install_nexe.py`)
   - `./nexe memory search` → `./nexe memory recall`
   - ELIMINADOS: `./nexe stop`, `./nexe restart` (no existen)

5. **✅ Qdrant auto-start**
   - NO es necesario ejecutar `./qdrant &` manualmente
   - Lifespan.py gestiona el auto-start con env vars

6. **✅ Backend Ollama**
   - NO `brew install ollama` (no disponible)
   - Descargar installer .pkg o script

7. **✅ Instalador**
   - NO ejecuta tests automáticos
   - Auto-ingestión solo en la primera ejecución (marker file)
   - Crea `storage/` (no `snapshots/`)

8. **✅ Auth headers**
   - `X-API-Key` header (NO `Authorization: Bearer`)
   - Dual-key support documentado

---

**Nota:** Si tienes problemas no resueltos aquí, consulta los logs (`./nexe logs`) o revisa **LIMITATIONS.md** para ver si es una limitación conocida.

**Contribuciones:** Si pruebas NEXE en Linux, Windows o RPi, por favor comparte tu experiencia para mejorar esta guía.
