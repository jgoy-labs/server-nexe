# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-limitations
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentacio honesta de les limitacions de server-nexe 1.0.0-beta. Cobreix suport de plataformes (macOS 14+ Apple Silicon only, Linux parcial, Intel i Windows NO suportats), qualitat de models vs nuvol (GPT-4/Claude), limitacions del RAG (embeddings, chunking, inici en fred, contradiccions), compatibilitat parcial amb l'API d'OpenAI, rendiment (instancia unica, concurrencia), restriccions de seguretat, advertencies d'encriptacio (default auto, nova, no provada en batalla) i mancances funcionals (sense multi-usuari, sense sync, sense fine-tuning)."
tags: [limitations, platform, models, rag, performance, security, api, compatibility, honest, encryption]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Limitacions — server-nexe 1.0.0-beta

Aquest document descriu honestament el que server-nexe no pot fer o no fa be.

## Plataforma

| Plataforma | Estat |
|----------|--------|
| macOS 14 Sonoma+ Apple Silicon (M1+) | **Target principal** — testejat, tots 3 backends |
| macOS 13 Ventura | **NO suportat** (eliminat a v0.9.9 per dependencies arm64-only del stack) |
| macOS Intel | **NO suportat** (eliminat a v0.9.9 — wheels arm64-only, sense MLX) |
| Linux x86_64 | Parcial — tests unitaris passen, CI verd, no testejat en produccio |
| Linux ARM64 | No testejat directament |
| Windows | No suportat |

## Qualitat dels models

Els models locals son menys capacos que els models al nuvol (GPT-4, Claude, etc.). Aquesta es la contrapartida de la privacitat.

- **Models petits (2-4B):** Bons per a tasques simples, respostes curtes. Raonament limitat.
- **Models mitjans (7-8B):** Adequats per a la majoria de tasques quotidianes. Al·lucinacions ocasionals.
- **Models grans (32B+):** Bona qualitat, pero requereixen 32+ GB de RAM i carrega lenta.
- **Catala:** Els models Salamandra (BSC/AINA) son els millors per al catala. Altres models tenen suport limitat de catala.

## Models multimodal (VLM)

El backend MLX suporta models de visio (imatge + text) a traves de `mlx-vlm 0.4.4`. Llista d'arquitectures detectades: Qwen2-VL, Qwen2.5-VL, Qwen3-VL, Llava (tots), Gemma-3/4, PaliGemma, InternVL, MiniCPMV, Idefics2/3, Mllama i mes. Des de **v0.9.8** el detector "any-of" de 3 senyals (architectures + vision_config al `config.json` + weight_map al `model.safetensors.index.json`) cobreix arquitectures noves sense keys clàssiques.

Limitacions actuals:
- **Familia Qwen3.5 i omni-models (Qwen3.5 2B/4B/9B/27B/35B/122B, Qwen3-Omni, Kimi-VL, …):** Requereixen `PyTorch` i `torchvision` per al seu `VideoProcessor`, que server-nexe **no inclou** al venv per mida (afegirien ~2 GB al DMG). Es carregaran via `mlx-vlm.load()` pero fallaran a la fase de preparacio del processor. **Via Ollama funcionen perfectament** sense cap dependencia addicional. **Opcional:** si vols usar-los via MLX, instal·la manualment: `pip install torch torchvision` al venv de server-nexe — afegira ~2 GB pero desbloqueara Qwen3.5 MLX amb prefix caching i visio. **Workaround sense instal·lar res:** usar Ollama per Qwen3.5 (automàtic si MLX falla) o un VLM imatge-only com Gemma-4.
- **Model per defecte recomanat:** `gemma-4-e4b-4bit` (4.9 GB) o `gemma-4-31b-8bit` (20 GB). Imatge only, sense dependencies torch.
- **Audio/veu:** No suportat. Models com Qwen3-Omni, Kimi-VL o DeepSeek-VL-V2 tenen branch d'audio a `mlx-vlm` pero el pipeline de server-nexe encara no el exposa.
- **Video nativament:** No suportat (veure omni-models).

## Limitacions del RAG

- **Homonims:** "bank" (seient) vs "bank" (finances) obtenen embeddings similars. Mateixa paraula, significats diferents.
- **Negacions:** "No m'agrada Python" ~ "M'agrada Python" a l'espai d'embeddings.
- **Inici en fred:** Memoria buida = RAG no contribueix res. Cal poblar-la primer.
- **Falles Top-K:** Si tens moltes dades, la informacio rellevant pot no estar als resultats Top-3/5.
- **Informacio contradictoria:** RAG pot recuperar fets conflictius de periodes de temps diferents.
- **Limits de chunks:** La informacio partida entre limits de chunks pot ser recuperada parcialment.
- **Model d'embeddings:** Vectors de 768 dimensions capturen el significat be pero no perfectament. El vocabulari de dominis especialitzats pot tenir menor precisio.

