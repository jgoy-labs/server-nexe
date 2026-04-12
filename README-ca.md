<p align="center">
  <img src=".github/logo.svg" alt="server.nexe" width="400">
</p>

<p align="center">
  <strong>Servidor d'IA local amb memòria persistent. Zero núvol. Control total.</strong>
</p>

<p align="center">
  <a href="https://github.com/jgoy-labs/server-nexe/actions/workflows/ci.yml"><img src="https://github.com/jgoy-labs/server-nexe/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src=".github/badges/coverage.svg" alt="Coverage">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
</p>

<p align="center">
  <a href="https://qdrant.tech"><img src="https://img.shields.io/badge/Qdrant-vector--db-dc244c?logo=qdrant&logoColor=white" alt="Qdrant"></a>
  <a href="https://github.com/ml-explore/mlx"><img src="https://img.shields.io/badge/MLX-Apple%20Silicon-000000?logo=apple&logoColor=white" alt="MLX"></a>
  <a href="https://ollama.com"><img src="https://img.shields.io/badge/Ollama-compatible-black?logo=ollama&logoColor=white" alt="Ollama"></a>
  <a href="https://github.com/ggerganov/llama.cpp"><img src="https://img.shields.io/badge/llama.cpp-GGUF-8B5CF6" alt="llama.cpp"></a>
  <a href="https://github.com/jgoy-labs/server-nexe"><img src="https://img.shields.io/badge/RAG-local%20%7C%20private-22c55e" alt="RAG"></a>
  <a href="https://github.com/sponsors/jgoy-labs"><img src="https://img.shields.io/badge/sponsor-♥-ea4aaa?logo=github-sponsors&logoColor=white" alt="Sponsor"></a>
</p>

<p align="center">
  <a href="https://server-nexe.org"><strong>Documentació</strong></a> ·
  <a href="#-inici-ràpid"><strong>Instal·lar</strong></a> ·
  <a href="#-arquitectura"><strong>Arquitectura</strong></a> ·
  <a href="https://github.com/jgoy-labs/server-nexe/releases"><strong>Releases</strong></a>
</p>

<p align="center">
  <a href="README.md"><strong>Read in English</strong></a>
</p>

---

## La Història

Server Nexe va començar com un experiment de learning-by-doing: *"Què caldria per tenir un servidor d'IA completament local amb memòria persistent?"* Una pregunta en va portar una altra — backends d'inferència, pipelines RAG, cerca vectorial, sistemes de plugins, capes de seguretat, una interfície web, un instal·lador amb detecció de hardware.

**Tot aquest projecte — codi, tests, auditories, documentació — ha estat construït per una sola persona orquestrant diferents models d'IA**, tant locals (MLX, Ollama) com al núvol (Claude, GPT, Gemini, DeepSeek, Qwen, Grok), com a col·laboradors. L'humà decideix què construir, dissenya l'arquitectura, revisa cada línia i executa cada test. Les IAs escriuen, auditen i fan stress-test sota direcció humana. Cap línia de codi surt sense que una persona l'entengui i se'n faci responsable.

El que va començar com un prototip de cap de setmana s'ha convertit en un producte genuïnament útil: 4572 tests, auditories de seguretat, encriptació at-rest, un instal·lador macOS amb detecció de hardware, i un sistema de plugins. No està acabat — hi ha un roadmap ple d'idees — però ja fa el que es proposava: **executar un servidor d'IA a la teva màquina, amb memòria que persisteix, i zero dades sortint del teu dispositiu.**

No intenta competir amb ChatGPT ni Claude. És una eina open-source per a gent que vol ser propietària de la seva infraestructura d'IA. Construït per una persona a Barcelona, amb IA com a copilot, música, i tossuderia.

## Per Què Server Nexe?

Les teves converses, documents, embeddings i pesos dels models es queden a la teva màquina. Sempre. Server Nexe combina inferència LLM amb un **sistema de memòria RAG persistent** — la teva IA recorda context entre sessions, indexa els teus documents, i mai truca a casa.

