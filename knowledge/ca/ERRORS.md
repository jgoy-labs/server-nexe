# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-errors-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Errors comuns i solucions per a server-nexe 1.0.2-beta. Cobreix errors d'instal·lacio, arrencada del servidor, Web UI, autenticacio API, carrega de models, memoria/RAG, streaming, errors d'encriptacio i fixes de Bug #19 (MEK fallback, personal_memory wipe)."
tags: [errors, troubleshooting, debugging, installation, startup, web-ui, api, models, memory, streaming, encryption]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Errors comuns — server-nexe 1.0.2-beta

## Errors d'instal·lacio

| Error | Causa | Solucio |
|-------|-------|----------|
| Python 3.11+ not found | Python del sistema massa antic | Instal·la Python 3.11+ via Homebrew, o utilitza l'instal·lador DMG (inclou 3.12) |
| Permission denied on setup.sh | Falta permis d'execucio | `chmod +x setup.sh` |
| ModuleNotFoundError | Dependencies no instal·lades | Activa el venv: `source venv/bin/activate`, despres `pip install -r requirements.txt` |
| rumps import error on Linux | Dependencia exclusiva de macOS | Normal a Linux — rumps esta a requirements-macos.txt, no a requirements.txt |

## Errors d'arrencada del servidor

| Error | Causa | Solucio |
|-------|-------|----------|
| Port 9119 already in use | Un altre proces en aquell port | `lsof -i :9119` i matar, o canviar el port a server.toml |
| Qdrant connection refused | Qdrant embedded no s'ha inicialitzat correctament | Reinicia el servidor amb `./nexe go`. Si persisteix, mira els logs a `storage/logs/`. |
| Ollama not available | Ollama no instal·lat o no en execucio | Instal·la des d'ollama.com. El servidor arrencara Ollama automaticament al boot. |
| asyncio.Lock deadlock | Problema de l'event loop de Python 3.12 | Corregit a v0.8.2 via init lazy a module_lifecycle.py. Actualitza a l'ultima versio. |
| Server ja en execució (PID X) | Un altre server actiu | Usa "Quit" al tray, o `pkill -9 server-nexe`. Verifica: `lsof -iTCP:9119` |
| Server orfe (Quit del tray no funciona) | Bug pre-v0.9.0 (corregit) — el tray no enviava SIGTERM al server | Actualitza a v0.9.9. Workaround: `pkill -f "core.app"` o `lsof -iTCP:9119 -sTCP:LISTEN` → `kill -9 <PID>` |

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
| Qwen3.5 falla amb MLX (versions < v0.9.7) | Model multimodal incompatible | Des de v0.9.7 el backend MLX suporta VLM via mlx_vlm. Des de v0.9.8 el detector "any-of" cobreix més arquitectures. Si falla, utilitza el backend Ollama com a alternativa. |

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

## Errors històrics corregits a v0.9.9

### Bug #18 — MEM_DELETE no esborrava fets (P0)

**Símptoma (pre-v0.9.9):** L'usuari deia "oblida que em dic Jordi" i el sistema no esborrava el fet de la memòria. El DELETE_THRESHOLD de `0.70` era massa alt i cap coincidència superava el llindar.

**Fix (v0.9.9):**
- **`DELETE_THRESHOLD` ajustat de `0.70` a `0.20`** (descobert empíricament amb 8 tests e2e reals contra Qdrant embedded + fastembed).
- **`_filter_rag_injection`** neutralitza patrons `[MEM_SAVE:…]`, `[MEM_DELETE:…]`, `[OLVIDA|OBLIT|FORGET:…]`, `[MEMORIA:…]` tant a ingest com a retrieval per evitar que el model auto-esborri per efecte rebot.
- **Confirmació `clear_all` 2-torns:** si l'usuari demana esborrar TOT (no un fet concret), el sistema demana confirmació al torn següent (`session._pending_clear_all`). Evita pèrdues massives accidentals.

### Bug #19a — `personal_memory` es wipeja al reiniciar

**Símptoma (pre-v0.9.9):** Cada reinici del servidor disparava una branca defensiva de "dim-check" que esborrava silenciosament la col·lecció `personal_memory`. Els usuaris perdien la memòria entre sessions.

**Fix (v0.9.9):** Eliminada la branca defensiva. Ara la memòria persisteix entre reinicis sense autorització explícita de l'usuari.

