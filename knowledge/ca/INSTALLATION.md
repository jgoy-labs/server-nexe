# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-installation-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Com instal-lar server-nexe: (1) Desktop App nexe-app (Tauri v2, recomanat) — DMG macOS (~1.3 GB) i AppImage Linux ARM64 (~1.2 GB) des de Releases, amb onboarding wizard (deteccio hardware, tria backend, descarrega model) i mode sidecar amb safata. (2) CLI des de codi font: git clone + ./setup.sh (macOS/Linux). (3) Legacy: DMG SwiftUI standalone (substituit per la Desktop App). Requisits: macOS 14+ Apple Silicon (M1+) o Linux ARM64, 8GB RAM. Backends: MLX, llama.cpp, Ollama. Cataleg a models.json. Port: 9119."
tags: [installation, setup, desktop-app, tauri, appimage, dmg, cli, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, encryption, sidecar, wizard, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Instal·lacio — server-nexe 1.0.6

## En 30 segons

- **3 metodes:** Desktop App nexe-app (Tauri, recomanat), CLI des de codi font (`./setup.sh`), o l'installer DMG SwiftUI legacy
- **Desktop App:** DMG per macOS (~1.3 GB) + AppImage per Linux ARM64 (~1.2 GB), des de [Releases](https://github.com/jgoy-labs/server-nexe/releases/latest)
- **Requereix macOS 14 Sonoma + Apple Silicon** (M1+) o Linux ARM64
- **Tria de model segons RAM:** l'onboarding wizard llegeix el cataleg mantingut (`models.json`) i recomana per la teva RAM
- **Port per defecte:** 9119

---

Tres metodes d'instal·lacio disponibles. Tria segons la teva plataforma i preferencies.

## Requisits del sistema

| Requisit | Minim | Recomanat |
|------------|---------|-------------|
| SO | **macOS 14 Sonoma** (Apple Silicon) / Linux ARM64 Ubuntu 24.04 (testejat a VM) / Linux x86_64 (parcial) | macOS 14+ (Apple Silicon M1+) |
| CPU | **Apple Silicon (M1+) obligatori** — Intel NO suportat | M2 Pro / M3 Pro / M4 |
| RAM | 8 GB | 16+ GB |
| Disc | 10 GB lliures | 20+ GB (per a models grans) |
| Python | 3.11+ (metode CLI) | 3.12 inclos (metode DMG) |

> **Breaking a v0.9.9:** macOS 13 Ventura i macOS Intel queden fora del target suportat. El stack (mlx, mlx-vlm, fastembed ONNX, llama-cpp-python amb Metal, wheels arm64) requereix macOS 14 Sonoma i Apple Silicon.

## Metode 1: Desktop App — nexe-app (Tauri v2, recomanat)

Aplicacio d'escriptori que embeu server-nexe com a sidecar Python dins una shell Tauri v2. Es el metode recomanat i el canal de release public.

Descarrega l'ultim paquet des de la pagina de [Releases](https://github.com/jgoy-labs/server-nexe/releases/latest):

| Plataforma | Paquet | Mida |
|------------|--------|------|
| macOS (Apple Silicon) | `nexe-app_1.0.6_aarch64.dmg` | ~1.3 GB |
| Linux (ARM64) | `nexe-app_1.0.6_aarch64.AppImage` | ~1.2 GB |

- **Onboarding wizard** integrat al frontend (HTML/JS, no SwiftUI): deteccio de hardware, seleccio de backend, descarrega del model i configuracio, tot des de la mateixa app.
- **Mode sidecar:** server-nexe corre amb `NEXE_SIDECAR=1`; els paths els gestiona Tauri (`NEXE_HOME`, `NEXE_DATA_DIR`).
- **Safata de sistema** i gestio automatica del proces sidecar.
- **Cross-platform:** macOS (Apple Silicon) + Linux (ARM64).
- **Ollama bundled** o auto-instal·lat.

El cataleg de models el llegeix el wizard del fitxer mantingut `models.json`. El binari Tauri (repo nexe-app) en porta una copia de fallback empotrada en temps de compilacio (`nexe-app/src-tauri/resources/catalog_fallback.json`), no a aquest repo. Vegeu el cataleg complet mes avall.

### Seleccio de backend

| Backend | Plataforma | Ideal per a |
|---------|----------|----------|
| MLX | Nomes Apple Silicon | El mes rapid en serie M, GPU Metal + Neural Engine |
| llama.cpp | macOS + Linux | Format GGUF universal, acceleracio Metal a Mac |
| Ollama | macOS + Linux | Si ja tens Ollama instal·lat, la configuracio mes facil |

## Metode 2: CLI des de codi font

Per a usuaris que prefereixen la instal·lacio per terminal, desenvolupament, o Linux.

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

## Metode 3: Installer DMG SwiftUI (legacy)

> **Estat:** substituit per la Desktop App (Metode 1). Es mante documentat per a instal·lacions existents; per a noves instal·lacions, fes servir la Desktop App.

Wizard natiu SwiftUI amb 6 pantalles, amb Python 3.12 bundled i instal·lacio 100% offline (des de v0.9.9): portava tots els wheels arm64 pre-compilats (~220 MB, amb `llama-cpp-python` pinned a 0.3.19 amb Metal), el model d'embeddings multilingue `paraphrase-multilingual-mpnet-base-v2` en ONNX (~470 MB) i els KB embeddings precomputats per ca/es/en. Mida del DMG ~1.2 GB; requeria Apple Silicon (M1+) amb macOS 14 Sonoma o superior.

## Cataleg de models (4 tiers per RAM)

El cataleg canonic viu a `installer/swift-wizard/Resources/models.json` (font de veritat, mantinguda al repo i llegida per l'onboarding wizard). La taula seguent n'es un reflex (actualment 15 entrades de model en 4 tiers; 14 models distints, ja que Gemma 4 31B apareix a 2 tiers):

### tier_8 (8 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 4B | Ollama, MLX | 👁 | 🧠 | ✓ |

### tier_16 (16 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 9B | Ollama, MLX | 👁 | 🧠 | |
| Qwen3.5 4B (8-bit) | Ollama, MLX | 👁 | 🧠 | |
| Gemma 4 E4B | Ollama, MLX | 👁 | 🧠 | |
| Mistral Nemo 12B | Ollama, MLX | | 🧠 | |
| Salamandra 7B | Ollama, llama.cpp | | | iberic |

### tier_24 (24 GB RAM)
| Model | Backends | 👁 | 🧠 | Rec. |
|-------|----------|-----|-----|------|
| Qwen3.5 27B | Ollama, MLX | 👁 | 🧠 | |
| Gemma 4 31B | Ollama, MLX | 👁 | 🧠 | |
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

DeepSeek R1 Distill nomes Ollama/GGUF (MLX no suporta arch qwen2).

### Com instal·lar aquests models

Tant Qwen3.5 family com DeepSeek R1 s'instal·len via **Ollama**. Primer comprova que tens Ollama en marxa (ve bundled amb el DMG o instal·la'l des d'[ollama.com](https://ollama.com)), despres:

```bash
# Qwen3.5 family (multimodal + thinking)
ollama pull qwen3.5:4b          # tier_8, ~3.4 GB
ollama pull qwen3.5:9b          # tier_16, ~6 GB
ollama pull qwen3.5:27b         # tier_24, ~17 GB
ollama pull qwen3.5:35b-a3b     # tier_32 MoE, ~21 GB

# DeepSeek R1 (reasoning)
ollama pull deepseek-r1:32b     # tier_32, ~19 GB
```

Un cop descarregat, configura'l a `server.toml` a l'arrel del repo (el fitxer d'override; els valors per defecte son a `personality/server.toml`):

```toml
[plugins.models]
primary = "qwen3.5:9b"          # o el que hagis triat
preferred_engine = "ollama"     # obligatori per aquests models
```

Reinicia el servidor (`./nexe stop && ./nexe go`, o via el tray) perque agafi el canvi.

### Alternativa GGUF per a DeepSeek R1

Si vols usar DeepSeek R1 sense Ollama, descarrega un fitxer GGUF d'un repositori Hugging Face compatible (p. ex. `unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF`) i col·loca'l a `storage/models/`. Despres configura `preferred_engine = "llama_cpp"`.

Models personalitzats: Ollama (per nom) o Hugging Face (URL de repositori GGUF).

### Carregar un model personalitzat

**Ollama** — qualsevol model del registre públic o privat:
```bash
# 1. Descarrega el model amb Ollama
ollama pull nom-del-model:tag

# 2. Configura server-nexe per usar-lo
# Edita server.toml a l'arrel del repo:
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

Reinicia el servidor per aplicar els canvis: `./nexe stop && ./nexe go`

## Verificacio d'integritat (SHA256)

Des de la remediacio de la revisio interna de seguretat assistida per IA `AUD-INT-001` (§2.7), tots els pesos descarregats durant la instal·lacio es verifiquen amb SHA256 contra un cataleg intern (`installer/installer_catalog_data.py::MODEL_WEIGHT_SHA256`). El check aplica a tres superficies de descarrega:

| Backend | Que es verifica | Com |
|---------|-----------------|-----|
| **Hugging Face MLX** | SHA256 del directori del snapshot local (`local_dir` de `snapshot_download`) | `core.integrity.sha256_of_dir` ignorant dotfiles (`.lock`, `.no_exist`, ...) |
| **GGUF** | SHA256 del fitxer `.gguf` descarregat via `curl` | `core.integrity.sha256_of_file` (stream 64 KB chunks) |
| **Ollama** | Delegat al `pull` content-addressed d'Ollama (sense pin propi del client, ADR B251) | Ollama verifica cada layer contra el digest del manifest durant `ollama pull`; els tags del cataleg son mutables upstream, aixi que un pin client donaria falsos positius en una re-publicacio legitima |
| **fastembed (bundle DMG)** | SHA256 de `model*.onnx`, `tokenizer.json` i `config.json` llegits del manifest `embeddings.manifest.json` generat per `build-embedding-bundle.sh` | `core.integrity.sha256_of_file` via `installer.download_verify.verify_embedding_bundle` |

### Politica en cas de mismatch

Quan el cataleg porta un pin (SHA256 concret) i el valor observat no coincideix, la instal·lacio aborta **hard** amb una excepcio `DownloadIntegrityError`. El fitxer descarregat es **preserva a disc** per a inspeccio post-mortem (l'installer no esborra mai descarregues parcials automaticament). El missatge d'error inclou:

- Hash esperat vs hash observat (complet, 64 chars).
- Ruta del fitxer o directori descarregat.
- Instruccions de reintent especifiques per backend (`ollama rm && ollama pull`, `rm storage/models/<file> && ./nexe model install <name>`, etc.).

### Mode legacy

Les entrades del cataleg amb pin `None` (per exemple models afegits despres d'un DMG ja publicat) **no aborten**. L'installer emet un `WARNING` visible (`⚠️ <model>: SHA256 not pinned in catalog`) i continua. Aixo preserva compatibilitat amb instal·lacions creades amb DMG anteriors a la v1.0.4-beta.

Per a l'embedding bundle, un DMG sense `embeddings.manifest.json` (build anterior al pinning dels pesos) també continua en mode legacy amb un warning a stdout.

### Protecció extra: escapament per symlinks

`verify_embedding_bundle` refusa seguir symlinks que apunten fora del directori del bundle, fins i tot si el hash del fitxer target coincidiria amb el pin. Impedeix que un DMG tampered apunti `model.onnx` a un fitxer extern amb hash conegut.

### Refresc dels hashes

Per a MLX i GGUF, quan un model publica una revisio nova a Hugging Face cal actualitzar els pins amb el nou digest: tier-1 (`MODEL_WEIGHT_SHA256`) es baixant el model i executant `sha256_of_dir` (MLX) o `sha256sum` (GGUF); tier-2 MLX (per-fitxer LFS) es regenera metadata-only amb `installer/bootstrap_catalog_pins.py`. Ollama **no** te pins de client (ADR B251): la seva integritat la garanteix el `pull` content-addressed, aixi que no cal refrescar res. El test `tests/test_installer_sha256_catalog.py` valida que cada artefacte del cataleg te una entrada al dict (encara que sigui `None`).

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

Aplicacio de la barra de menu per controlar el servidor sense terminal. Implementada amb el framework `rumps` a la classe `NexeTray` (`installer/tray.py`, 711 linies). S'arrenca automaticament en mode `--attach` un cop el servidor esta en marxa (llançat per `core/server/runner.py`). El bundle `installer/NexeTray.app` (bash wrapper, `LSUIElement=true`, `CFBundleIdentifier=net.servernexe.tray`) evita les restriccions de provenance de macOS Sequoia.

### Funcions del menu (d'amunt a avall)

| Opcio | Que fa | Codi |
|-------|--------|------|
| **server.nexe v1.0.6** | Capçalera no clicable. La versio es llegeix dinamicament de `pyproject.toml` via `tomllib` (SSOT). | `tray.py:196-206, 272` |
| **Servidor actiu / aturat** | Indicador d'estat (no clicable). La icona de la barra canvia: `ICON_RUNNING` (verda) quan el servidor esta viu, `ICON_STOPPED` (gris) quan no. | `tray.py:223` |
| **Aturar / Iniciar servidor** | Engega o atura el proces `core.app` (uvicorn + FastAPI + Qdrant). Fa SIGTERM i, si cal, SIGKILL. Gestio de PID a `storage/run/server.pid`. | `_toggle_server` → `tray.py:324` |
| **Obrir Web UI** | Obre `http://127.0.0.1:9119/ui` al navegador per defecte. | `_open_web_ui` → `tray.py:564` |
| **Obrir logs** | Obre `storage/logs/server.log` a l'editor associat amb `.log`. | `_open_logs` → `tray.py:567` |
| **Server RAM** | RAM consumida pel proces servidor + model carregat. El polling (`psutil`) es fa a un daemon thread (`RamMonitor`, `installer/tray_monitor.py`, 142 linies) per no bloquejar el menu (fix post-v0.9.0 — abans freezava el teclat). | `tray_monitor.py`; `tray.py:231` |
| **Temps (uptime)** | Temps viu del servidor calculat des de `server_start_time`. | `tray.py:234` |
| **Documentacio** | Obre la documentacio oficial. Item afegit al menu principal per reemplaçar un enllaç duplicat. | `_open_docs` → `tray.py:578` |
| **Configuracio** | Submenu amb 3 opcions: | `tray.py:253-269` |
| ↳ server-nexe.com | Obre la web oficial al navegador. | `_open_website` → `tray.py:575` |
| ↳ Suportar el projecte | Obre GitHub Sponsors. | `_open_donate` → `tray.py:583` |
| ↳ Desinstal·lar Nexe | Llança el desinstal·lador amb doble confirmacio, calcula l'espai, elimina entrades Dock/Login Items, fa backup de `storage/` amb marca de temps. **NO esborra la carpeta del projecte** (opcio de seguretat). | `_uninstall` → `tray.py:586` + `installer/tray_uninstaller.py` (349 linies) |
| **Sortir** | Atura el servidor si esta corrent i tanca l'app del tray. | `_quit` → `tray.py:636` |

### Actualitzacio automatica

Un `rumps.Timer(self._update_stats, 5)` (`tray.py:302`) executa el callback `_update_stats` (`tray.py:513`) cada 5 segons: refresca RAM, uptime, i verifica estat (si el proces ha mort inesperadament → canvia icona i status).

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
| NEXE_LANG | Idioma del servidor | en |
| NEXE_ENV | Entorn | production |
| NEXE_ENCRYPTION_ENABLED | Activar encriptacio at-rest | auto (s'activa si sqlcipher3 disponible) |
| NEXE_OLLAMA_THINK | Default global de thinking tokens per a models Ollama | false |
| NEXE_OLLAMA_EMBED_MODEL | Model d'embeddings Ollama (opcional, fallback) | nomic-embed-text |
