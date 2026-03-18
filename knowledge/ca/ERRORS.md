# === METADATA RAG ===
versio: "1.0"
data: 2026-03-12
id: nexe-errors

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia d'errors comuns de NEXE 0.8: missatges d'error, causes i solucions. Cobreix errors d'instal·lació, arrencada, Web UI, autenticació, model, memòria i API."
tags: [errors, troubleshooting, solucions, debug, 401, 403, 404, qdrant, mlx, model, web-ui, instal·lació]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# NEXE 0.8 — Errors comuns i solucions

Recull dels errors més habituals que pot trobar un usuari de NEXE, amb les causes probables i les solucions recomanades.

---

## Errors d'instal·lació

### `No s'ha pogut trobar Python 3.11+`
**Causa:** Python no instal·lat o versió massa antiga.
**Solució:** `brew install python@3.12` i torna a executar `./setup.sh`

### `Permission denied: ./setup.sh` o `./nexe`
**Causa:** L'script no té permisos d'execució.
**Solució:** `chmod +x setup.sh nexe`

### `ModuleNotFoundError`
**Causa:** L'entorn virtual no s'ha creat correctament o no s'han instal·lat les dependències.
**Solució:** Torna a executar `./setup.sh` — reinstal·la l'entorn de zero.

### `NameError: name 'DIM' is not defined`
**Causa:** Bug a `installer/installer_setup_env.py` en una versió antiga — la constant ANSI `DIM` no estava importada.
**Solució:** `git pull` per obtenir la versió corregida i torna a executar `./setup.sh`.

### `Python version error` / `requires Python 3.11+`
**Causa:** Python 3.9 o anterior instal·lat al sistema.
**Solució:** `brew install python@3.11` o `brew install python@3.12`.

---

## Errors d'arrencada del servidor

### `Port 9119 already in use`
**Causa:** Ja hi ha una instància de NEXE (o un altre procés) usant el port 9119.
**Solució:**
```bash
./nexe status          # comprova l'estat
lsof -ti:9119 | xargs kill   # força aturada del procés
./nexe go
```

### `Qdrant connection refused`
**Causa:** El servei Qdrant no està en execució.
**Solució:** `./nexe go` l'inicia automàticament si `NEXE_AUTOSTART_QDRANT=true` al `.env`. Si el problema persisteix, atura el servidor amb Ctrl+C o `pkill -f "uvicorn.*nexe"` i torna a executar `./nexe go`.

### `MLX not found` / `No module named 'mlx'`
**Causa:** MLX no instal·lat o el processador no és Apple Silicon.
**Solució:** MLX requereix Apple Silicon (M1/M2/M3/M4). Si tens un Mac Intel o Linux, canvia a `llama_cpp` o `ollama` al `.env`:
```
NEXE_MODEL_ENGINE=llama_cpp
```

### El servidor arrenca però no respon
**Causa:** El model s'està carregant (pot trigar 10–30 s) o hi ha un error silenciós.
**Solució:** Espera fins que el model estigui carregat. Comprova amb:
```bash
curl http://localhost:9119/health
./nexe logs
```

### `OOM killed` / `Killed` (procés mort)
**Causa:** El model és massa gran per la RAM disponible.
**Solució:** Tria un model més petit al `.env`. Referència orientativa:
- 8 GB RAM → Qwen3 1.7B o Qwen3 4B
- 16 GB RAM → Qwen3 8B o Mistral 7B
- 32 GB+ RAM → Qwen3 32B o Llama 3.1 70B

---

## Errors de Web UI

### Pantalla de login apareix però la clau no funciona (`Clau incorrecta`)
**Causa 1:** La clau introduïda és incorrecta.
**Solució:** Troba la clau correcta amb:
```bash
grep NEXE_PRIMARY_API_KEY .env
```
Copia-la exactament, sense espais ni salts de línia.

**Causa 2:** El servidor està corrent una versió antiga (sense el sistema de login).
**Solució:**
```bash
git pull
lsof -ti:9119 | xargs kill
./nexe go
```

