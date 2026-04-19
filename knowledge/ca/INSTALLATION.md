# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-installation-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Com instal-lar server-nexe: 2 metodes. (1) DMG per macOS amb wizard SwiftUI, Python 3.12 inclos, models per tiers de RAM. (2) CLI: git clone + ./setup.sh (macOS/Linux). Requisits: macOS 14+ Sonoma Apple Silicon (M1+), 8GB RAM minim. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Port per defecte: 9119."
tags: [installation, setup, dmg, swiftui, wizard, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Instal·lacio — server-nexe 1.0.1-beta

## En 30 segons

- **2 metodes:** DMG (macOS, wizard SwiftUI) o CLI (`./setup.sh`)
- **DMG ~1.2 GB offline** (wheels + embedding model bundled)
- **Requereix macOS 14 Sonoma + Apple Silicon** (M1+)
- **Tria model segons RAM** (cataleg 16 models, 4 tiers 8/16/24/32 GB)
- **Port per defecte:** 9119

---

Dos metodes d'instal·lacio disponibles. Tria segons la teva plataforma i preferencies.

## Requisits del sistema

| Requisit | Minim | Recomanat |
|------------|---------|-------------|
| SO | **macOS 14 Sonoma** (Apple Silicon) / Linux ARM64 Ubuntu 24.04 (testejat a VM) / Linux x86_64 (parcial) | macOS 14+ (Apple Silicon M1+) |
| CPU | **Apple Silicon (M1+) obligatori** — Intel NO suportat | M2 Pro / M3 Pro / M4 |
| RAM | 8 GB | 16+ GB |
| Disc | 10 GB lliures | 20+ GB (per a models grans) |
| Python | 3.11+ (metode CLI) | 3.12 inclos (metode DMG) |

> **Breaking a v0.9.9:** macOS 13 Ventura i macOS Intel queden fora del target suportat. El stack (mlx, mlx-vlm, fastembed ONNX, llama-cpp-python amb Metal, wheels arm64) requereix macOS 14 Sonoma i Apple Silicon.

## Metode 1: Instal·lador DMG per a macOS (recomanat)

Wizard natiu SwiftUI amb 6 pantalles. Inclou Python 3.12 — sense dependencia del Python del sistema.

### ⚡ Instal·lacio 100% offline (des de v0.9.9)

A partir d'aquesta versio, el DMG porta **tot** el que l'installer necessita:

- Runtime Python 3.12 (~45 MB)
- **Tots els wheels de Python** pre-compilats per a arm64 macOS 14+ (~220 MB): fastapi, pydantic, mlx-lm, mlx-vlm, **llama-cpp-python pinned a 0.3.19** (amb Metal; la 0.3.20 té wheels corruptes Bad CRC-32 al servidor de paquets i s'ha evitat explicitament), fastembed, onnxruntime, sqlcipher3, cryptography, i la resta del stack.
- **Model d'embeddings multilingue** pre-descarregat (~470 MB): `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` en format ONNX (carregat via fastembed).
- **KB embeddings precomputats** a `knowledge/.embeddings/` per ca/es/en (10.7× speedup a la primera arrencada).

Efectes practics:

- Mida del DMG: **~1.2 GB** (creix per wheels + embedding model bundled per facilitar instal·lació offline a altres equips).
- Un cop baixat el DMG, l'instal·lacio **no requereix xarxa** i no necessita Xcode Command Line Tools (sense prompt de `CMAKE_ARGS`).
- **Cap prompt de macOS demanant "eines de desenvolupador"** durant l'install.
- RAG funcional al primer boot: el model d'embeddings ja esta present.
- L'unica cosa que segueix requerint xarxa post-install es la descarrega del model LLM que trieu (Qwen, Gemma, DeepSeek, etc.), si no useu un model ja present a Ollama local.
- Fallback a PyPI si algun wheel del bundle falta (robustesa).

Requisit: **Apple Silicon (M1+) amb macOS 14 Sonoma o superior**. Intel Mac i macOS 13 Ventura ja no son un target suportat.

### Que fa el wizard

1. **Benvinguda:** Selector d'idioma (ca/es/en), logotip, informacio de versio
2. **Desti:** Selector de carpeta amb validacio d'espai lliure
3. **Seleccio de model:** 4 pestanyes (petit/mitja/gran/personalitzat) amb deteccio de maquinari. Mostra 15 models amb requisits de RAM, compatibilitat de motor i any. Recomana models basant-se en la RAM/GPU detectada.
4. **Confirmacio:** Resum de les opcions abans d'instal·lar
5. **Progres:** Barra de progres de 7 passos amb log en temps real. Parser de protocol Python (marcadors [PROGRESS], [LOG], [DONE], [ERROR]). 8-30 minuts depenent de la descarrega del model.
6. **Finalitzacio:** Visualitzacio de la clau API, opcions per afegir al Dock i als Elements d'inici, compte enrere per al llancament

### Deteccio de maquinari

El wizard utilitza crides natives a `sysctl` per detectar:
- Xip CPU (M1/M2/M3/M4, Intel)
- RAM total
- Suport de GPU Metal
- Espai lliure en disc

Basant-se en la deteccio, recomana el backend i els models adequats.

### Seleccio de backend

| Backend | Plataforma | Ideal per a |
|---------|----------|----------|
| MLX | Nomes Apple Silicon | El mes rapid en serie M, GPU Metal + Neural Engine |
| llama.cpp | macOS + Linux | Format GGUF universal, acceleracio Metal a Mac |
| Ollama | macOS + Linux | Si ja tens Ollama instal·lat, la configuracio mes facil |

### Descarrega

Descarrega el DMG des de la pagina de releases de GitHub: https://github.com/jgoy-labs/server-nexe/releases

## Metode 2: CLI headless

Per a usuaris que prefereixen la instal·lacio per terminal o estan a Linux.

```bash
# Linux (Debian/Ubuntu) — prerequisits (un sol cop):
# sudo apt-get install -y python3-venv python3-dev build-essential

git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
```

`setup.sh` detecta la teva plataforma:
- **macOS:** Comprova Homebrew, Python 3.11+, crea venv, instal·la requirements.txt + requirements-macos.txt (rumps per a la safata)
- **Linux:** Suggereix paquets apt/dnf, crea venv, instal·la nomes requirements.txt

### Instal·lacio Linux — entorn testejat

Testejat end-to-end a Ubuntu 24.04.4 LTS Desktop ARM64 dins una VM UTM en un Mac Apple Silicon (8 GB RAM assignats, backend Ollama a CPU). L'instal·lador detecta directoris de descarrega/temporals i mou la instal·lacio a `~/.local/share/nexe/` (XDG-compliant). Hardware Linux ARM64/x86_64 natiu encara no validat.

Despres de la configuracio:
```bash
./nexe go    # Arrencar servidor -> http://127.0.0.1:9119
```

## Cataleg de models (16 models, 4 tiers — verificat 2026-04-16)

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

Familia Qwen3.5 nomes funciona via Ollama (MLX requereix torch). DeepSeek R1 nomes Ollama/GGUF (MLX no suporta arch qwen2).

### Com instal·lar aquests models

Tant Qwen3.5 family com DeepSeek R1 s'instal·len via **Ollama**. Primer comprova que tens Ollama en marxa (ve bundled amb el DMG o instal·la'l des d'[ollama.com](https://ollama.com)), despres:

```bash
# Qwen3.5 family (multimodal + thinking)
ollama pull qwen3.5:4b          # tier_8, ~3.4 GB
ollama pull qwen3.5:9b          # tier_16, ~6 GB
ollama pull qwen3.5:27b         # tier_32, ~17 GB
ollama pull qwen3.5:35b-a3b     # tier_32 MoE, ~21 GB

# DeepSeek R1 (reasoning)
ollama pull deepseek-r1:32b     # tier_32, ~19 GB
```

Un cop descarregat, configura'l a `storage/config/server.toml`:

```toml
[plugins.models]
primary = "qwen3.5:9b"          # o el que hagis triat
preferred_engine = "ollama"     # obligatori per aquests models
```

Reinicia el servidor (`./nexe restart` o via el tray) perque agafi el canvi.

### Alternativa GGUF per a DeepSeek R1

Si vols usar DeepSeek R1 sense Ollama, descarrega un fitxer GGUF d'un repositori Hugging Face compatible (p. ex. `unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF`) i col·loca'l a `storage/models/`. Despres configura `preferred_engine = "llama_cpp"`.

Models personalitzats: Ollama (per nom) o Hugging Face (URL de repositori GGUF).

### Carregar un model personalitzat

**Ollama** — qualsevol model del registre públic o privat:
```bash
# 1. Descarrega el model amb Ollama
ollama pull nom-del-model:tag

# 2. Configura server-nexe per usar-lo
# Edita storage/config/server.toml:
# [plugins.models]
# primary = "nom-del-model:tag"
```

**MLX (Hugging Face)** — qualsevol repositori MLX compatible:
```bash
# Descarrega el model a storage/models/
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('organitzacio/nom-model-mlx', local_dir='storage/models/nom-model-mlx')
"

# Configura server.toml:
# [plugins.models]
# primary = "storage/models/nom-model-mlx"
# preferred_engine = "mlx"
```

**llama.cpp (GGUF)** — qualsevol fitxer `.gguf`:
```bash
# Col·loca el fitxer a storage/models/
cp /ruta/al/model.gguf storage/models/

# Configura server.toml:
# [plugins.models]
# primary = "storage/models/model.gguf"
# preferred_engine = "llama_cpp"
```

Reinicia el servidor per aplicar els canvis: `./nexe restart`

## Verificacio post-instal·lacio

```bash
curl http://127.0.0.1:9119/health    # Health check
./nexe modules                        # Llistar moduls carregats
./nexe chat                           # Provar xat
open http://127.0.0.1:9119/ui        # Web UI
```

## Encriptacio at-rest (default `auto`)

Despres de la instal·lacio, l'encriptacio s'activa automaticament si sqlcipher3 esta disponible. Per gestionar-la manualment:

```bash
# Activar encriptacio
export NEXE_ENCRYPTION_ENABLED=true

# Comprovar estat actual
./nexe encryption status

# Migrar dades existents a format encriptat
./nexe encryption encrypt-all
```

Aixo encripta les bases de dades SQLite (via SQLCipher), les sessions de xat (.json -> .enc) i el text de documents RAG. Consulta SECURITY.md per a tots els detalls.

## App de safata (NexeTray, macOS)

Aplicacio de la barra de menu per controlar el servidor sense terminal. Implementada amb el framework `rumps` a la classe `NexeTray` (`installer/tray.py`, 655 linies). S'arrenca automaticament en mode `--attach` un cop el servidor esta en marxa (llançat per `core/server/runner.py`). El bundle `installer/NexeTray.app` (bash wrapper, `LSUIElement=true`, `CFBundleIdentifier=net.servernexe.tray`) evita les restriccions de provenance de macOS Sequoia.

### Funcions del menu (d'amunt a avall)

| Opcio | Que fa | Codi |
|-------|--------|------|
| **server.nexe v1.0.1-beta** | Capçalera no clicable. La versio es llegeix dinamicament de `pyproject.toml` via `tomllib` (SSOT). | `tray.py:170-180, 246` |
| **Servidor actiu / aturat** | Indicador d'estat (no clicable). La icona de la barra canvia: `ICON_RUNNING` (verda) quan el servidor esta viu, `ICON_STOPPED` (gris) quan no. | `tray.py:197` |
| **Aturar / Iniciar servidor** | Engega o atura el proces `core.app` (uvicorn + FastAPI + Qdrant). Fa SIGTERM i, si cal, SIGKILL. Gestio de PID a `storage/run/server.pid`. | `_toggle_server` → `tray.py:296` |
| **Obrir Web UI** | Obre `http://127.0.0.1:9119/ui` al navegador per defecte. | `_open_web_ui` → `tray.py:509` |
| **Obrir logs** | Obre `storage/logs/server.log` a l'editor associat amb `.log`. | `_open_logs` → `tray.py:512` |
| **Server RAM** | RAM consumida pel proces servidor + model carregat. El polling (`psutil`) es fa a un daemon thread (`_RamMonitor`, `installer/tray_monitor.py`, 141 linies) per no bloquejar el menu (fix post-v0.9.0 — abans freezava el teclat). | `tray_monitor.py`; `tray.py:205` |
| **Temps (uptime)** | Temps viu del servidor calculat des de `server_start_time`. | `tray.py:208` |
| **Documentacio** | Obre la documentacio oficial. Item afegit al menu principal (Bug #9) per reemplaçar un enllaç duplicat. | `_open_docs` → `tray.py:523` |
| **Configuracio** | Submenu amb 3 opcions: | `tray.py:227-243` |
| ↳ server-nexe.com | Obre la web oficial al navegador. | `_open_website` → `tray.py:520` |
| ↳ Suportar el projecte | Obre GitHub Sponsors. | `_open_donate` → `tray.py:528` |
| ↳ Desinstal·lar Nexe | Llança el desinstal·lador amb doble confirmacio, calcula l'espai, elimina entrades Dock/Login Items, fa backup de `storage/` amb marca de temps. **NO esborra la carpeta del projecte** (opcio de seguretat). | `_uninstall` → `tray.py:531` + `installer/tray_uninstaller.py` (284 linies) |
| **Sortir** | Atura el servidor si esta corrent i tanca l'app del tray. | `_quit` → `tray.py:581` |

### Actualitzacio automatica

Un `rumps.Timer(self._update_stats, 5)` executa el callback `_update_stats` (`tray.py:458`) cada 5 segons: refresca RAM, uptime, i verifica estat (si el proces ha mort inesperadament → canvia icona i status).

### Traduccions

L'idioma es detecta de `$LANG` / system locale a `_detect_lang`. Totes les cadenes viuen al diccionari `T` de `installer/tray_translations.py` (135 linies) amb 3 variants: `ca` (canonic), `es`, `en`.

## Desinstal·lador

Accessible des del menu de la safata. Doble confirmacio, calcula l'espai, elimina elements del Dock/Inici, copia de seguretat de storage/ amb marca de temps, NO esborra la carpeta.

## Resolucio de problemes

| Problema | Solucio |
|---------|----------|
| Port 9119 en us | `lsof -i :9119` i matar el proces, o canviar a server.toml |
| Qdrant no arrenca | Verifica que `storage/vectors/` és escrivible i no té lock files (`*.lock`). Reinicia el servidor. |
| Ollama no trobat | Instal·la des d'ollama.com, o utilitza MLX/llama.cpp |
| Error de versio de Python | Requereix 3.11+. El DMG inclou 3.12. |
| MLX no disponible | Nomes Apple Silicon. Utilitza llama.cpp o Ollama. |
| Descarrega de model lenta | Els models grans triguen 30+ min. Timeout de 600s. |
| OOM killed | Tria un model mes petit. 8GB -> models 2B. |

## Variables d'entorn clau

| Variable | Proposit | Per defecte |
|----------|---------|---------|
| NEXE_PRIMARY_API_KEY | Clau API principal | (generada) |
| NEXE_MODEL_ENGINE | Backend per defecte | auto |
| NEXE_OLLAMA_MODEL | Model d'Ollama | (seleccionat durant la instal·lacio) |
| NEXE_LLAMA_CPP_MODEL | Ruta del model GGUF | storage/models/*.gguf |
| NEXE_DEFAULT_MAX_TOKENS | Tokens maxims de resposta | 4096 |
| NEXE_LANG | Idioma del servidor | ca |
| NEXE_ENV | Entorn | production |
| NEXE_ENCRYPTION_ENABLED | Activar encriptacio at-rest | auto (s'activa si sqlcipher3 disponible) |
| NEXE_OLLAMA_THINK | Default global de thinking tokens per a models Ollama | false |
| NEXE_OLLAMA_EMBED_MODEL | Model d'embeddings Ollama (opcional, fallback) | nomic-embed-text |
