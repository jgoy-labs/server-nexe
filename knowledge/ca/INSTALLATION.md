# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-installation-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia d'instal·lacio per a server-nexe 0.9.0 pre-release. Tres metodes: DMG per a macOS amb wizard SwiftUI (6 pantalles, deteccio de maquinari, 15 models, Python 3.12 inclos), CLI headless (setup.sh amb suport Linux) i Docker (docker-compose amb Ollama). Cobreix requisits del sistema, seleccio de backend, cataleg de models per nivell de RAM, verificacio post-instal·lacio, app de safata, desinstal·lador, encriptacio opt-in i resolucio de problemes."
tags: [installation, setup, dmg, swiftui, wizard, docker, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Instal·lacio — server-nexe 0.9.0 pre-release

Tres metodes d'instal·lacio disponibles. Tria segons la teva plataforma i preferencies.

## Requisits del sistema

| Requisit | Minim | Recomanat |
|------------|---------|-------------|
| SO | macOS 12+ / Linux x86_64 | macOS 14+ (Apple Silicon) |
| RAM | 8 GB | 16+ GB |
| Disc | 10 GB lliures | 20+ GB (per a models grans) |
| Python | 3.11+ (metode CLI) | 3.12 inclos (metode DMG) |

## Metode 1: Instal·lador DMG per a macOS (recomanat)

Wizard natiu SwiftUI amb 6 pantalles. Inclou Python 3.12 — sense dependencia del Python del sistema.

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

## Metode 3: Docker

Per a servidors Linux o desplegaments en contenidors.

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
docker-compose up
```

- **Dockerfile:** Python 3.12-slim, binari Qdrant embegut (auto-deteccio linux-amd64/arm64), usuari no-root (`nexe`), EXPOSE 9119 6333
- **docker-compose.yml:** Dos serveis — Nexe + Ollama
- **docker-entrypoint.sh:** Arrencada sequencial (Qdrant -> esperar health -> Nexe), timeout de 15s amb avis

Munta `storage/` per a dades persistents (models, vectors Qdrant, logs).

## Cataleg de models (15 models)

### Petits (8 GB RAM)
| Model | Mida | Motor | Any |
|-------|------|--------|------|
| Qwen3 1.7B | 1.1 GB | Tots | 2025 |
| Qwen3.5 2B | 1.5 GB | Nomes Ollama | 2025 |
| Phi-3.5 Mini | 2.4 GB | Tots | 2024 |
| Salamandra 2B | 1.5 GB | Tots | 2024 |
| Qwen3 4B | 2.5 GB | Tots | 2025 |

### Mitjans (12-16 GB RAM)
| Model | Mida | Motor | Any |
|-------|------|--------|------|
| Mistral 7B | 4.1 GB | Tots | 2023 |
| Salamandra 7B | 4.9 GB | Tots | 2024 |
| Llama 3.1 8B | 4.7 GB | Tots | 2024 |
| Qwen3 8B | 5.0 GB | Tots | 2025 |
| Gemma 3 12B | 7.6 GB | Tots | 2025 |

### Grans (32+ GB RAM)
| Model | Mida | Motor | Any |
|-------|------|--------|------|
| Qwen3.5 27B | 17 GB | Nomes Ollama | 2025 |
| Qwen3 32B | 20 GB | Tots | 2025 |
| Gemma 3 27B | 17 GB | Tots | 2025 |
| DeepSeek R1 32B | 20 GB | Tots | 2025 |
| Llama 3.1 70B | 40 GB | Tots | 2024 |

Models personalitzats: Ollama (per nom) o Hugging Face (URL de repositori GGUF).

## Verificacio post-instal·lacio

```bash
curl http://127.0.0.1:9119/health    # Health check
./nexe modules                        # Llistar moduls carregats
./nexe chat                           # Provar xat
open http://127.0.0.1:9119/ui        # Web UI
```

## Encriptacio at-rest (opt-in)

Despres de la instal·lacio, pots activar l'encriptacio at-rest:

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
| Qdrant no arrenca | Comprova el port 6333, comprova els permisos del binari |
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
| NEXE_ENCRYPTION_ENABLED | Activar encriptacio at-rest | false |
