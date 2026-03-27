# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-installation-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia d'instal·lació de server-nexe 0.8.2. Tres mètodes: DMG macOS amb wizard SwiftUI (6 pantalles, detecció de hardware, 17 models, Python 3.12 inclòs), CLI headless (setup.sh amb suport Linux) i Docker (docker-compose amb Ollama). Cobreix requisits del sistema, selecció de backend (MLX/llama.cpp/Ollama), catàleg de models per nivell de RAM, verificació post-instal·lació, tray app, desinstal·lador i resolució de problemes."
tags: [instal·lació, setup, dmg, swiftui, wizard, docker, cli, headless, macos, linux, requisits, models, backends, mlx, ollama, llama-cpp, tray, desinstal·lador]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Instal·lació — server-nexe 0.8.2

Tres mètodes d'instal·lació disponibles. Tria segons la teva plataforma i preferències.

## Requisits del sistema

| Requisit | Mínim | Recomanat |
|----------|-------|-----------|
| SO | macOS 12+ / Linux x86_64 | macOS 14+ (Apple Silicon) |
| RAM | 8 GB | 16+ GB |
| Disc | 10 GB lliures | 20+ GB (per a models més grans) |
| Python | 3.11+ (mètode CLI) | 3.12 inclòs (mètode DMG) |

## Mètode 1: Instal·lador DMG macOS (Recomanat)

Wizard natiu SwiftUI amb 6 pantalles. Inclou Python 3.12 — sense dependència del Python del sistema.

### Què fa el wizard

1. **Benvinguda:** Selector d'idioma (ca/es/en), logo, informació de versió
2. **Destinació:** Selector de carpeta amb validació d'espai lliure
3. **Selecció de model:** 4 pestanyes (petit/mitjà/gran/personalitzat) amb detecció de hardware. Mostra 17 models amb requisits de RAM, compatibilitat de motor i any. Recomana models segons la RAM/GPU detectades.
4. **Confirmació:** Resum de les opcions abans d'instal·lar
5. **Progrés:** Barra de progrés de 7 passos amb log en temps real. Parser de protocol Python ([PROGRESS], [LOG], [DONE], [ERROR]). 8-30 minuts segons la descàrrega del model.
6. **Finalització:** Mostra la API key, opcions per afegir al Dock i als Login Items, compte enrere per llançar

### Detecció de hardware

El wizard usa crides natives `sysctl` per detectar:
- Xip CPU (M1/M2/M3/M4, Intel)
- RAM total
- Suport GPU Metal
- Espai lliure en disc

Segons la detecció, recomana el backend i models adequats.

### Selecció de backend

| Backend | Plataforma | Millor per a |
|---------|------------|--------------|
| MLX | Només Apple Silicon | Més ràpid en M-series, GPU Metal + Neural Engine |
| llama.cpp | macOS + Linux | Format GGUF universal, acceleració Metal a Mac |
| Ollama | macOS + Linux | Si ja tens Ollama instal·lat, configuració més fàcil |

### Descàrrega

Descarrega el DMG des de la pàgina de releases de GitHub: https://github.com/jgoy-labs/server-nexe/releases

## Mètode 2: CLI Headless

Per a usuaris que prefereixen instal·lació per terminal o estan a Linux.

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
```

`setup.sh` detecta la teva plataforma:
- **macOS:** Comprova Homebrew, Python 3.11+, crea venv, instal·la requirements.txt + requirements-macos.txt (rumps per al tray)
- **Linux:** Suggereix paquets apt/dnf, crea venv, instal·la només requirements.txt

Després del setup:
```bash
./nexe go    # Inicia el servidor → http://127.0.0.1:9119
```

## Mètode 3: Docker

Per a servidors Linux o desplegaments containeritzats.

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
docker-compose up
```