<table>
<tr>
<td width="50%">

### Local i Privat
Cada conversa, document i embedding es queda al teu dispositiu. Sense telemetria, sense crides externes, sense dependència del núvol. Ni tan sols un servidor que t'espiï.

</td>
<td width="50%">

### Memòria RAG Persistent
Recorda context entre sessions usant cerca vectorial Qdrant amb embeddings de 768 dimensions en 3 col·leccions especialitzades: `personal_memory`, `user_knowledge`, `nexe_documentation`.

</td>
</tr>
<tr>
<td width="50%">

### Memòria Automàtica (MEM_SAVE)
El model extreu fets de les converses automàticament — noms, feines, preferències, projectes — i els guarda a memòria dins la mateixa crida LLM, amb zero latència extra. Detecció d'intents trilingüe (ca/es/en), deduplicació semàntica, i esborrat per veu ("oblida que...").

</td>
<td width="50%">

### Inferència Multi-Backend
Canvia entre MLX (natiu Apple Silicon), llama.cpp (GGUF, universal), o Ollama — un canvi de config, mateixa API compatible amb OpenAI.

</td>
</tr>
<tr>
<td width="50%">

### Sistema Modular de Plugins
Plugins auto-descoberts amb manifests independents. Seguretat, web UI, RAG, backends — tot és un plugin. Afegeix capacitats sense tocar el core. Protocol NexeModule amb duck typing, sense herència.

</td>
<td width="50%">

### Instal·lador macOS
DMG amb assistent guiat que detecta el teu hardware, tria el backend adequat, recomana models per la teva RAM, i et posa en marxa en minuts.

</td>
</tr>
<tr>
<td width="50%">

### Pujada de Documents amb Aïllament de Sessió
Puja .txt, .md o .pdf i s'indexen automàticament per RAG. Cada document només és visible dins la sessió on s'ha pujat — sense contaminació creuada entre sessions.

</td>
<td width="50%">

### Construït per Créixer
4572 tests, auditoria de seguretat, i18n en 3 idiomes, API completa. El que va començar com un experiment es construeix amb pràctiques de producció.

</td>
</tr>
</table>

## Inici Ràpid

### Opció A: Instal·lador DMG (macOS)

Descarrega l'últim **[Install Nexe.dmg](https://github.com/jgoy-labs/server-nexe/releases/latest)** de Releases. L'assistent ho gestiona tot: detecció de hardware, selecció de backend, descàrrega de model, i configuració.

### Opció B: Línia de comandes

```bash
git clone https://github.com/jgoy-labs/server-nexe.git
cd server-nexe
./setup.sh      # instal·lació guiada (detecta hardware, tria backend i model)
nexe go         # arrenca el servidor al port 9119
```

Un cop en marxa:

```bash
nexe chat               # xat interactiu
nexe chat --rag         # xat amb memòria RAG
nexe memory store "Barcelona és la capital de Catalunya"
nexe memory recall "capital Catalunya"
nexe status             # estat del sistema
```

### Opció C: Headless (servidors, scripts, CI)

```bash
python -m installer.install_headless --backend ollama --model qwen3.5:latest
nexe go
```

**Endpoints a `http://localhost:9119`:**

| Endpoint | Descripció |
|----------|------------|
| `/v1/chat/completions` | API de xat compatible amb OpenAI |
| `/ui` | Interfície web (xat, pujada de fitxers, sessions) |
| `/health` | Health check |
| `/docs` | Documentació interactiva de l'API (Swagger) |

> Autenticació via header `X-API-Key`. La clau es genera durant la instal·lació i es guarda a `.env`.

## Backends

| Backend | Plataforma | Millor per a |
|---------|-----------|-------------|
| **MLX** | macOS (Apple Silicon) | Recomanat per Mac — acceleració GPU Metal nativa, el més ràpid en xips M |
| **llama.cpp** | macOS / Linux | Universal — format GGUF, Metal a Mac, CPU/CUDA a Linux |
| **Ollama** | macOS / Linux | Pont a instal·lacions Ollama existents, gestió de models més fàcil |