### Bug #19b — sessions `.enc` sobreviuen reset del Keychain

**Símptoma (pre-v0.9.9):** Si l'usuari reiniciava el macOS Keychain (o el perdia), el CryptoProvider no podia recuperar la MEK (Master Encryption Key) i les sessions `.enc` quedaven irrecuperables tot i tenir `~/.nexe/master.key` al disc.

**Fix (v0.9.9):** MEK fallback order corregit a **file → keyring → env → generate**. Si el fitxer local existeix, s'usa primer (abans fallava a keyring directament). Això permet que sessions `.enc` sobrevisquin un reset de Keychain sempre que `~/.nexe/master.key` estigui intacte.

| Error | Causa | Solucio |
|-------|-------|----------|
| Memoria perduda despres de reiniciar (pre-v0.9.9) | Bug #19a | Actualitza a v0.9.9. Sense workaround retroactiu: la memoria ja s'havia perdut. |
| Sessions .enc no desencripten despres de reset Keychain (pre-v0.9.9) | Bug #19b | Actualitza a v0.9.9. Si tens el fitxer `~/.nexe/master.key` o l'entorn `NEXE_MASTER_KEY`, ara es recupera automaticament. |

## Com reportar un error

Si trobes un error no cobert aquí (o que persisteix tot i el workaround), pots reportar-lo. Segueix aquests 3 passos.

### 1. Recollir les evidències des del System Tray

El menú del tray (veure `INSTALLATION.md` — App de safata (NexeTray, macOS)) té un accés directe als logs:

1. Obre el menú del tray (icona `server.nexe` a la barra de menú).
2. Clica **"Obrir logs"** → s'obre `storage/logs/server.log` amb l'editor associat a `.log`.
3. Identifica les línies rellevants — normalment les últimes **50-100 línies** abans del moment de l'error.
4. **Alternativa**: copia el log sencer si vols donar màxim context al triatge.

### 2. ⚠️ Privacitat: revisa el log ABANS d'enviar-lo

**El log pot contenir dades personals teves** perquè captura l'activitat real del servidor:

| Tipus de dada | On pot aparèixer al log |
|---------------|------------------------|
| **Converses** | Fragments de missatges que has enviat al xat (truncats a 200 caràcters per defecte, però encara llegibles) |
| **Resultats RAG** | Trossos de documents que has pujat (`.txt`, `.md`, `.pdf`) |
| **Memòria personal** | Fets emmagatzemats via MEM_SAVE (noms, preferències, projectes) |
| **Paths locals** | `/Users/tu/...` i noms de carpetes del teu equip |
| **Session IDs** | Identificadors d'activitat (útil per correlacionar, però no personal per se) |
| **Stack traces** | Poden incloure camins interns a la teva instal·lació |

**Abans d'enviar**, revisa-ho i:
- Esborra o ofusca noms propis i dades sensibles
- Substitueix paths privats per `[PATH]` o `~/server-nexe/`
- Considera si vols compartir el log sencer o només el fragment rellevant
- **Mai comparteixis** `~/.nexe/master.key` ni el valor de `NEXE_MASTER_KEY` ni `NEXE_PRIMARY_API_KEY`

### 3. Canals de report

| Canal | Millor per a |
|-------|-------------|
| **GitHub Issues** · `github.com/jgoy-labs/server-nexe/issues` | Bugs tècnics, stack traces, regressions, crashes. Requereix compte GitHub |
| **Fòrum** · `server-nexe.com` | Preguntes d'ús, ajuda de la comunitat, discussions de workflow, dubtes sobre config |

### Què incloure al report (GitHub Issue)

- **Versió**: la veuràs al menú del tray com a `server.nexe v1.0.2-beta` (o executa `./nexe --version`)
- **SO + hardware**: `sw_vers` i `uname -m` (M1/M2/M3/M4)
- **Backend actiu**: MLX / llama.cpp / Ollama (el veus a `/ui/backends` o al tray)
- **Model en ús**: nom del model carregat
- **Passos per reproduir**: què estaves fent just abans de l'error
- **Resultat esperat vs obtingut**
- **Log fragment** (ja revisat per privacitat)
- **Captura** si és un error visual (Web UI, tray)

Més context = menys preguntes de seguiment = resolució més ràpida.