## Compatibilitat amb l'API

Parcialment compatible amb el format de l'API d'OpenAI:

| Funcionalitat | Estat |
|---------|--------|
| /v1/chat/completions | Funcional (messages, temperature, max_tokens, stream) |
| /v1/embeddings (estandard) | No implementat (utilitza /v1/embeddings/encode en el seu lloc) |
| /v1/models | No implementat |
| /v1/completions (legacy) | No implementat |
| /v1/fine-tuning | No implementat |
| Function calling | No implementat |
| Visio/multimodal | Implementat des de v0.9.7 (Ollama, MLX, llama.cpp, Web UI) |

## Rendiment

- **Instancia unica:** Un sol proces de servidor, no clusteritzat.
- **Concurrencia:** Limitada per la inferencia del model (una peticio a la vegada per backend).
- **Temps d'arrencada:** 5-15 segons (Qdrant + carrega de moduls + ingestio de coneixement a la primera execucio).
- **Carrega de model:** 10-60 segons depenent de la mida del model i el backend.
- **Consum de RAM:** Model + Qdrant + Python = significatiu. 8GB de RAM es just per a models 7B.
- **Disc:** Models (1-40 GB) + vectors Qdrant + logs. Estimacio 10-50 GB total.

## Seguretat

- **Injeccio de prompt:** Els models locals poden seguir instruccions injectades. El sanitizer detecta patrons comuns (47 patrons de jailbreak, 6 detectors d'injeccio amb normalitzacio Unicode) pero no tots.
- **Sense TLS per defecte:** HTTP a localhost. Utilitza un reverse proxy per a HTTPS.
- **Un sol usuari:** Sense aillament multi-usuari. Una clau API = acces complet.
- **Auditories IA, no auditories externes:** La seguretat ha estat revisada per sessions autonomes d'IA, no per empreses de seguretat externes. Aixo es exhaustiu pero no complet.
- **Bug keep_alive d'Ollama:** keep_alive:0 no sempre allibera VRAM (problema conegut d'Ollama).

## Advertencies d'encriptacio

- **Default `auto`:** L'encriptacio at-rest s'activa automaticament si `sqlcipher3` es disponible (mode `auto`). Es pot forcar amb `NEXE_ENCRYPTION_ENABLED=true` o desactivar amb `false`.
- **Funcionalitat nova:** Afegida a la v0.9.0, disponible des de 0.9.7. Testejada (68 tests, 0 errors) pero encara no provada en batalla en produccio amb usuaris reals.
- **Gestio de claus:** La clau mestra s'emmagatzema a l'OS Keyring, variable d'entorn o fitxer. Si la clau es perd, les dades encriptades no es poden recuperar.
- **Dependencia de SQLCipher:** Requereix el paquet `sqlcipher3`. Fa fallback a SQLite en text pla amb un avis si no esta instal·lat.
- **Migracio:** Migrar conjunts de dades grans (moltes memories, moltes sessions) pot trigar. Fes copia de seguretat abans de migrar.

## Mancances funcionals

- **Sense sincronitzacio multi-dispositiu** — Nomes local, sense sync al nuvol.
- **Sense fine-tuning de models** — No es poden entrenar ni ajustar models.
- **Sense OCR** — No es pot extreure text d'imatges ni de PDFs escanejats.
- **Sense multi-usuari** — Una sola clau API, sense comptes d'usuari.
- **Sense col·laboracio en temps real** — Disseny d'un sol usuari, sessio unica.
- **Sense tasques programades** — Sense automatitzacio tipus cron integrada.
- **La Web UI es funcional pero basica** — No es una app de xat completa. Streaming, pujades, memoria, i18n funcionen, pero sense edicio de missatges, sense branching, sense exportacio.

## Realitat del projecte

- **Un sol desenvolupador** — Construit per una sola persona amb desenvolupament i auditories assistides per IA.
- **Un sol usuari real** — Nomes el desenvolupador l'ha usat fins ara. Sense feedback de tercers ni testing multi-usuari.
- **No es de nivell enterprise** — Es un projecte personal de codi obert, no un producte amb SLA ni garanties de suport.
- **Desenvolupament actiu** — Les coses canvien. Les APIs poden evolucionar. La documentacio pot anar per darrere del codi.

## Que NO es server-nexe

- NO es un substitut de ChatGPT, Claude ni serveis d'IA al nuvol
- NO es un producte enterprise amb SLA
- NO es una plataforma multi-usuari
- NO te garantia d'absencia de bugs (es un projecte personal de codi obert)
- NO es npm nexe (compilador Node.js — completament no relacionat)
