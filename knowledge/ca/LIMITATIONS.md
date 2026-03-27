# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-limitations

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentació honesta de les limitacions de server-nexe 0.8.2. Cobreix suport de plataformes (macOS testat, Linux parcial, Windows no suportat), qualitat de models vs cloud (GPT-4/Claude), limitacions del RAG (embeddings, chunking, cold start, contradiccions), compatibilitat parcial API OpenAI, rendiment (instància única, concurrència), restriccions de seguretat i mancances funcionals (sense multi-usuari, sense sync, sense fine-tuning)."
tags: [limitacions, plataforma, models, rag, rendiment, seguretat, api, compatibilitat, honest]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Limitacions — server-nexe 0.8.2

Aquest document descriu honestament el que server-nexe no pot fer o no fa bé.

## Plataforma

| Plataforma | Estat |
|------------|-------|
| macOS Apple Silicon | Testat, els 3 backends |
| macOS Intel | Testat, llama.cpp + Ollama (sense MLX) |
| Linux x86_64 | Parcial — tests unitaris passen (3901/3901), CI verd, no testat en producció |
| Linux ARM64 | Suport Docker, no testat directament |
| Windows | No suportat |

## Qualitat dels models

Els models locals són menys capaços que els models al núvol (GPT-4, Claude, etc.). Aquesta és la contrapartida de la privacitat.

- **Models petits (2-4B):** Bons per a tasques simples, respostes curtes. Raonament limitat.
- **Models mitjans (7-8B):** Adequats per a la majoria de tasques quotidianes. Al·lucinacions ocasionals.
- **Models grans (32B+):** Bona qualitat, però requereixen 32+ GB de RAM i càrrega lenta.
- **Català:** Els models Salamandra (BSC/AINA) són els millors per al català. Altres models tenen suport limitat de català.

## Limitacions del RAG

- **Homonímia:** "banc" (seient) vs "banc" (finances) obtenen embeddings similars. Mateixa paraula, significats diferents.
- **Negacions:** "No m'agrada Python" obtén embedding similar a "M'agrada Python".
- **Cold start:** Memòria buida = el RAG no aporta res. Cal omplir-la primer.
- **Misses de Top-K:** Si tens moltes dades, la informació rellevant pot no estar als Top-3/5 resultats.
- **Informació contradictòria:** El RAG pot recuperar fets contradictoris de períodes de temps diferents.
- **Límits de chunks:** La informació partida entre límits de chunks pot ser recuperada parcialment.
- **Model d'embeddings:** Vectors de 768 dimensions capturen el significat bé però no perfectament. Vocabulari de dominis especialitzats pot tenir menor precisió.

## Compatibilitat API

Parcialment compatible amb el format de l'API d'OpenAI:

| Funcionalitat | Estat |
|---------------|-------|
| /v1/chat/completions | Funcional (messages, temperature, max_tokens, stream) |
| /v1/embeddings (estàndard) | No implementat (usa /v1/embeddings/encode en comptes) |
| /v1/models | No implementat |
| /v1/completions (legacy) | No implementat |
| /v1/fine-tuning | No implementat |
| Function calling | No implementat |
| Visió/multimodal | No implementat |

## Rendiment

- **Instància única:** Un sol procés de servidor, no clusteritzat.
- **Concurrència:** Limitada per la inferència del model (una petició a la vegada per backend).
- **Temps d'arrencada:** 5-15 segons (Qdrant + càrrega de mòduls + ingestió de coneixement a la primera execució).
- **Càrrega de model:** 10-60 segons segons la mida del model i el backend.
- **Consum de RAM:** Model + Qdrant + Python = significatiu. 8 GB de RAM és just per a models 7B.
- **Disc:** Models (1-40 GB) + vectors Qdrant + logs. Estimació 10-50 GB total.

## Seguretat

- **Injecció de prompt:** Els models locals poden seguir instruccions injectades. El sanititzador detecta patrons comuns (69 patrons de jailbreak) però no tots.
- **Sense TLS per defecte:** HTTP a localhost. Usa un reverse proxy per HTTPS.
- **Mono-usuari:** Sense aïllament multi-usuari. Una API key = accés complet.
- **Qdrant sense encriptar:** Vectors al disc en text pla. Usa encriptació de disc.
- **Bug keep_alive d'Ollama:** keep_alive:0 no sempre allibera VRAM (problema conegut d'Ollama).

## Mancances funcionals

- **Sense sync multi-dispositiu** — Només local, sense sync al núvol.
- **Sense fine-tuning de models** — No es poden entrenar ni ajustar models.
- **Sense OCR** — No es pot extreure text d'imatges o PDFs escanejats.
- **Sense multi-usuari** — Una sola API key, sense comptes d'usuari.
- **Sense col·laboració en temps real** — Disseny mono-usuari, sessió única.
- **Sense tasques programades** — Sense automatització tipus cron integrada.
- **La Web UI és funcional però bàsica** — No és una app de xat completa. Streaming, pujades, memòria, i18n funcionen, però sense edició de missatges, sense branching, sense exportació.

## Què NO és server-nexe

- NO és un reemplaçament de ChatGPT, Claude ni serveis d'IA al núvol
- NO és un producte enterprise amb SLA
- NO és una plataforma multi-usuari
- NO té garantia d'absència de bugs (és un projecte personal de codi obert)
- NO és npm nexe (compilador Node.js — completament no relacionat)
