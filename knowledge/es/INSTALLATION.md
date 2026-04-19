# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-installation-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Como instalar server-nexe: 2 metodos. (1) DMG para macOS con wizard SwiftUI, Python 3.12 incluido, modelos por tiers de RAM. (2) CLI: git clone + ./setup.sh (macOS/Linux). Requisitos: macOS 14+ Sonoma Apple Silicon (M1+), 8GB RAM minimo. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Puerto por defecto: 9119."
tags: [installation, setup, dmg, swiftui, wizard, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Instalacion — server-nexe 1.0.0-beta

## En 30 segundos

- **2 metodos:** DMG (macOS, wizard SwiftUI) o CLI (`./setup.sh`)
- **DMG ~1.2 GB offline** (wheels + modelo de embeddings bundled)
- **Requiere macOS 14 Sonoma + Apple Silicon** (M1+)
- **Elige modelo segun RAM** (catalogo 16 modelos, 4 tiers 8/16/24/32 GB)
- **Puerto por defecto:** 9119

---

Dos metodos de instalacion disponibles. Elige segun tu plataforma y preferencias.

## Requisitos del sistema

| Requisito | Minimo | Recomendado |
|-----------|--------|-------------|
| SO | **macOS 14 Sonoma** (Apple Silicon) / Linux ARM64 Ubuntu 24.04 (testeado en VM) / Linux x86_64 (parcial) | macOS 14+ (Apple Silicon M1+) |
| CPU | **Apple Silicon (M1+) obligatorio** — Intel NO soportado | M2 Pro / M3 Pro / M4 |
| RAM | 8 GB | 16+ GB |
| Disco | 10 GB libres | 20+ GB (para modelos mas grandes) |
| Python | 3.11+ (metodo CLI) | 3.12 incluido (metodo DMG) |

> **Breaking en v0.9.9:** macOS 13 Ventura y macOS Intel quedan fuera del target soportado. El stack (mlx, mlx-vlm, fastembed ONNX, llama-cpp-python con Metal, wheels arm64) requiere macOS 14 Sonoma y Apple Silicon.

## Metodo 1: Instalador DMG para macOS (Recomendado)

Wizard nativo SwiftUI con 6 pantallas. Incluye Python 3.12 — sin dependencia del Python del sistema.

### ⚡ Instalacion 100% offline (desde v0.9.9)

A partir de esta version, el DMG incluye **todo** lo que necesita el instalador:

- Runtime Python 3.12 (~45 MB)
- **Todos los wheels de Python** pre-compilados para arm64 macOS 14+ (~220 MB): fastapi, pydantic, mlx-lm, mlx-vlm, **llama-cpp-python pinned a 0.3.19** (con Metal; la 0.3.20 tiene wheels corruptos Bad CRC-32 en el servidor de paquetes y se ha evitado explicitamente), fastembed, onnxruntime, sqlcipher3, cryptography, y el resto del stack.
- **Modelo de embeddings multilingue** pre-descargado (~470 MB): `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` en formato ONNX (cargado via fastembed).
- **KB embeddings precomputados** en `knowledge/.embeddings/` para ca/es/en (10.7× speedup en el primer arranque).

Efectos practicos:

- Tamano del DMG: **~1.2 GB** (crece por wheels + embedding model bundled para facilitar instalacion offline en otros equipos).
- Una vez descargado el DMG, la instalacion **no requiere red** y no necesita Xcode Command Line Tools (sin prompt de `CMAKE_ARGS`).
- **Ningun prompt de macOS pidiendo "herramientas de desarrollador"** durante el install.
- RAG funcional en el primer arranque: el modelo de embeddings ya esta presente.
- Lo unico que sigue requiriendo red tras la instalacion es la descarga del modelo LLM que elijas (Qwen, Gemma, DeepSeek, etc.), si no usas un modelo ya presente en Ollama local.
- Fallback a PyPI si algun wheel del bundle falta (robustez).

Requisito: **Apple Silicon (M1+) con macOS 14 Sonoma o superior**. Los Mac Intel y macOS 13 Ventura ya no son un target soportado.

### Que hace el wizard

1. **Bienvenida:** Selector de idioma (ca/es/en), logo, info de version
2. **Destino:** Selector de carpeta con validacion de espacio libre
3. **Seleccion de modelo:** 4 pestanas (pequeno/mediano/grande/personalizado) con deteccion de hardware. Muestra 15 modelos con requisitos de RAM, compatibilidad de motor y ano. Recomienda modelos segun la RAM/GPU detectadas.
4. **Confirmacion:** Resumen de las elecciones antes de instalar
5. **Progreso:** Barra de progreso de 7 pasos con log en tiempo real. Parser de protocolo Python ([PROGRESS], [LOG], [DONE], [ERROR]). 8-30 minutos dependiendo de la descarga del modelo.
6. **Finalizacion:** Muestra la API key, opciones para anadir al Dock y a Elementos de Inicio, cuenta atras para el lanzamiento

### Deteccion de hardware

El wizard usa llamadas nativas a `sysctl` para detectar:
- Chip CPU (M1/M2/M3/M4, Intel)
- RAM total
- Soporte de GPU Metal
- Espacio libre en disco

Segun la deteccion, recomienda el backend y modelos apropiados.

### Seleccion de backend

| Backend | Plataforma | Mejor para |
|---------|------------|------------|
| MLX | Solo Apple Silicon | El mas rapido en serie M, GPU Metal + Neural Engine |
| llama.cpp | macOS + Linux | Formato GGUF universal, aceleracion Metal en Mac |
| Ollama | macOS + Linux | Si ya tienes Ollama instalado, la configuracion mas facil |

### Descarga

Descarga el DMG desde la pagina de releases de GitHub: https://github.com/jgoy-labs/server-nexe/releases

## Metodo 2: CLI Headless

Para usuarios que prefieren instalacion por terminal o estan en Linux.

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

## Catalogo de modelos (16 modelos, 4 tiers — verificado 2026-04-16)

### tier_8 (8 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Gemma 3 4B | Ollama, MLX | 👁 | 🧠 | MLX |
| Qwen3.5 4B | Ollama | 👁 | 🧠 | Ollama |
| Qwen3 4B | Ollama, MLX | | | |

### tier_16 (16 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Gemma 4 E4B | Ollama, MLX | 👁 | 🧠 | MLX |
| Salamandra 7B | Ollama, llama.cpp | | | iberic |
| Qwen3.5 9B | Ollama | 👁 | 🧠 | Ollama |
| Gemma 3 12B | Ollama, MLX | 👁 | 🧠 | |

### tier_24 (24 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Gemma 4 31B | Ollama, MLX | 👁 | 🧠 | ✓ |
| Qwen3 14B | Ollama, MLX | | 🧠 | ✓ |
| GPT-OSS 20B | Ollama, MLX | | 🧠 | |

### tier_32 (32 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 27B | Ollama | 👁 | 🧠 | |
| Gemma 3 27B | MLX, llama.cpp | 👁 | 🧠 | |
| DeepSeek R1 32B | Ollama, llama.cpp | | 🧠 | |
| Gemma 4 31B | Ollama, MLX | 👁 | 🧠 | MLX |
| Qwen3.5 35B-A3B | Ollama | 👁 | 🧠 | |
| ALIA-40B | Ollama, llama.cpp | | | iberic |

La familia Qwen3.5 solo funciona via Ollama (MLX requiere torch). DeepSeek R1 solo Ollama/GGUF (MLX no soporta arch qwen2).

### Como instalar estos modelos

Tanto la familia Qwen3.5 como DeepSeek R1 se instalan via **Ollama**. Primero comprueba que Ollama esta en marcha (viene incluido con el DMG o instalalo desde [ollama.com](https://ollama.com)), despues:

```bash
# Familia Qwen3.5 (multimodal + thinking)
ollama pull qwen3.5:4b          # tier_8, ~3.4 GB
ollama pull qwen3.5:9b          # tier_16, ~6 GB
ollama pull qwen3.5:27b         # tier_32, ~17 GB
ollama pull qwen3.5:35b-a3b     # tier_32 MoE, ~21 GB

# DeepSeek R1 (reasoning)
ollama pull deepseek-r1:32b     # tier_32, ~19 GB
```

Una vez descargado, configuralo en `storage/config/server.toml`:

```toml
[plugins.models]
primary = "qwen3.5:9b"          # o el que hayas elegido
preferred_engine = "ollama"     # obligatorio para estos modelos
```

Reinicia el servidor (`./nexe restart` o via el tray) para que tome el cambio.

### Alternativa GGUF para DeepSeek R1

Si quieres usar DeepSeek R1 sin Ollama, descarga un fichero GGUF de un repositorio Hugging Face compatible (p. ej. `unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF`) y colocalo en `storage/models/`. Despues configura `preferred_engine = "llama_cpp"`.

Modelos personalizados: Ollama (por nombre) o Hugging Face (URL de repositorio GGUF).

### Cargar un modelo personalizado

**Ollama** — cualquier modelo del registro público o privado:
```bash
# 1. Descarga el modelo con Ollama
ollama pull nombre-modelo:tag

# 2. Configura server-nexe para usarlo
# Edita storage/config/server.toml:
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

Reinicia el servidor para aplicar los cambios: `./nexe restart`

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

App de la barra de menu para controlar el servidor sin terminal. Construida sobre el framework `rumps` como la clase `NexeTray` (`installer/tray.py`, 655 lineas). Se arranca automaticamente en modo `--attach` una vez el servidor esta en marcha (lanzada por `core/server/runner.py`). El bundle `installer/NexeTray.app` (bash wrapper, `LSUIElement=true`, `CFBundleIdentifier=net.servernexe.tray`) evita las restricciones de provenance de macOS Sequoia.

### Items del menu (de arriba a abajo)

| Item | Que hace | Codigo |
|------|----------|--------|
| **server.nexe v1.0.0-beta** | Cabecera no clicable. Version leida dinamicamente de `pyproject.toml` via `tomllib` (SSOT). | `tray.py:170-180, 246` |
| **Servidor activo / detenido** | Indicador de estado no clicable. El icono de la barra cambia: `ICON_RUNNING` (verde) cuando esta vivo, `ICON_STOPPED` (gris) cuando no. | `tray.py:197` |
| **Detener / Iniciar servidor** | Arranca o detiene el proceso `core.app` (uvicorn + FastAPI + Qdrant). SIGTERM y, si hace falta, SIGKILL. PID en `storage/run/server.pid`. | `_toggle_server` → `tray.py:296` |
| **Abrir Web UI** | Abre `http://127.0.0.1:9119/ui` en el navegador por defecto. | `_open_web_ui` → `tray.py:509` |
| **Abrir logs** | Abre `storage/logs/server.log` en el editor asociado a `.log`. | `_open_logs` → `tray.py:512` |
| **Server RAM** | RAM consumida por el proceso servidor + modelo cargado. El polling (`psutil`) corre en un daemon thread (`_RamMonitor`, `installer/tray_monitor.py`, 141 lineas) para no bloquear el menu (fix post-v0.9.0 — antes congelaba el teclado). | `tray_monitor.py`; `tray.py:205` |
| **Tiempo (uptime)** | Tiempo vivo del servidor calculado desde `server_start_time`. | `tray.py:208` |
| **Documentacion** | Abre la documentacion oficial. Item anadido al menu principal (Bug #9) para reemplazar un enlace duplicado. | `_open_docs` → `tray.py:523` |
| **Configuracion** | Submenu con 3 opciones: | `tray.py:227-243` |
| ↳ server-nexe.com | Abre la web oficial en el navegador. | `_open_website` → `tray.py:520` |
| ↳ Apoyar el proyecto | Abre GitHub Sponsors. | `_open_donate` → `tray.py:528` |
| ↳ Desinstalar Nexe | Lanza el desinstalador con doble confirmacion, calcula el espacio, elimina entradas Dock/Login Items, hace backup de `storage/` con timestamp. **NO elimina la carpeta del proyecto** (opcion de seguridad). | `_uninstall` → `tray.py:531` + `installer/tray_uninstaller.py` (284 lineas) |
| **Salir** | Detiene el servidor (si esta corriendo) y cierra la app de la bandeja. | `_quit` → `tray.py:581` |

### Actualizacion automatica

Un `rumps.Timer(self._update_stats, 5)` ejecuta el callback `_update_stats` (`tray.py:458`) cada 5 segundos: refresca RAM, uptime, y verifica estado (si el proceso murio inesperadamente → cambia icono y status).

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
| NEXE_LANG | Idioma del servidor | ca |
| NEXE_ENV | Entorno | production |
| NEXE_ENCRYPTION_ENABLED | Activar encriptacion en reposo | auto (se activa si sqlcipher3 disponible) |
| NEXE_OLLAMA_THINK | Default global de thinking tokens para modelos Ollama | false |
| NEXE_OLLAMA_EMBED_MODEL | Modelo de embeddings Ollama (opcional, fallback) | nomic-embed-text |