L'instal·lador detecta automàticament el teu hardware i recomana el millor backend. Pots canviar en qualsevol moment a `personality/server.toml`.

## Models Disponibles per Tiers de RAM

L'instal·lador organitza els models per la RAM disponible al teu equip:

| Tier | Models | Origen |
|------|--------|--------|
| **8 GB** | Qwen3.5 9B, Gemma 4 E4B, Salamandra 2B | Alibaba, Google, BSC/AINA |
| **16 GB** | Llama 4 Scout (109B MoE), Salamandra 7B | Meta, BSC/AINA |
| **24 GB** | Qwen3.5 27B, Gemma 4 31B | Alibaba, Google |
| **32 GB** | Qwen3.5 35B (MoE), DeepSeek R1 32B, ALIA-40B | Alibaba, DeepSeek, Govern d'Espanya |
| **48 GB** | Qwen3.5 122B (MoE), Llama 4 Maverick (400B MoE) | Alibaba, Meta |
| **64 GB** | Qwen3.5 122B, GPT-OSS 120B | Alibaba, Nomic/Together |

A més, pots usar qualsevol model d'Ollama pel seu nom o qualsevol model GGUF de Hugging Face.

## Arquitectura

```
server-nexe/
├── core/                 # Servidor FastAPI, endpoints, CLI, config, mètriques, resiliència
│   ├── endpoints/        # API REST (v1 chat, health, status, system)
│   ├── cli/              # Comandes CLI i i18n (ca/es/en)
│   └── resilience/       # Circuit breaker, rate limiting
├── personality/          # Module manager, descobriment de plugins, server.toml
│   ├── loading/          # Pipeline de càrrega de plugins (find, validate, import, lifecycle)
│   └── module_manager/   # Descobriment, registre, config, sync
├── memory/               # Embeddings, motor RAG, memòria vectorial, ingestió de documents
│   ├── embeddings/       # Chunking, generació d'embeddings
│   ├── rag/              # Pipeline de Retrieval-Augmented Generation
│   └── memory/           # Vector store persistent (Qdrant)
├── plugins/              # Mòduls plugin auto-descoberts
│   ├── mlx_module/       # Backend MLX (Apple Silicon)
│   ├── llama_cpp_module/ # Backend llama.cpp (GGUF)
│   ├── ollama_module/    # Pont Ollama
│   ├── security/         # Auth, detecció d'injecció, CSRF, rate limiting, sanitització d'input
│   └── web_ui_module/    # Interfície de xat web amb pujada de fitxers
├── installer/            # Instal·lador guiat, mode headless, detecció de hardware, catàleg de models
├── knowledge/            # Documentació indexada per RAG (ca/es/en)
└── tests/                # Suites de tests d'integració i e2e
```

### Pipeline de processament de peticions

```mermaid
flowchart LR
    A[Petició] --> B[Auth<br/>X-API-Key]
    B --> C[Rate Limit<br/>slowapi]
    C --> D[validate_string_input<br/>paràmetre context]
    D --> E[RAG Recall<br/>3 col·leccions]
    E --> F[_sanitize_rag_context<br/>filtre d'injecció]
    F --> G[Inferència LLM<br/>MLX/Ollama/llama.cpp]
    G --> H[Resposta Stream<br/>marcadors SSE]
    H --> I[Parseig MEM_SAVE<br/>extracció de fets]
    I --> J[Resposta<br/>al client]
```

## Sistema de Plugins

Server Nexe utilitza un protocol de duck typing (NexeModule Protocol) — sense herència de classes, sense BasePlugin. Cada plugin és un directori sota `plugins/` amb un `manifest.toml` i un `module.py`.

**5 plugins actius:**

