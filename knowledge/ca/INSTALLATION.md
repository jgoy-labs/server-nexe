# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-installation-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Com instal-lar server-nexe: 2 metodes. (1) DMG per macOS amb wizard SwiftUI, Python 3.12 inclos, models per tiers de RAM. (2) CLI: git clone + ./setup.sh (macOS/Linux). Requisits: macOS 13+ o Linux, 8GB RAM minim. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Port per defecte: 9119."
tags: [installation, setup, dmg, swiftui, wizard, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy"
expires: null
---

# Instal·lacio — server-nexe 0.9.7

Dos metodes d'instal·lacio disponibles. Tria segons la teva plataforma i preferencies.

## Requisits del sistema

| Requisit | Minim | Recomanat |
|------------|---------|-------------|
| SO | macOS 12+ / Linux x86_64 | macOS 14+ (Apple Silicon) |
| RAM | 8 GB | 16+ GB |
| Disc | 10 GB lliures | 20+ GB (per a models grans) |
| Python | 3.11+ (metode CLI) | 3.12 inclos (metode DMG) |

## Metode 1: Instal·lador DMG per a macOS (recomanat)

Wizard natiu SwiftUI amb 6 pantalles. Inclou Python 3.12 — sense dependencia del Python del sistema.

### ⚡ Instal·lacio 100% offline (des de 2026-04-16)

A partir d'aquesta versio, el DMG porta **tot** el que l'installer necessita:

- Runtime Python 3.12 (~45 MB)
- **Tots els wheels de Python** pre-compilats per a arm64 macOS 13+ (~220 MB): fastapi, pydantic, mlx-lm, mlx-vlm, llama-cpp-python (amb Metal), fastembed, onnxruntime, sqlcipher3, cryptography, i la resta del stack.
- **Model d'embeddings multilingue** pre-descarregat (~470 MB): `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` en format ONNX.

Efectes practics:

- Mida del DMG: **~700 MB** (abans ~20 MB).
- Un cop baixat el DMG, l'instal·lacio **no requereix xarxa** i no necessita Xcode Command Line Tools.
- **Cap prompt de macOS demanant "eines de desenvolupador"** durant l'install.
- RAG funcional al primer boot: el model d'embeddings ja esta present.
- L'unica cosa que segueix requerint xarxa post-install es la descarrega del model LLM que trieu (Qwen, Gemma, DeepSeek, etc.), si no useu un model ja present a Ollama local.

Requisit: **Apple Silicon (M1+) amb macOS 13 Ventura o superior**. Intel Mac ja no son un target suportat.

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
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
```

`setup.sh` detecta la teva plataforma:
- **macOS:** Comprova Homebrew, Python 3.11+, crea venv, instal·la requirements.txt + requirements-macos.txt (rumps per a la safata)
- **Linux:** Suggereix paquets apt/dnf, crea venv, instal·la nomes requirements.txt

Despres de la configuracio:
```bash
./nexe go    # Arrencar servidor -> http://127.0.0.1:9119
```

## Cataleg de models

### tier_8 (8 GB RAM)
| Model | Motor | Any |
|-------|--------|------|
| Qwen3.5 9B | Tots | 2025 |
| Gemma 4 E4B | Tots | 2025 |
| Salamandra 2B | Tots | 2024 |

### tier_16 (16 GB RAM)
| Model | Motor | Any |
|-------|--------|------|
| Llama 4 Scout (109B/17B actius MoE) | Tots | 2025 |
| Salamandra 7B | Tots | 2024 |

### tier_24 (24 GB RAM)
| Model | Motor | Any |
|-------|--------|------|
| Qwen3.5 27B | Tots | 2025 |
| Gemma 4 31B | Tots | 2025 |

### tier_32 (32 GB RAM)
| Model | Motor | Any |
|-------|--------|------|
| Qwen3.5 35B-A3B (MoE) | Tots | 2025 |
| DeepSeek R1 Distill 32B | Tots | 2025 |
| ALIA-40B Instruct | Tots | 2025 |

### tier_48 (48 GB RAM)
| Model | Motor | Any |
|-------|--------|------|
| Qwen3.5 122B-A10B (MoE) | Tots | 2025 |
| Llama 4 Maverick (400B/17B actius MoE) | Tots | 2025 |

### tier_64 (64 GB RAM)
| Model | Motor | Any |
|-------|--------|------|
| Qwen3.5 122B-A10B | Tots | 2025 |
| GPT-OSS 120B | Tots | 2025 |

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

## App de safata (macOS)

Aplicacio de safata del sistema amb: arrencada/aturada del servidor, indicador d'estat (pulsant durant l'arrencada), mode clar/fosc (automatic per hora + commutacio manual), accessos rapids a la Web UI, acces al desinstal·lador, menu multilingue (ca/es/en), Ollama s'obre en segon pla.

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
