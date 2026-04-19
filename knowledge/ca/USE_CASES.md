# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-use-cases
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Casos d'us practics de server-nexe 1.0.1-beta: assistent personal amb memoria, base de coneixement privada, desenvolupament assistit (Cursor/Continue/Zed), cerca semantica, experimentacio amb backends, IA local segura per compliance. Inclou guia de quan server-nexe TE sentit (privacitat, offline, control) i quan NO (multi-usuari, models frontier, hardware limitat, fine-tuning, SLA)."
tags: [use-cases, casos-d-us, assistent, rag, cursor, continue, zed, api, privacy, local, compliance, privacidad]
chunk_size: 600
priority: P2

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Casos d'us — server-nexe 1.0.1-beta

server-nexe esta pensat per a escenaris on **privacitat, control local i memoria persistent** tenen valor concret. Aquesta es la llista dels casos d'us mes testejats, amb context practic per a cada un.

## 1. Assistent personal amb memoria

**Per a qui:** usuaris que volen un assistent que aprengui de les seves converses sense enviar dades al nuvol.

Pregunta sobre projectes en curs, preferencies, terminis. El sistema **MEM_SAVE** recorda el context automaticament (noms, feines, terminis, decisions) i el recupera en sessions futures via RAG. La memoria es persistent, encriptada at-rest, i nomes viu al teu dispositiu.

**Exemple:** "Recorda que el proper dilluns tinc reunio amb Xiri." → Setmanes despres: *"Quan vaig quedar amb l'Xiri?"* → el sistema ho recorda.

## 2. Base de coneixement privada

**Per a qui:** professionals que treballen amb documents sensibles (legal, medic, consultoria) i no poden pujar-los a serveis cloud.

Puja `.txt`, `.md` o `.pdf` i s'indexen automaticament al RAG. Consulta'ls en llenguatge natural. Cada document queda **aillat per sessio** — no es creua context entre converses sense voler-ho.

**Exemple:** puja contractes i pregunta *"Quines clausules de rescissio mencionen penalitzacio economica?"*

## 3. Desenvolupament assistit per IA (Cursor, Continue, Zed)

**Per a qui:** desenvolupadors que volen IA al seu IDE sense enviar el codi propietari a tercers.

L'API compatible amb OpenAI (`/v1/chat/completions`) funciona amb qualsevol eina que accepti un endpoint OpenAI-like. Configura la URL base a `http://127.0.0.1:9119/v1` i la clau API del teu `.env`.

**Exemple config Cursor:** Settings → Models → Add Model → OpenAI-compatible → Base URL `http://127.0.0.1:9119/v1` + capçalera `X-API-Key` amb el valor de `NEXE_PRIMARY_API_KEY`.

## 4. Cerca semantica

**Per a qui:** equips que volen cercar documents per *significat*, no per paraules clau exactes.

`POST /v1/memory/search` retorna els fragments mes similars a la teva consulta, amb puntuacio de similitud. Els embeddings multilingues (fastembed, 768-dim, ONNX) funcionen en catala, castella i angles sense cap canvi de config.

**Exemple:** cerca *"com es fa el deploy"* → troba docs que parlen de *"publicacio"*, *"release process"*, *"push a produccio"*, *"desplegament"*, etc.

## 5. Experimentacio amb models

**Per a qui:** usuaris que volen comparar empiricament velocitat i qualitat de diferents backends i models locals.

Canvia entre **MLX** (natiu Apple Silicon), **llama.cpp** (GGUF universal) i **Ollama** (gestio facil) amb un canvi de config. Cataleg de 16 models en 4 tiers de RAM — des de Gemma 3 4B fins ALIA-40B.

**Exemple:** prova Qwen3.5 9B (Ollama, tier_16) vs Gemma 4 E4B (MLX, tier_16) per saber quin encaixa millor amb el teu hardware i cas d'us.

## 6. IA local segura (compliance, dades sensibles)

**Per a qui:** organitzacions amb requeriments de compliance (RGPD, HIPAA, secret professional) que no poden enviar dades a un proveidor extern.

Activa l'encriptacio at-rest (`NEXE_ENCRYPTION_ENABLED=auto`, fail-closed des de v0.9.2) i totes les dades queden xifrades amb AES-256-GCM: base de dades SQLite (via SQLCipher), sessions de xat (`.enc`) i text de documents RAG.

**Nota compliance:** server-nexe NO ha passat certificacions externes. L'encriptacio es forta pero el sistema es un projecte open-source d'un desenvolupador, no un producte enterprise amb auditories professionals.

---

## Quan server-nexe NO es la millor eina

Sigues honest sobre les limitacions. Hi ha casos d'us on altres opcions son millors:

| Si necessites... | Prova... |
|------------------|----------|
| Models frontier (GPT-5, Claude Opus 4.5, Gemini 3) | Serveis cloud oficials — els models locals encara son menys capaços |
| Multi-usuari amb sync entre dispositius | server-nexe es **mono-usuari per disseny**. Considera un desplegament client-servidor extern |
| Suport Windows o Linux arm64 de produccio | server-nexe requereix **macOS 14+ Apple Silicon** des de v0.9.9 |
| Fine-tuning o entrenament de models | No es funcio de server-nexe. Usa MLX, transformers o Axolotl directament |
| Garantia d'uptime i SLA | Es un projecte open-source mantingut per una persona — no hi ha SLA |
| Auditoria de seguretat professional | Les auditories actuals son IA-assistides (Claude, Gemini, Codex), no per empreses humanes especialitzades |

## Referencies

- [[INSTALLATION|Com instal·lar]] — metodes DMG i CLI
- [[API|API completa]] — tots els endpoints
- [[USAGE|Us diari]] — comandes CLI i Web UI
- [[IDENTITY|Que es server-nexe]]
- [[LIMITATIONS|Limitacions tecniques]]