| Plugin | Tipus | Característiques clau |
|--------|-------|----------------------|
| **mlx_module** | Backend LLM | Natiu Apple Silicon, prefix caching (trie), GPU Metal |
| **llama_cpp_module** | Backend LLM | GGUF universal, ModelPool LRU, CPU/GPU |
| **ollama_module** | Backend LLM | Pont HTTP a Ollama, auto-arrencada, neteja VRAM |
| **security** | Core | Auth dual-key, 6 detectors d'injecció + NFKC, 47 patrons jailbreak, rate limiting, audit logging RFC5424 |
| **web_ui_module** | Interfície | Xat web, sessions, pujada documents, MEM_SAVE, sanitització RAG, i18n |

## Documentació AI-Ready

La carpeta `knowledge/` conté 12 documents temàtics × 3 idiomes = 36 fitxers, estructurats amb frontmatter YAML per a ingestió RAG:

API, Arquitectura, Errors, Identitat, Instal·lació, Limitacions, Plugins, RAG, README, Seguretat, Testing, Ús.

Apunta qualsevol assistent d'IA a aquest repo i pot entendre l'arquitectura completa.

| Idioma | Enllaç |
|--------|--------|
| Català | [knowledge/ca/README.md](knowledge/ca/README.md) |
| Anglès | [knowledge/en/README.md](knowledge/en/README.md) |
| Castellà | [knowledge/es/README.md](knowledge/es/README.md) |

## Seguretat

Server Nexe inclou un mòdul de seguretat activat per defecte:

- **Autenticació per clau API** a tots els endpoints
- **Capçaleres CSP** (`script-src 'self'`, sense `unsafe-inline`)
- **Protecció CSRF** amb validació de token
- **Rate limiting** per endpoint (20/min xat, 5/min upload)
- **Sanitització d'input** — 6 detectors d'injecció + normalització Unicode (NFKC)
- **Detecció de jailbreak** — 47 patrons speed-bump (v0.9.1)
- **Denylist de pujades** — bloqueja pujada accidental de claus API, claus PEM (v0.9.1)
- **Protecció d'injecció de memòria** — stripping de tags a tots els camins d'entrada (v0.9.1)
- **Enforcement de pipeline** — tot el xat passa pels endpoints canònics (v0.9.1)
- **Encriptació at-rest** — AES-256-GCM, SQLCipher, fail-closed (v0.9.1)
- **Trusted host middleware**

> **Nota:** Aquest projecte no ha estat testejat en producció amb usuaris reals. Les auditories de seguretat han estat fetes per IA, no per auditors professionals. Consulta [SECURITY.md](SECURITY.md) per al disclosure complet i l'informe de vulnerabilitats.

## Suport de Plataformes

| Plataforma | Estat | Backends |
|-----------|-------|----------|
| macOS Apple Silicon | Testejat, tots 3 backends | MLX, llama.cpp, Ollama |
| macOS Intel | Testejat | llama.cpp, Ollama (sense MLX) |
| Linux x86_64 | **Parcial** — tests unitaris passen, CI verd, **NO testejat en producció** | llama.cpp, Ollama |
| Linux ARM64 | No testejat directament | llama.cpp, Ollama (teòric) |
| Windows | No suportat | — |

> Server Nexe està optimitzat per macOS però hauria de funcionar a Linux amb els backends llama.cpp i Ollama. L'auditoria completa de compatibilitat Linux està al roadmap.

## Requisits

| | Mínim | Recomanat |
|---|-------|-----------|
| **SO** | macOS 13+ | macOS 14+ (Apple Silicon) |
| **Python** | 3.11+ | 3.12+ |
| **RAM** | 8 GB | 16 GB+ (per a models més grans) |
| **Disc** | 10 GB lliure | 20 GB+ lliure |

## Testing

4572 tests amb informes de cobertura. El CI executa la suite completa a cada push.

```bash
# Tests unitaris
pytest core memory personality plugins -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --tb=short -q

# Tests d'integració (requereix Ollama en marxa)
NEXE_AUTOSTART_OLLAMA=true pytest -m "integration" -q
```

## Full de Ruta

Server Nexe està en desenvolupament actiu. Pròximament:

