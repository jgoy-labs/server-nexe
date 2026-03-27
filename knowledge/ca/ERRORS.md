# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-errors-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Errors comuns i solucions per a server-nexe 0.8.2. Cobreix errors d'instal·lació, arrencada del servidor, Web UI, autenticació API, càrrega de models, memòria/RAG, Docker i problemes de streaming."
tags: [errors, resolució-problemes, depuració, instal·lació, arrencada, web-ui, api, models, memòria, docker, streaming]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Errors comuns — server-nexe 0.8.2

## Errors d'instal·lació

| Error | Causa | Solució |
|-------|-------|---------|
| Python 3.11+ not found | Python del sistema massa antic | Instal·la Python 3.11+ via Homebrew, o usa l'instal·lador DMG (inclou 3.12) |
| Permission denied on setup.sh | Falta permís d'execució | `chmod +x setup.sh` |
| ModuleNotFoundError | Dependències no instal·lades | Activa el venv: `source venv/bin/activate`, després `pip install -r requirements.txt` |
| rumps import error on Linux | Dependència exclusiva de macOS | Normal a Linux — rumps està a requirements-macos.txt, no a requirements.txt |
| Qdrant binary not found | No descarregat | Torna a executar l'instal·lador, o descarrega manualment per a la teva plataforma |

## Errors d'arrencada del servidor

| Error | Causa | Solució |
|-------|-------|---------|
| Port 9119 already in use | Un altre procés en aquell port | `lsof -i :9119` i mata'l, o canvia el port a server.toml |
| Qdrant connection refused | Qdrant no s'executa o port incorrecte | Comprova el port 6333, reinicia el servidor amb `./nexe go` |
| Ollama not available | Ollama no instal·lat o no en execució | Instal·la des de ollama.com. El servidor iniciarà Ollama automàticament a l'arrencada. |
| asyncio.Lock deadlock | Problema del bucle d'events de Python 3.12 | Corregit a v0.8.2 via inicialització lazy a module_lifecycle.py. Actualitza a la darrera versió. |

## Errors de la Web UI

| Error | Causa | Solució |
|-------|-------|---------|
| 401 Unauthorized | API key incorrecta o absent | Comprova que la clau a localStorage coincideixi amb `NEXE_PRIMARY_API_KEY` al `.env` |
| 403 CSRF | Discordança de token CSRF | Esborra la cache del navegador i recarrega |
| El xat no respon | Càrrega del model (primer missatge) | Espera l'indicador de càrrega. Pot trigar 10-60s a la primera càrrega. |
| L'streaming s'atura al 2n missatge | Bug _renderTimer (pre-v0.8.2) | Corregit a v0.8.2. Actualitza a la darrera versió. |
| JS/CSS antic en cache | Cache agressiva del navegador | Corregit a v0.8.2 amb cache-busting (?v=timestamp). Recàrrega forçada: Cmd+Shift+R |
| La caixa de pensament no fa scroll | Bug d'auto-scroll (pre-v0.8.2) | Corregit a v0.8.2. Actualitza a la darrera versió. |

## Errors d'API

| Error | Causa | Solució |
|-------|-------|---------|
| 401 Missing X-API-Key | Falta capçalera d'autenticació | Afegeix `-H "X-API-Key: YOUR_KEY"` a la petició |
| 429 Rate Limited | Massa peticions | Espera i reintenta. Comprova els límits de rate al `.env` |
| 408 Timeout | Inferència del model massa lenta | Augmenta el timeout de NEXE_DEFAULT_MAX_TOKENS (per defecte 4096). Models grans necessiten 600s. |
| Missatge d'error buit | httpx.ReadTimeout té str() buit | Corregit a v0.8.2 amb repr(e). Comprova els logs del servidor. |

## Errors de model

| Error | Causa | Solució |
|-------|-------|---------|
| OOM Killed | Model massa gran per a la RAM | Usa un model més petit. 8 GB RAM → models 2B com a màxim. |
| Càrrega de model molt lenta | Model gran o GPU freda | Normal per a models 32B+. L'indicador de càrrega mostra el progrés. |
| MLX not available | Mac Intel o Linux | MLX és exclusiu d'Apple Silicon. Usa llama.cpp o Ollama. |
| Qwen3.5 falla amb MLX | Model multimodal incompatible | Usa el backend Ollama per als models Qwen3.5. |

## Errors de memòria/RAG

| Error | Causa | Solució |
|-------|-------|---------|
| El RAG no retorna res | Memòria buida (cold start) | Puja documents, usa `nexe knowledge ingest`, o xateja per omplir MEM_SAVE. |
| Resultats RAG incorrectes | Llindar massa alt | Abaixa el llindar via el slider de la UI o les variables d'entorn NEXE_RAG_*_THRESHOLD. |
| Memòries duplicades | Problema de llindar de deduplicació | La deduplicació comprova similitud > 0.80. Entrades molt similars però diferents es poden desar ambdues. |
| Documents no visibles | Sessió incorrecta | Els documents estan aïllats per sessió. Puja'ls a la mateixa sessió on estàs xatejant. |

## Errors de Docker

| Error | Causa | Solució |
|-------|-------|---------|
| Qdrant no arrenca | Discordança d'arquitectura del binari | Docker auto-detecta amd64/arm64. Comprova la plataforma al Dockerfile. |
| No es pot connectar a Ollama | Aïllament de xarxa | Ollama s'executa com a servei separat de docker-compose. Comprova el nom del servei a la configuració. |
| L'emmagatzematge no persisteix | Volum no muntat | Munta `storage/` com a volum Docker. |
