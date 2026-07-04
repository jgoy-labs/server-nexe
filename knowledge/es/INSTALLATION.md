# === METADATA RAG ===
versio: "2.0"
data: 2026-07-04
id: nexe-installation-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Como instalar server-nexe: (1) Desktop App nexe-app (Tauri v2, recomendado) — DMG macOS (~1.3 GB), AppImage Linux ARM64 (~1.2 GB) e installer NSIS para Windows ARM64 (~1.3 GB, nuevo en 1.0.7, sin firmar — SmartScreen avisa) desde Releases, con onboarding wizard (deteccion hardware, eleccion backend, descarga modelo) y modo sidecar con bandeja. (2) CLI desde codigo fuente: git clone + ./setup.sh (macOS/Linux). (3) Legacy: DMG SwiftUI standalone (sustituido por la Desktop App). Requisitos: macOS 14+ Apple Silicon (M1+), Linux ARM64 o Windows 11 ARM64, 8GB RAM. Backends: MLX, llama.cpp, Ollama (unico backend en Windows). Catalogo en models.json. Puerto: 9119."
tags: [installation, setup, desktop-app, tauri, appimage, dmg, cli, macos, linux, windows, nsis, requirements, models, backends, mlx, ollama, llama-cpp, tray, encryption, sidecar, wizard, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Instalacion — server-nexe 1.0.7

## En 30 segundos

- **3 metodos:** Desktop App nexe-app (Tauri, recomendado), CLI desde codigo fuente (`./setup.sh`), o el instalador DMG SwiftUI legacy
- **Desktop App:** DMG para macOS (~1.3 GB) + AppImage para Linux ARM64 (~1.2 GB) + setup NSIS para Windows ARM64 (~1.3 GB, nuevo en v1.0.7, sin firmar — SmartScreen avisa), desde [Releases](https://github.com/jgoy-labs/server-nexe/releases/latest)
- **Requiere macOS 14 Sonoma + Apple Silicon** (M1+), Linux ARM64 o Windows 11 ARM64
- **Elige modelo segun RAM:** el onboarding wizard lee el catalogo mantenido (`models.json`) y recomienda para tu RAM
- **Puerto por defecto:** 9119

---

Tres metodos de instalacion disponibles. Elige segun tu plataforma y preferencias.

## Requisitos del sistema

| Requisito | Minimo | Recomendado |
|-----------|--------|-------------|
| SO | **macOS 14 Sonoma** (Apple Silicon) / Linux ARM64 Ubuntu 24.04 (testeado en VM) / Linux x86_64 (parcial) / Windows 11 ARM64 (nuevo en 1.0.7 — installer NSIS sin firmar, backend Ollama) | macOS 14+ (Apple Silicon M1+) |
| CPU | **Apple Silicon (M1+) obligatorio** en macOS — Intel NO soportado | M2 Pro / M3 Pro / M4 |
| RAM | 8 GB | 16+ GB |
| Disco | 10 GB libres | 20+ GB (para modelos mas grandes) |
| Python | 3.11+ (metodo CLI) | 3.12 incluido (metodo DMG) |

> **Breaking en v0.9.9:** macOS 13 Ventura y macOS Intel quedan fuera del target soportado. El stack (mlx, mlx-vlm, fastembed ONNX, llama-cpp-python con Metal, wheels arm64) requiere macOS 14 Sonoma y Apple Silicon.

## Metodo 1: Desktop App — nexe-app (Tauri v2, Recomendado)

Aplicacion de escritorio que integra server-nexe como sidecar Python dentro de un shell Tauri v2. Es el metodo recomendado y el canal de release publico.

Descarga el ultimo paquete desde la pagina de [Releases](https://github.com/jgoy-labs/server-nexe/releases/latest):

| Plataforma | Paquete | Tamano |
|------------|---------|--------|
| macOS (Apple Silicon) | `nexe-app_1.0.7_aarch64.dmg` | ~1.3 GB |
| Linux (ARM64) | `nexe-app_1.0.7_aarch64.AppImage` | ~1.2 GB |
| Windows (ARM64) | `nexe-app_1.0.7_arm64-setup.exe` (nuevo en v1.0.7, sin firmar) | ~1.3 GB |

- **Wizard de onboarding** integrado en el frontend (HTML/JS, no SwiftUI): deteccion de hardware, seleccion de backend, descarga del modelo y configuracion, todo desde la propia app.
- **Modo sidecar:** server-nexe corre con `NEXE_SIDECAR=1`; las rutas las gestiona Tauri (`NEXE_HOME`, `NEXE_DATA_DIR`).
- **Bandeja de sistema** y gestion automatica del proceso sidecar.
- **Cross-platform:** macOS (Apple Silicon) + Linux (ARM64) + Windows (ARM64, nuevo en v1.0.7).
- **Windows:** soportado desde v1.0.7 — installer NSIS sin firmar (SmartScreen avisa: "Mas informacion" → "Ejecutar de todas formas"); WebView2 lo gestiona el installer; el motor es Ollama (la app lo instala automaticamente).
- **Ollama bundled** o auto-instalado.

El wizard lee el catalogo de modelos del fichero mantenido `models.json`. El binario Tauri (repo nexe-app) lleva una copia de fallback empotrada en tiempo de compilacion (`nexe-app/src-tauri/resources/catalog_fallback.json`), no en este repo. Consulta el catalogo completo mas abajo.

### Seleccion de backend

| Backend | Plataforma | Mejor para |
|---------|------------|------------|
| MLX | Solo Apple Silicon | El mas rapido en serie M, GPU Metal + Neural Engine |
| llama.cpp | macOS + Linux | Formato GGUF universal, aceleracion Metal en Mac |
| Ollama | macOS + Linux + Windows (unico backend en Windows, nuevo en 1.0.7) | Si ya tienes Ollama instalado, la configuracion mas facil |

## Metodo 2: CLI desde codigo fuente

Para usuarios que prefieren instalacion por terminal, desarrollo, o estan en Linux.

```bash
# Linux (Debian/Ubuntu) — prerrequisitos (una sola vez):
# sudo apt-get install -y python3-venv python3-dev build-essential

git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
```

`setup.sh` detecta tu plataforma:
- **macOS:** Comprueba Homebrew, Python 3.11+, crea venv, instala requirements.txt + requirements-macos.txt (rumps para bandeja)
- **Linux:** Sugiere paquetes apt/dnf, crea venv, instala solo requirements.txt

### Instalacion Linux — entorno testeado

Testeado end-to-end en Ubuntu 24.04.4 LTS Desktop ARM64 dentro de una VM UTM en un Mac Apple Silicon (8 GB RAM asignados, backend Ollama en CPU). El instalador detecta directorios de descarga/temporales y mueve la instalacion a `~/.local/share/nexe/` (XDG-compliant). Hardware Linux ARM64/x86_64 nativo aun no validado.

Despues del setup:
```bash
./nexe go    # Iniciar servidor -> http://127.0.0.1:9119
```

## Metodo 3: Instalador DMG SwiftUI (legacy)

> **Estado:** sustituido por la Desktop App (Metodo 1). Se mantiene documentado para instalaciones existentes; para nuevas instalaciones, usa la Desktop App.

Wizard nativo SwiftUI con 6 pantallas, con Python 3.12 bundled e instalacion 100% offline (desde v0.9.9): incluia todos los wheels arm64 pre-compilados (~220 MB, con `llama-cpp-python` pinned a 0.3.19 con Metal), el modelo de embeddings multilingue `paraphrase-multilingual-mpnet-base-v2` en ONNX (~470 MB) y los KB embeddings precomputados para ca/es/en. Tamano del DMG ~1.2 GB; requeria Apple Silicon (M1+) con macOS 14 Sonoma o superior.

## Catalogo de modelos (4 tiers por RAM)

El catalogo canonico vive en `installer/swift-wizard/Resources/models.json` (fuente de verdad, mantenida en el repo y leida por el onboarding wizard). La tabla siguiente lo refleja (actualmente 14 entradas de modelo en 4 tiers poblados; los tiers tier_48 y tier_64 existen pero estan vacios):

### tier_8 (8 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 4B | Ollama, MLX | 👁 | 🧠 | ✓ |

### tier_16 (16 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 9B | Ollama, MLX | 👁 | 🧠 | |
| Qwen3.5 4B (8-bit) | MLX | 👁 | 🧠 | |
| Gemma 4 E4B | Ollama, MLX | 👁 | 🧠 | |
| Mistral Nemo 12B | Ollama, MLX | | 🧠 | |
| Salamandra 7B | Ollama, llama.cpp | | | iberic |

### tier_24 (24 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 27B | Ollama, MLX | 👁 | 🧠 | |
| Mistral Small 3.2 24B | Ollama, MLX | 👁 | 🧠 | |
| GPT-OSS 20B | Ollama, MLX | | 🧠 | |

### tier_32 (32 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 35B-A3B | Ollama, MLX | 👁 | 🧠 | |
| Gemma 4 31B | Ollama, MLX | 👁 | 🧠 | |
| Mixtral 8x7B | Ollama, MLX | | 🧠 | |
| DeepSeek R1 Distill 32B | Ollama, llama.cpp | | 🧠 | |
| ALIA-40B Instruct | Ollama, llama.cpp | | | iberic |

DeepSeek R1 Distill solo Ollama/GGUF (MLX no soporta arch qwen2).

### Como instalar estos modelos

Tanto la familia Qwen3.5 como DeepSeek R1 se instalan via **Ollama**. Primero comprueba que Ollama esta en marcha (viene incluido con el DMG o instalalo desde [ollama.com](https://ollama.com)), despues:

```bash
# Familia Qwen3.5 (multimodal + thinking)
ollama pull qwen3.5:4b          # tier_8, ~3.4 GB
ollama pull qwen3.5:9b          # tier_16, ~6 GB
ollama pull qwen3.5:27b         # tier_24, ~17 GB
ollama pull qwen3.5:35b-a3b     # tier_32 MoE, ~21 GB

# DeepSeek R1 (reasoning)
ollama pull deepseek-r1:32b     # tier_32, ~19 GB
```

Una vez descargado, configuralo en `server.toml` en la raiz del repo (el fichero de override; los valores por defecto estan en `personality/server.toml`):

```toml
[plugins.models]
primary = "qwen3.5:9b"          # o el que hayas elegido
preferred_engine = "ollama"     # obligatorio para estos modelos
```

Reinicia el servidor (`./nexe stop && ./nexe go`, o via el tray) para que tome el cambio.

### Alternativa GGUF para DeepSeek R1

Si quieres usar DeepSeek R1 sin Ollama, descarga un fichero GGUF de un repositorio Hugging Face compatible (p. ej. `unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF`) y colocalo en `storage/models/`. Despues configura `preferred_engine = "llama_cpp"`.

Modelos personalizados: Ollama (por nombre) o Hugging Face (URL de repositorio GGUF).

### Cargar un modelo personalizado

**Ollama** — cualquier modelo del registro público o privado:
```bash
# 1. Descarga el modelo con Ollama
ollama pull nombre-modelo:tag

# 2. Configura server-nexe para usarlo
# Edita server.toml en la raiz del repo:
# [plugins.models]
# primary = "nombre-modelo:tag"
```

**MLX (Hugging Face)** — cualquier repositorio MLX compatible:
```bash
# Descarga el modelo a storage/models/
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('org/nombre-modelo-mlx', local_dir='storage/models/nombre-modelo-mlx')
"

# Configura server.toml:
# [plugins.models]
# primary = "storage/models/nombre-modelo-mlx"
# preferred_engine = "mlx"
```

**llama.cpp (GGUF)** — cualquier fichero `.gguf`:
```bash
# Coloca el fichero en storage/models/
cp /ruta/al/modelo.gguf storage/models/

# Configura server.toml:
# [plugins.models]
# primary = "storage/models/modelo.gguf"
# preferred_engine = "llama_cpp"
```

Reinicia el servidor para aplicar los cambios: `./nexe stop && ./nexe go`

## Verificacion de integridad (SHA256)

Desde la remediacion de la revision interna de seguridad asistida por IA `AUD-INT-001` (§2.7), todos los pesos descargados durante la instalacion se verifican con SHA256 contra un catalogo interno (`installer/installer_catalog_data.py::MODEL_WEIGHT_SHA256`). El check aplica a tres superficies de descarga:

| Backend | Que se verifica | Como |
|---------|-----------------|------|
| **Hugging Face MLX** | SHA256 del directorio del snapshot local (`local_dir` de `snapshot_download`) | `core.integrity.sha256_of_dir` ignorando dotfiles (`.lock`, `.no_exist`, ...) |
| **GGUF** | SHA256 del fichero `.gguf` descargado via `curl` | `core.integrity.sha256_of_file` (stream 64 KB chunks) |
| **Ollama** | Delegado al `pull` content-addressed de Ollama (sin pin propio del cliente, ADR B251) | Ollama verifica cada layer contra el digest del manifest durante `ollama pull`; los tags del catalogo son mutables upstream, asi que un pin de cliente daria falsos positivos en una re-publicacion legitima |
| **fastembed (bundle DMG)** | SHA256 de `model*.onnx`, `tokenizer.json` y `config.json` leidos del manifest `embeddings.manifest.json` generado por `build-embedding-bundle.sh` | `core.integrity.sha256_of_file` via `installer.download_verify.verify_embedding_bundle` |

### Politica en caso de mismatch

Cuando el catalogo lleva un pin (SHA256 concreto) y el valor observado no coincide, la instalacion aborta **hard** con una excepcion `DownloadIntegrityError`. El fichero descargado se **preserva en disco** para inspeccion post-mortem (el installer no borra nunca descargas parciales automaticamente). El mensaje de error incluye:

- Hash esperado vs hash observado (completo, 64 chars).
- Ruta del fichero o directorio descargado.
- Instrucciones de reintento especificas por backend (`ollama rm && ollama pull`, `rm storage/models/<file> && ./nexe model install <name>`, etc.).

### Modo legacy

Las entradas del catalogo con pin `None` (por ejemplo modelos añadidos despues de un DMG ya publicado) **no abortan**. El installer emite un `WARNING` visible (`⚠️ <model>: SHA256 not pinned in catalog`) y continua. Esto preserva la compatibilidad con instalaciones creadas con DMG anteriores a la v1.0.4-beta.

Para el embedding bundle, un DMG sin `embeddings.manifest.json` (build anterior al pinning de los pesos) tambien continua en modo legacy con un warning en stdout.

### Proteccion extra: rechazo de escape por symlinks

`verify_embedding_bundle` rechaza seguir symlinks que apuntan fuera del directorio del bundle, aunque el hash del fichero target coincida con el pin. Impide que un DMG tampered apunte `model.onnx` a un fichero externo con hash conocido.

### Refresco de los hashes

Para MLX y GGUF, cuando un modelo publica una revision nueva en Hugging Face hay que actualizar los pins con el nuevo digest: tier-1 (`MODEL_WEIGHT_SHA256`) descargando el modelo y ejecutando `sha256_of_dir` (MLX) o `sha256sum` (GGUF); tier-2 MLX (por fichero LFS) se regenera metadata-only con `installer/bootstrap_catalog_pins.py`. Ollama **no** tiene pins de cliente (ADR B251): su integridad la garantiza el `pull` content-addressed, asi que no hay que refrescar nada. El test `tests/test_installer_sha256_catalog.py` valida que cada artefacto del catalogo tiene una entrada en el dict (aunque sea `None`).

## Verificacion post-instalacion

```bash
curl http://127.0.0.1:9119/health    # Health check
./nexe modules                        # Listar modulos cargados
./nexe chat                           # Probar chat
open http://127.0.0.1:9119/ui        # Web UI
```

## Encriptacion en reposo (default `auto`)

Despues de la instalacion, la encriptacion se activa automaticamente si sqlcipher3 esta disponible. Para gestionarla manualmente:

```bash
# Activar encriptacion
export NEXE_ENCRYPTION_ENABLED=true

# Comprobar estado actual
./nexe encryption status

# Migrar datos existentes a formato encriptado
./nexe encryption encrypt-all
```

Esto encripta las bases de datos SQLite (via SQLCipher), sesiones de chat (.json -> .enc), y texto de documentos RAG. Consulta SECURITY.md para todos los detalles.

## App de bandeja (NexeTray, macOS)

App de la barra de menu para controlar el servidor sin terminal. Construida sobre el framework `rumps` como la clase `NexeTray` (`installer/tray.py`, 626 lineas). Se arranca automaticamente en modo `--attach` una vez el servidor esta en marcha (lanzada por `core/server/runner.py`). El bundle `installer/NexeTray.app` (bash wrapper, `LSUIElement=true`, `CFBundleIdentifier=net.servernexe.tray`) evita las restricciones de provenance de macOS Sequoia.

### Items del menu (de arriba a abajo)

| Item | Que hace | Codigo |
|------|----------|--------|
| **server.nexe v1.0.7** | Cabecera no clicable. Version leida dinamicamente de `pyproject.toml` via `tomllib` (SSOT). | `tray.py:114-187` |
| **Servidor activo / detenido** | Indicador de estado no clicable. El icono de la barra cambia: `ICON_RUNNING` (verde) cuando esta vivo, `ICON_STOPPED` (gris) cuando no. | `tray.py` |
| **Detener / Iniciar servidor** | Arranca o detiene el proceso `core.app` (uvicorn + FastAPI + Qdrant). SIGTERM y, si hace falta, SIGKILL. PID en `storage/run/server.pid`. | `_toggle_server` |
| **Abrir Web UI** | Abre `http://127.0.0.1:9119/ui` en el navegador por defecto. | `_open_web_ui` |
| **Abrir logs** | Abre `storage/logs/server.log` en el editor asociado a `.log`. | `_open_logs` |
| **Server RAM** | RAM consumida por el proceso servidor + modelo cargado. El polling (`psutil`) corre en un daemon thread (`RamMonitor`, `installer/tray_monitor.py`, 142 lineas) para no bloquear el menu (fix post-v0.9.0 — antes congelaba el teclado). | `tray_monitor.py`; `_update_stats` |
| **Tiempo (uptime)** | Tiempo vivo del servidor calculado desde `server_start_time`. | `_update_stats` |
| **Documentacion** | Abre la documentacion oficial. Item anadido al menu principal para reemplazar un enlace duplicado. | `_open_docs` |
| **Configuracion** | Submenu con 3 opciones: | `tray.py` |
| ↳ server-nexe.com | Abre la web oficial en el navegador. | `_open_website` |
| ↳ Apoyar el proyecto | Abre GitHub Sponsors. | `_open_donate` |
| ↳ Desinstalar Nexe | Lanza el desinstalador con doble confirmacion, calcula el espacio, elimina entradas Dock/Login Items, hace backup de `storage/` con timestamp. **NO elimina la carpeta del proyecto** (opcion de seguridad). | `_uninstall` + `installer/tray_uninstaller.py` (264 lineas) |
| **Salir** | Detiene el servidor (si esta corriendo) y cierra la app de la bandeja. | `_quit` |

### Actualizacion automatica

Un `rumps.Timer(self._update_stats, 5)` (`tray.py:217`) ejecuta el callback `_update_stats` (`tray.py:428`) cada 5 segundos: refresca RAM, uptime, y verifica estado (si el proceso murio inesperadamente → cambia icono y status).

### Traducciones

El idioma se detecta de `$LANG` / system locale en `_detect_lang`. Todas las cadenas viven en el diccionario `T` de `installer/tray_translations.py` (135 lineas) con 3 variantes: `ca` (canonico), `es`, `en`.

## Desinstalador

Accesible desde el menu de la bandeja. Doble confirmacion, calcula espacio, elimina elementos del Dock/Inicio, backup de storage/ con timestamp, NO elimina la carpeta.

## Resolucion de problemas

| Problema | Solucion |
|----------|----------|
| Puerto 9119 en uso | `lsof -i :9119` luego matar, o cambiar en server.toml |
| Qdrant no arranca | Verifica que `storage/vectors/` es escribible y no tiene lock files (`*.lock`). Reinicia el servidor. |
| Ollama no encontrado | Instalar desde ollama.com, o usar MLX/llama.cpp |
| Error de version de Python | Requiere 3.11+. El DMG incluye 3.12. |
| MLX no disponible | Solo Apple Silicon. Usar llama.cpp u Ollama. |
| Descarga de modelo lenta | Los modelos grandes tardan 30+ min. Timeout 600s. |
| OOM killed | Elegir modelo mas pequeno. 8GB -> modelos 2B. |

## Variables de entorno clave

| Variable | Proposito | Por defecto |
|----------|-----------|-------------|
| NEXE_PRIMARY_API_KEY | API key principal | (generada) |
| NEXE_MODEL_ENGINE | Backend por defecto | auto |
| NEXE_OLLAMA_MODEL | Modelo Ollama | (seleccionado durante la instalacion) |
| NEXE_LLAMA_CPP_MODEL | Ruta del modelo GGUF | storage/models/*.gguf |
| NEXE_DEFAULT_MAX_TOKENS | Tokens maximos de respuesta | 4096 |
| NEXE_LANG | Idioma del servidor | en |
| NEXE_ENV | Entorno | production |
| NEXE_ENCRYPTION_ENABLED | Activar encriptacion en reposo | auto (se activa si sqlcipher3 disponible) |
| NEXE_OLLAMA_THINK | Default global de thinking tokens para modelos Ollama | false |
| NEXE_OLLAMA_EMBED_MODEL | Modelo de embeddings Ollama (opcional, fallback) | nomic-embed-text |