- [x] Memòria persistent amb RAG (v0.9.0)
- [x] Encriptació at-rest — AES-256-GCM (v0.9.0)
- [x] Signatura de codi macOS i notarització (v0.9.0)
- [x] Hardening de seguretat — detecció jailbreak, denylist uploads, enforcement pipeline (v0.9.1)
- [ ] Suport multimodal — imatges via backends Ollama, llama.cpp i MLX
- [ ] Auditoria completa de compatibilitat Linux
- [ ] App nativa macOS (SwiftUI, substitueix el tray Python)
- [ ] Paràmetres d'inferència configurables via UI
- [ ] Fòrum de comunitat

Consulta [CHANGELOG.md](CHANGELOG.md) per a l'historial de versions.

## Limitacions

Disclosure honest del que server Nexe **no** fa o no fa bé:

- **Models locals < núvol** — Els models locals són menys capaços que GPT-4 o Claude. Aquesta és la contrapartida de la privacitat.
- **RAG no és perfecte** — Homonímia, negacions, inici en fred (memòria buida), i informació contradictòria entre períodes.
- **API parcialment compatible amb OpenAI** — `/v1/chat/completions` funciona. Falten `/v1/embeddings`, `/v1/models`, function calling, i multimodal.
- **Un sol usuari** — Disseny mono-usuari per arquitectura. Sense multi-device sync, sense comptes.
- **Sense fine-tuning** — No es poden entrenar ni ajustar models.
- **Encriptació nova** — Opt-in, afegida a v0.9.0, no provada en batalla. Si perds la clau mestra, les dades no es recuperen.
- **Un sol desenvolupador, un sol usuari real** — Projecte personal open-source, no producte enterprise.

Consulta [knowledge/ca/LIMITATIONS.md](knowledge/ca/LIMITATIONS.md) per al detall complet.

## Contribuir

Consulta [CONTRIBUTING.md](CONTRIBUTING.md) per a les instruccions de setup i les guies de contribució.

## Agraïments

server-nexe està construït sobre les espatlles d'aquests projectes open-source:

**IA i Inferència**
- [MLX](https://github.com/ml-explore/mlx) — Framework ML natiu per Apple Silicon
- [llama.cpp](https://github.com/ggerganov/llama.cpp) — Inferència eficient de models GGUF
- [Ollama](https://ollama.ai) — Gestió i servei de models locals
- [sentence-transformers](https://www.sbert.net) — Models d'embeddings de text
- [Hugging Face](https://huggingface.co) — Hub de models i llibreria transformers

**Infraestructura**
- [Qdrant](https://qdrant.tech) — Motor de cerca vectorial que alimenta la memòria RAG
- [FastAPI](https://fastapi.tiangolo.com) — Framework web async d'alt rendiment
- [Uvicorn](https://www.uvicorn.org) — Servidor ASGI
- [Pydantic](https://docs.pydantic.dev) — Validació de dades

**Eines i Llibreries**
- [Rich](https://github.com/Textualize/rich) — Formatació bonica per terminal
- [marked.js](https://marked.js.org) — Renderització Markdown a la web UI
- [PyPDF](https://github.com/py-pdf/pypdf) — Extracció de text de PDFs per RAG
- [rumps](https://github.com/jaredks/rumps) — Integració amb la barra de menú de macOS

**Seguretat i Monitoratge**
- [Prometheus](https://prometheus.io) — Mètriques i monitoratge
- [SlowAPI](https://github.com/laurentS/slowapi) — Rate limiting

El 20% dels patrocinis Enterprise van directament a donar suport a aquests projectes.

Construït amb col·laboració d'IA · Barcelona

## Avís Legal

Aquest software es proporciona **"tal com és"**, sense cap mena de garantia. Utilitza'l sota el teu propi risc. L'autor no és responsable de cap dany, pèrdua de dades, incidents de seguretat, o mal ús derivat de l'ús d'aquest software.

Consulta [LICENSE](LICENSE) per als detalls.

---

<p align="center">
  <strong>Versió 0.9.1</strong> · Apache 2.0 · Fet per <a href="https://www.jgoy.net">Jordi Goy</a> a Barcelona
</p>