### `GET /ui/auth 404 Not Found` als logs
**Causa:** El servidor no té l'endpoint `/ui/auth` — versió antiga del codi.
**Solució:** `git pull` i reinicia el servidor.

### `POST /ui/chat 403 Forbidden` als logs
**Causa:** Error CSRF — la cookie de sessió no coincideix o és de versió anterior.
**Solució:** Obre la Web UI en mode incògnit o esborra les cookies per `localhost:9119`. Amb la versió actual (login amb API key) aquest error ja no hauria d'aparèixer.

### La Web UI carrega però el xat no respon
**Causa:** El model encara s'està carregant, o Qdrant no està actiu.
**Solució:** Espera 10–30 s i comprova:
```bash
curl http://localhost:9119/health
```

---

## Errors d'autenticació API

### `401 Unauthorized` a les peticions API
**Causa:** La API key no s'ha enviat o és incorrecta.
**Solució:** Afegeix la capçalera correcta:
```bash
curl -H "X-API-Key: $(grep NEXE_PRIMARY_API_KEY .env | cut -d= -f2)" \
  http://localhost:9119/v1/chat/completions
```

### `403 Forbidden` a les peticions API
**Causa habitual:** Error CSRF (sessions web antigues) o intent d'accés des d'un origen no permès.
**Solució:** Per a l'API REST (`/v1/`), no s'usa CSRF — comprova que estàs usant `X-API-Key` correctament.

### La clau API ha expirat
**Causa:** `NEXE_PRIMARY_KEY_EXPIRES` al `.env` és una data passada.
**Solució:** Genera una nova clau i actualitza el `.env`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Actualitza `NEXE_PRIMARY_API_KEY` al `.env` i reinicia.

---

## Errors de model

### `Model download very slow` / descàrrega molt lenta
**Causa:** Connexió lenta o model molt gran (models 7B+ ocupen 4–20 GB).
**Solució:** Espera o tria un model més petit. La descàrrega es pot reprendre si s'interromp.

### El model respon molt lentament
**Causa:** Model massa gran per la RAM/GPU disponibles, o context molt llarg.
**Solució:** Considera un model més petit. En Apple Silicon M1 de 8 GB, Qwen3 4B és el màxim recomanat.

### `ValueError: Unsupported model architecture`
**Causa:** El model GGUF o MLX no és compatible amb la versió actual de llama.cpp o mlx-lm.
**Solució:** Actualitza les dependències: `pip install --upgrade mlx-lm llama-cpp-python`

---

## Errors de memòria / RAG

### `Qdrant collection not found`
**Causa:** Les col·leccions de Qdrant no s'han inicialitzat.
**Solució:** Reinicia el servidor — s'inicialitzen automàticament a l'arrencada.

### La memòria no recorda informació guardada
**Causa:** La informació es va guardar en una sessió diferent, o Qdrant va reiniciar i va perdre l'índex.
**Solució:** Comprova l'estat de la memòria:
```bash
./nexe memory stats
./nexe memory recall "paraula clau de la info guardada"
```

### `Embedding model not loaded`
**Causa:** El model d'embeddings (`paraphrase-multilingual-mpnet-base-v2`) no s'ha descarregat.
**Solució:** Durant el `./setup.sh` hauries d'haver confirmat la descàrrega. Si no:
```bash
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')"
```

---

## Errors generals

### `NEXE_CSRF_SECRET not configured in production mode`
**Causa:** El fitxer `.env` no té `NEXE_CSRF_SECRET` i el servidor corre en mode producció.
**Solució:** Afegeix al `.env`:
```bash
echo "NEXE_CSRF_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
```

### El servidor no arrenca després d'un `git pull`
**Causa:** Canvis incompatibles en la configuració o dependències noves.
**Solució:**
```bash
./setup.sh   # actualitza dependències
./nexe go
```

### Els canvis al codi no es reflecteixen al servidor
**Causa:** El servidor corrent usa el codi antic (no s'ha reiniciat).
**Solució:** Mata el procés i reinicia:
```bash
lsof -ti:9119 | xargs kill
./nexe go
```
