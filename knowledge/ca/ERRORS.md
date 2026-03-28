# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-errors-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Errors comuns i solucions per a server-nexe 0.8.5 pre-release. Cobreix errors d'instal·lacio, arrencada del servidor, Web UI, autenticacio API, carrega de models, memoria/RAG, Docker, streaming i errors d'encriptacio."
tags: [errors, troubleshooting, debugging, installation, startup, web-ui, api, models, memory, docker, streaming, encryption]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Errors comuns — server-nexe 0.8.5 pre-release

## Errors d'instal·lacio

| Error | Causa | Solucio |
|-------|-------|----------|
| Python 3.11+ not found | Python del sistema massa antic | Instal·la Python 3.11+ via Homebrew, o utilitza l'instal·lador DMG (inclou 3.12) |
| Permission denied on setup.sh | Falta permis d'execucio | `chmod +x setup.sh` |
| ModuleNotFoundError | Dependencies no instal·lades | Activa el venv: `source venv/bin/activate`, despres `pip install -r requirements.txt` |
| rumps import error on Linux | Dependencia exclusiva de macOS | Normal a Linux — rumps esta a requirements-macos.txt, no a requirements.txt |
| Qdrant binary not found | No descarregat | Torna a executar l'instal·lador, o descarrega manualment per a la teva plataforma |

## Errors d'arrencada del servidor

| Error | Causa | Solucio |
|-------|-------|----------|
| Port 9119 already in use | Un altre proces en aquell port | `lsof -i :9119` i matar, o canviar el port a server.toml |
| Qdrant connection refused | Qdrant no s'executa o port incorrecte | Comprova el port 6333, reinicia el servidor amb `./nexe go` |
| Ollama not available | Ollama no instal·lat o no en execucio | Instal·la des d'ollama.com. El servidor arrencara Ollama automaticament al boot. |
| asyncio.Lock deadlock | Problema de l'event loop de Python 3.12 | Corregit a v0.8.2 via init lazy a module_lifecycle.py. Actualitza a l'ultima versio. |

## Errors de la Web UI

| Error | Causa | Solucio |
|-------|-------|----------|
| 401 Unauthorized | Clau API incorrecta o absent | Comprova que la clau a localStorage coincideixi amb `NEXE_PRIMARY_API_KEY` al `.env` |
| 403 CSRF | Discordanca de token CSRF | Esborra la cache del navegador i recarrega |
| El xat no respon | Carrega del model (primer missatge) | Espera l'indicador de carrega. Pot trigar 10-60s a la primera carrega. |
| L'streaming s'atura al 2n missatge | Bug _renderTimer (pre-v0.8.2) | Corregit a v0.8.2. Actualitza a l'ultima versio. |
| JS/CSS antic en cache | Cache agressiva del navegador | Corregit amb cache-busting (?v=timestamp). Recarrega forcada: Cmd+Shift+R |
| 429 Too Many Requests | Rate limit excedit | Espera i reintenta. Limits per endpoint (5-30/min per a UI). |

## Errors d'API

| Error | Causa | Solucio |
|-------|-------|----------|
| 401 Missing X-API-Key | Falta capcalera d'autenticacio | Afegeix `-H "X-API-Key: YOUR_KEY"` a la peticio |
| 429 Rate Limited | Massa peticions | Espera i reintenta. Comprova els limits de rate al `.env` |
| 408 Timeout | Inferencia del model massa lenta | Augmenta el timeout de NEXE_DEFAULT_MAX_TOKENS. Models grans necessiten 600s. |
| Missatge d'error buit | httpx.ReadTimeout te str() buit | Corregit amb repr(e). Comprova els logs del servidor. |

## Errors de model

| Error | Causa | Solucio |
|-------|-------|----------|
| OOM Killed | Model massa gran per a la RAM | Utilitza un model mes petit. 8GB RAM -> models 2B maxim. |
| Carrega de model molt lenta | Model gran o GPU freda | Normal per a models 32B+. L'indicador de carrega mostra el progres. |
| MLX not available | Mac Intel o Linux | MLX es nomes Apple Silicon. Utilitza llama.cpp o Ollama. |
| Qwen3.5 falla amb MLX | Model multimodal incompatible | Utilitza el backend Ollama per als models Qwen3.5. |

## Errors de memoria/RAG

| Error | Causa | Solucio |
|-------|-------|----------|
| RAG no retorna res | Memoria buida (inici en fred) | Puja documents, utilitza `nexe knowledge ingest`, o xateja per poblar MEM_SAVE. |
| Resultats RAG incorrectes | Llindar massa alt | Abaixa el llindar via el slider de la UI o les variables d'entorn NEXE_RAG_*_THRESHOLD. |
| Memories duplicades | Problema de llindar de deduplicacio | La deduplicacio comprova similitud > 0.80. Entrades molt similars pero diferents es poden guardar ambdues. |
| Documents no visibles | Sessio incorrecta | Els documents estan aillats per sessio. Puja'ls a la mateixa sessio on estas xatejant. |

## Errors d'encriptacio

| Error | Causa | Solucio |
|-------|-------|----------|
| Keyring not available | OS keyring no configurat (Linux sense Secret Service) | Estableix la variable d'entorn `NEXE_MASTER_KEY` o crea el fitxer `~/.nexe/master.key` (chmod 600) |
| sqlcipher3 not installed | Dependencia no instal·lada | `pip install sqlcipher3`. Fa fallback a SQLite en text pla amb avis. |
| Cannot decrypt data | Clau mestra incorrecta | Assegura't que s'utilitza la mateixa clau. Exporta amb `./nexe encryption export-key`. |
| Migration failed | Base de dades corrupta o migracio interrompuda | El fitxer de backup .bak es conserva. Restaura des del backup i reintenta. |
| Encryption status: disabled | Funcionalitat no activada | Estableix `NEXE_ENCRYPTION_ENABLED=true` al .env o a l'entorn |

## Errors de Docker

| Error | Causa | Solucio |
|-------|-------|----------|
| Qdrant no arrenca | Discordanca d'arquitectura del binari | Docker auto-detecta amd64/arm64. Comprova la plataforma al Dockerfile. |
| No es pot connectar a Ollama | Aillament de xarxa | Ollama s'executa com a servei separat de docker-compose. Comprova el nom del servei a la configuracio. |
| L'emmagatzematge no persisteix | Volum no muntat | Munta `storage/` com a volum Docker. |