- **Dockerfile:** Python 3.12-slim, binari Qdrant incrustat (auto-detecta linux-amd64/arm64), usuari no-root (`nexe`), EXPOSE 9119 6333
- **docker-compose.yml:** Dos serveis — Nexe + Ollama
- **docker-entrypoint.sh:** Arrencada seqüencial (Qdrant → esperar health → Nexe), timeout de 15s amb avís

Munta `storage/` per a dades persistents (models, vectors Qdrant, logs).

## Catàleg de models (17 models)

### Petits (8 GB RAM)
| Model | Mida | Motor | Any |
|-------|------|-------|-----|
| Qwen3 1.7B | 1.1 GB | Tots | 2025 |
| Qwen3.5 2B | 1.5 GB | Només Ollama | 2025 |
| Phi-3.5 Mini | 2.4 GB | Tots | 2024 |
| Salamandra 2B | 1.5 GB | Tots | 2024 |
| Qwen3 4B | 2.5 GB | Tots | 2025 |

### Mitjans (12-16 GB RAM)
| Model | Mida | Motor | Any |
|-------|------|-------|-----|
| Mistral 7B | 4.1 GB | Tots | 2023 |
| Salamandra 7B | 4.9 GB | Tots | 2024 |
| Llama 3.1 8B | 4.7 GB | Tots | 2024 |
| Qwen3 8B | 5.0 GB | Tots | 2025 |
| Gemma 3 12B | 7.6 GB | Tots | 2025 |

### Grans (32+ GB RAM)
| Model | Mida | Motor | Any |
|-------|------|-------|-----|
| Qwen3.5 27B | 17 GB | Només Ollama | 2025 |
| Qwen3 32B | 20 GB | Tots | 2025 |
| Gemma 3 27B | 17 GB | Tots | 2025 |
| DeepSeek R1 32B | 20 GB | Tots | 2025 |
| Llama 3.1 70B | 40 GB | Tots | 2024 |

Models personalitzats: Ollama (per nom) o Hugging Face (URL de repositori GGUF).

## Verificació post-instal·lació

```bash
curl http://127.0.0.1:9119/health    # Health check
./nexe modules                        # Llista mòduls carregats
./nexe chat                           # Test de xat
open http://127.0.0.1:9119/ui        # Web UI
```

## Tray App (macOS)

App a la barra del sistema amb: inici/parada del servidor, indicador d'estat (polsant durant l'arrencada), mode fosc/clar (automàtic per hora + canvi manual), enllaços ràpids a la Web UI, accés al desinstal·lador, menú multilingüe (ca/es/en), Ollama s'obre en segon pla.

## Desinstal·lador

Accessible des del menú del tray. Doble confirmació, calcula espai, elimina Dock/Login Items, backup de storage/ amb timestamp, NO esborra la carpeta.

## Resolució de problemes

| Problema | Solució |
|----------|---------|
| Port 9119 en ús | `lsof -i :9119` i mata el procés, o canvia a server.toml |
| Qdrant no arrenca | Comprova el port 6333, comprova permisos del binari |
| Ollama no trobat | Instal·la des de ollama.com, o usa MLX/llama.cpp |
| Error de versió Python | Requereix 3.11+. El DMG inclou 3.12. |
| MLX no disponible | Només Apple Silicon. Usa llama.cpp o Ollama. |
| Descàrrega de model lenta | Models grans triguen 30+ min. Timeout 600s. |
| OOM killed | Tria un model més petit. 8GB → models 2B. |

## Variables d'entorn clau

| Variable | Propòsit | Per defecte |
|----------|----------|-------------|
| NEXE_PRIMARY_API_KEY | API key principal | (generada) |
| NEXE_MODEL_ENGINE | Backend per defecte | auto |
| NEXE_OLLAMA_MODEL | Model Ollama | (seleccionat durant la instal·lació) |
| NEXE_LLAMA_CPP_MODEL | Ruta del model GGUF | storage/models/*.gguf |
| NEXE_DEFAULT_MAX_TOKENS | Tokens màxims de resposta | 4096 |
| NEXE_LANG | Idioma del servidor | ca |
| NEXE_ENV | Entorn | production |
