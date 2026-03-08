# === METADATA RAG ===
versio: "1.0"
data: 2026-02-23
id: nexe-installation-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia completa d'instal·lació de NEXE 0.8. macOS (testejat), Linux i Windows (teòric). Requisits, instal·lació guiada amb setup.sh, configuració .env, backends MLX/llama.cpp/Ollama i resolució de problemes."
tags: [instal·lació, setup, macos, configuració, homebrew, python, venv]
chunk_size: 1000
priority: P1

# === OPCIONAL ===
lang: ca
type: tutorial
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Guia d'Instal·lació - NEXE 0.8

> **📝 Document actualitzat:** 2026-02-04
> **⚠️ IMPORTANT:** Aquest document ha estat revisat per reflectir el **codi real** de Nexe 0.8 (setup.sh, install_nexe.py, variables d'entorn, etc.).

Aquesta guia explica pas a pas com instal·lar NEXE al teu sistema.

## ⚠️ Plataformes suportades

**Testat i funcionant:**
- ✅ macOS 12+ (Monterey o superior)
  - Apple Silicon (M1, M2, M3, M4)
  - Intel x86_64

**Teòric (codi implementat però NO testat):**
- ⚠️ Raspberry Pi 4/5 amb Raspberry Pi OS
- ⚠️ Linux x86_64 (Ubuntu 20.04+, Debian, etc.)
- ⚠️ Windows 10/11 (amb WSL2 recomanat)

**Si proves NEXE en RPi, Linux o Windows**, si us plau reporta l'experiència! És codi no testat però hauria de funcionar.

## Requisits del sistema

### Mínims (models petits)
- **CPU:** Qualsevol CPU modern (2+ cores)
- **RAM:** 8 GB
- **Disc:** 10 GB lliures
- **Python:** 3.9+
- **Internet:** Per descarregar models i dependències

### Recomanats (models mitjans)
- **CPU:** Apple Silicon (M1+) o CPU amb AVX2
- **RAM:** 16 GB
- **Disc:** 20 GB lliures
- **Python:** 3.11+
- **GPU:** Metal (Mac) o CUDA (Linux/Win) per acceleració

### Òptims (models grans)
- **CPU:** Apple Silicon M2+ o CPU modern multicor
- **RAM:** 32+ GB
- **Disc:** 50+ GB lliures
- **GPU:** Obligatòria per models 70B

## Dependències prèvies

### macOS

```bash
# Instal·lar Homebrew si no el tens
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Instal·lar Python 3.11 (recomanat)
brew install python@3.11

# Verificar instal·lació
python3 --version
```

### Linux (Ubuntu/Debian)

```bash
# Actualitzar sistema
sudo apt update && sudo apt upgrade -y

# Instal·lar Python i dependències
sudo apt install python3.11 python3.11-venv python3-pip git curl -y

# Verificar instal·lació
python3.11 --version
```

### Raspberry Pi

```bash
# Actualitzar sistema
sudo apt update && sudo apt upgrade -y

# Instal·lar dependències
sudo apt install python3-pip python3-venv git curl -y

# Nota: Els models grans NO funcionaran en RPi per limitacions de RAM
```

## Descarregar NEXE

**Opció 1: Clonar repositori (recomanat)**

```bash
# Clonar el repositori
git clone https://github.com/jgoy/nexe.git
cd nexe/server-nexe

# O si està en un path local
cd /path/to/server-nexe
```

**Opció 2: Descarregar ZIP**

Si tens NEXE com a ZIP:
```bash
unzip server-nexe.zip
cd server-nexe
```

## Instal·lació guiada (recomanat)

NEXE inclou un instal·lador interactiu que detecta el teu hardware i et guia pel procés.

### Executar l'instal·lador

**Opció 1: Via setup.sh (RECOMANAT)**

```bash
cd server-nexe
chmod +x setup.sh   # només cal la primera vegada (ZIP de GitHub no preserva permisos)
./setup.sh
```

Aquest script:
- Neteja cache Python automàticament
- Atura processos anteriors (Qdrant, Ollama, servidor)
- Ofereix opció de cleanup complet (venv, .env, storage)
- Crida `install_nexe.py` amb entorn net

**Opció 2: Directament (menys robust)**

```bash
cd server-nexe
python3 install_nexe.py
```

⚠️ **Nota:** Si tens instal·lació prèvia, usa `./setup.sh` per garantir neteja adequada.

### Què fa l'instal·lador?

L'instal·lador et guiarà per aquestes etapes:

#### 1. Selecció d'idioma
- Català (CA)
- Castellà (ES)
- English (EN)

#### 2. Detecció de hardware

L'instal·lador analitza:
- **Plataforma:** macOS, Linux, Raspberry Pi, Windows
- **CPU:** Arquitectura (ARM64, x86_64, armv7l)
- **RAM disponible:** Per recomanar models adequats
- **Espai en disc:** Per verificar que hi ha prou espai
- **GPU/Metal:** Per decidir quin backend usar

**Exemple de sortida:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Analitzant el teu hardware...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Plataforma: macOS (Darwin)
Arquitectura: arm64 (Apple Silicon)
RAM Disponible: 16 GB
Disc Disponible: 256 GB lliures
Suport Metal (GPU): Sí ✓

Recomanació: Backend MLX (optimitzat per Apple Silicon)
```

#### 3. Selecció de backend

Segons el teu hardware, se't proposaran backends:

**Per Apple Silicon:**
- **MLX** (recomanat) - Natiu, optimitzat, ràpid
- llama.cpp - Universal, compatible
- Ollama - Si ja el tens instal·lat

**Per Intel Mac:**
- **llama.cpp** (recomanat) - Universal amb Metal
- Ollama - Si ja el tens instal·lat

**Per Linux/RPi:**
- **llama.cpp** (única opció testejada teòricament)
- Ollama - Si ja el tens instal·lat

**Per Raspberry Pi:**
- **llama.cpp** (única opció viable)
- ⚠️ Només models petits (Phi-3.5, Salamandra 2B)

#### 4. Selecció de model

L'instal·lador et mostrarà models compatibles amb la teva RAM:

**Si tens 8 GB RAM:**
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

**Si tens 16+ GB RAM:**
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

**Si tens 32+ GB RAM:**
També tindràs disponibles Mixtral 8x7B i Llama 3.1 70B.

#### 5. Descàrrega i instal·lació

L'instal·lador:
1. Crea un entorn virtual Python
2. Instal·la les dependències necessàries
3. Descarrega Qdrant binari (gestiona quarantena macOS)
4. Descarrega el model seleccionat (pot trigar segons la mida)
5. Configura el fitxer `.env` amb variables necessàries
6. Crea directoris `storage/` (qdrant, vectors, logs, models)
7. Marca auto-ingesta per primera execució (no la fa ara)
8. Mostra instruccions finals

**Nota:** La descàrrega del model pot trigar entre 5-30 minuts segons la teva connexió i la mida del model.

#### 6. Primera execució

Després de la instal·lació:

```bash
./nexe go
```

Al primer arrencament:
- ✅ Qdrant s'auto-arrenca (subprocess gestionat per lifespan.py)
- ✅ Ollama s'auto-arrenca si està instal·lat
- ✅ Memory modules es carreguen (Memory, RAG, Embeddings)
- ✅ Plugin modules s'inicialitzen (MLX/LlamaCpp/Ollama, Security, WebUI)
- ✅ Auto-ingesta de `knowledge/` (només primera vegada, crea marker `.knowledge_ingested`)
- ✅ Bootstrap token es genera (si NEXE_ENV=development)

**No hi ha tests automàtics** - la verificació es fa manualment (veure secció "Verificació post-instal·lació").

## Instal·lació manual (avançat)

Si prefereixes instal·lar manualment o l'instal·lador automàtic falla:

### 1. Crear entorn virtual

```bash
cd server-nexe
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows
```

### 2. Instal·lar dependències

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configurar `.env`

Crea un fitxer `.env` a l'arrel de `server-nexe/`:

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
# Dual-key support (rotació de claus)
NEXE_PRIMARY_API_KEY=your-primary-key-here
NEXE_PRIMARY_KEY_EXPIRES=2026-06-30T00:00:00Z  # ISO 8601 format
NEXE_SECONDARY_API_KEY=your-secondary-key-here  # Grace period rotation
NEXE_SECONDARY_KEY_EXPIRES=2026-01-31T00:00:00Z

# Retrocompatibilitat (clau única)
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

**Nota important:**
- El servidor/port es configura a `personality/server.toml` (NO .env)
- Els paths `storage/*` es creen automàticament
- En DEV mode, API keys són opcionals (fail-open)
- En PRODUCTION mode, API keys són obligatòries (fail-closed)

### 4. Inicialitzar Qdrant

**Qdrant s'auto-arrenca automàticament** quan executes `./nexe go` (gestionat per `core/lifespan.py`).

**Si vols arrencar Qdrant manualment:**

```bash
# Variables d'entorn necessàries
export QDRANT__STORAGE__STORAGE_PATH="storage/qdrant"
export QDRANT__SERVICE__HTTP_PORT="6333"
export QDRANT__SERVICE__DISABLE_TELEMETRY="true"

# Executar binari
./qdrant --disable-telemetry &

# Verificar que corre
curl http://localhost:6333/health
```

**Si no tens el binari:**
```bash
# L'instal·lador el descarrega automàticament
# O descarrega manualment:
# Mac (arm64): https://github.com/qdrant/qdrant/releases
# Linux (x86_64): https://github.com/qdrant/qdrant/releases
```

⚠️ **Recomanació:** Deixa que `./nexe go` gestioni Qdrant automàticament.

### 5. Iniciar el servidor

```bash
./nexe go

# O manualment:
python3 -m uvicorn core.app:app --host 0.0.0.0 --port 9119
```

### 6. Verificar funcionament

```bash
# Test de health
curl http://localhost:9119/health

# Hauries de veure:
# {"status": "ok", "version": "0.8.0"}
```

## Backends: Instal·lació específica

### Backend MLX (Apple Silicon)

```bash
pip install mlx mlx-lm
```

**Models MLX:**
- Es descarreguen automàticament de HuggingFace
- Es guarden a `storage/models/` (NO `~/.cache/huggingface/`)
- Format: Checkpoint natius MLX (no GGUF)
- L'instal·lador usa `snapshot_download(local_dir=storage/models/...)`

### Backend llama.cpp

```bash
pip install llama-cpp-python

# Per Metal (Mac):
CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir

# Per CUDA (Linux amb GPU NVIDIA):
CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
```

**Models llama.cpp:**
- Format GGUF
- Es descarreguen de HuggingFace
- Es guarden a `storage/models/` (NO `./models/`)
- Variable `.env`: `NEXE_LLAMA_CPP_MODEL=storage/models/model.gguf`

### Backend Ollama

```bash
# 1. Instal·lar Ollama

# Mac: Descarregar installer .pkg
# https://ollama.com/download
# (NO està disponible via Homebrew)

# Linux:
curl -fsSL https://ollama.com/install.sh | sh

# 2. Iniciar Ollama
ollama serve &

# 3. Descarregar un model
ollama pull phi3:mini
# o
ollama pull mistral:7b

# 4. Configurar NEXE per usar Ollama
# Al .env:
NEXE_MODEL_ENGINE=ollama
NEXE_OLLAMA_MODEL=phi3:mini
```

## Verificació post-instal·lació

### 1. Comprovar servidor

```bash
# Health check
curl http://localhost:9119/health

# Resposta esperada:
# {
#   "status": "healthy",
#   "message": "Nexe 0.8 - All systems operational",
#   "version": "0.8.0",
#   "uptime": 123.45
# }

# Info del sistema (API endpoints disponibles)
curl http://localhost:9119/api/info

# Resposta esperada:
# {
#   "version": "0.8.0",
#   "endpoints": [...],
#   "modules": [...]
# }
```

### 2. Test de chat

```bash
./nexe chat

# Prova alguna pregunta:
# > Hola, qui ets?
```

### 3. Test de memòria RAG

```bash
# Guardar informació
./nexe memory store "El meu projecte favorit és NEXE"

# Recuperar (NO "search", sinó "recall")
./nexe memory recall "projecte favorit"

# Altres comandes memòria:
./nexe memory stats     # Estadístiques
./nexe memory cleanup   # Neteja expired entries

# RAG search (diferent de memory):
./nexe rag search "projecte favorit"
```

**Nota:**
- `memory` → Flat memory (store/recall/stats/cleanup)
- `rag` → RAG search (cerca semàntica amb vectors)

### 4. Accedir a Web UI

Obre el navegador a: `http://localhost:9119/ui`

### 5. Revisar logs

```bash
# Logs en temps real (path correcte)
tail -f storage/logs/nexe.log

# O via CLI (automàtic, troba logs a storage/logs/)
./nexe logs

# Veure logs específics de mòdul
./nexe logs --module mlx_module
./nexe logs --module security

# Últimes 100 línies
./nexe logs --last 100
```

## Troubleshooting comú

### Error: "Python version not supported"

```bash
# Verifica la versió
python3 --version

# Ha de ser 3.9+, recomanat 3.11+
# Si és més antiga, instal·la Python més nou
```

### Error: "No module named 'mlx'"

```bash
# Reactiva l'entorn virtual
source venv/bin/activate

# Reinstal·la dependències
pip install -r requirements.txt
```

### Error: "Qdrant connection refused"

```bash
# Verifica que Qdrant estigui corrent
ps aux | grep qdrant

# Si no està, inicia'l:
./qdrant &

# Espera uns segons i torna a provar
```

### Error: "Out of memory" durant inferència

**Solució:**
- Tria un model més petit
- Tanca altres aplicacions
- Si és Mac, comprova Activity Monitor
- En RPi, usa només models 2B

### Error: "Model download failed"

**Solució:**
- Comprova connexió a internet
- HuggingFace pot estar temporalment inactiu
- Prova manualment: visita el link del model al navegador
- Tria un model alternatiu

### El servidor arrenca però no respon

```bash
# Comprova que el port no estigui ocupat
lsof -i :9119

# Si hi ha un altre procés:
kill -9 <PID>

# O atura processos Nexe:
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"
pkill -f "ollama serve"

# Torna a iniciar
./nexe go
```

**Nota:** No existeixen comandes `./nexe stop` ni `./nexe restart`. Usa:
- **Aturar:** Ctrl+C o `pkill`
- **Reiniciar:** API endpoint `/admin/system/restart` (requereix API key)

### Performance molt lenta

**Possibles causes:**
- Model massa gran per la teva RAM
- Backend no optimitzat (prova MLX si tens Apple Silicon)
- CPU sobrecarregada
- Disc ple (la swap és lenta)

**Solucions:**
- Tria un model més petit
- Tanca altres aplicacions
- Verifica que Metal/GPU estigui actiu
- Allibera espai en disc

## Desinstal·lació

Si vols desinstal·lar NEXE:

```bash
# 1. Atura el servidor (Ctrl+C o pkill)
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"
pkill -f "ollama serve"

# 2. Elimina l'entorn virtual
rm -rf venv/

# 3. Elimina storage (dades, logs, vectors, models)
rm -rf storage/

# 4. Elimina fitxers de configuració
rm -f .env
rm -f .qdrant-initialized

# 5. Elimina snapshots legacy (si existeix)
rm -rf snapshots/

# 6. (Opcional) Elimina la carpeta del projecte
cd ..
rm -rf server-nexe/
```

**Nota:**
- Els models MLX estan a `storage/models/`, NO a `~/.cache/huggingface/`
- Eliminar `storage/` elimina TOTES les dades (vectors, logs, models)

## Actualitzacions

Per actualitzar NEXE a una versió nova:

```bash
# 1. Fes backup de la teva configuració
cp .env .env.backup
cp -r storage/ storage.backup/

# 2. Atura el servidor
pkill -f "uvicorn.*nexe"
pkill -f "qdrant.*disable-telemetry"

# 3. Descarrega la nova versió
git pull origin main

# 4. Actualitza dependències
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 5. Reinicia el servidor
./nexe go

# O via API (si servidor està running):
curl -X POST http://localhost:9119/admin/system/restart \
  -H "X-API-Key: your-api-key-here"
```

**Nota:** NO existeix `./nexe restart`. Usa `./nexe go` o l'endpoint API `/admin/system/restart`.

## Següents passos

Ara que tens NEXE instal·lat:

1. **USAGE.md** - Aprèn a usar les funcionalitats
2. **RAG.md** - Entén com funciona la memòria
3. **API.md** - Integra NEXE amb altres eines
4. **ARCHITECTURE.md** - Aprofundeix en l'arquitectura

---

## Referència ràpida: Variables d'entorn

| Variable | Valor per defecte | Descripció |
|----------|-------------------|------------|
| **Model Engine** |||
| `NEXE_MODEL_ENGINE` | `mlx` | Backend LLM: mlx, llama_cpp, ollama |
| `NEXE_DEFAULT_MODEL` | - | Model actiu (path o ID) |
| `NEXE_MLX_MODEL` | - | Model específic MLX |
| `NEXE_LLAMA_CPP_MODEL` | - | Model específic llama.cpp (GGUF) |
| `NEXE_OLLAMA_MODEL` | - | Model específic Ollama |
| **Security** |||
| `NEXE_PRIMARY_API_KEY` | - | API key principal (production) |
| `NEXE_PRIMARY_KEY_EXPIRES` | - | Expiry date ISO 8601 |
| `NEXE_SECONDARY_API_KEY` | - | API key secundària (rotation) |
| `NEXE_SECONDARY_KEY_EXPIRES` | - | Expiry date ISO 8601 |
| `NEXE_ADMIN_API_KEY` | - | API key única (legacy) |
| `NEXE_CSRF_SECRET` | auto | Secret CSRF tokens |
| **Environment** |||
| `NEXE_ENV` | `development` | production o development |
| **Autostart** |||
| `NEXE_AUTOSTART_QDRANT` | `true` | Auto-start Qdrant binari |
| `NEXE_AUTOSTART_OLLAMA` | `true` | Auto-start Ollama si instal·lat |
| **Qdrant** |||
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| **Bootstrap** |||
| `BOOTSTRAP_TTL` | `30` | Token TTL (minutes) |
| `NEXE_BOOTSTRAP_DISPLAY` | `true` | Mostrar token a startup |
| **Production** |||
| `NEXE_APPROVED_MODULES` | - | Module allowlist (comma-separated) |

**Configuració servidor (personality/server.toml):**
- `core.server.host` → `127.0.0.1`
- `core.server.port` → `9119`
- `core.server.cors_origins` → `["http://localhost:3000"]`

---

## Changelog d'actualització (2026-02-04)

### Canvis principals vs versió anterior:

1. **✅ Variables .env actualitzades**
   - `NEXE_BACKEND` → `NEXE_MODEL_ENGINE`
   - `MODEL_ID` → `NEXE_DEFAULT_MODEL`
   - `API_KEY` → `NEXE_PRIMARY_API_KEY` + `NEXE_SECONDARY_API_KEY`
   - Afegides: `NEXE_ENV`, `NEXE_CSRF_SECRET`, `BOOTSTRAP_TTL`, etc.

2. **✅ Paths corregits**
   - `snapshots/qdrant_storage/` → `storage/qdrant/`
   - `./models/` → `storage/models/`
   - `logs/nexe.log` → `storage/logs/*.log`
   - `~/.cache/huggingface/` → `storage/models/` (MLX)

3. **✅ Endpoints actualitzats**
   - `/info` → `/api/info`
   - `/health` response corregit (afegit uptime, message)
   - `/metrics` → Prometheus text (JSON a `/metrics/json`)

4. **✅ CLI actualitzat**
   - Recomanar `./setup.sh` (no `python3 install_nexe.py`)
   - `./nexe memory search` → `./nexe memory recall`
   - ELIMINATS: `./nexe stop`, `./nexe restart` (no existeixen)

5. **✅ Qdrant auto-start**
   - NO cal executar `./qdrant &` manualment
   - Lifespan.py gestiona auto-start amb env vars

6. **✅ Backend Ollama**
   - NO `brew install ollama` (no disponible)
   - Descarregar installer .pkg o script

7. **✅ Instal·lador**
   - NO executa tests automàtics
   - Auto-ingesta només a primera execució (marker file)
   - Crea `storage/` (no `snapshots/`)

8. **✅ Auth headers**
   - `X-API-Key` header (NO `Authorization: Bearer`)
   - Dual-key support documentat

---

**Nota:** Si tens problemes no resolts aquí, consulta els logs (`./nexe logs`) o revisa **LIMITATIONS.md** per veure si és una limitació coneguda.

**Contribucions:** Si proves NEXE en Linux, Windows o RPi, si us plau comparteix la teva experiència per millorar aquesta guia!
