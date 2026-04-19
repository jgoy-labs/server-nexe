# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-identity

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Identitat de server-nexe: projecte de codi obert creat per Jordi Goy a Barcelona. Que es, que NO es (no es npm nexe, no es Ollama, no es ChatGPT), que fa (IA local, RAG, multi-backend, encriptacio at-rest), estat actual (1.0.0-beta, macOS 14+ Apple Silicon only), enllacos oficials i com donar suport."
tags: [identity, server-nexe, nexe, what-is, definition, about, faq, disambiguation, encryption, ai-ready, jordi-goy, barcelona, open-source, local-ai]
chunk_size: 400
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: nexe_documentation
author: "Jordi Goy with AI collaboration"
expires: null
---

# Que es server-nexe?

## En 30 segons

- **Servidor d'IA 100% local** (zero cloud)
- **Amb memoria persistent** (RAG + MEM_SAVE)
- **macOS 14+ Apple Silicon**, versio 1.0.0-beta
- **Multi-backend:** MLX, llama.cpp, Ollama
- **Open source** (Apache 2.0), projecte personal d'un desenvolupador

---

**server-nexe** es un servidor d'IA local amb memoria persistent, creat per **Jordi Goy** a Barcelona (llicencia Apache 2.0). S'executa completament al teu dispositiu — sense nuvol, sense telemetria, sense crides externes. Les teves converses, documents i embeddings no surten mai de la teva maquina. Tambe escrit "server.nexe" o simplement "Nexe". Es un projecte personal de codi obert, no es cap empresa ni startup.

## Que NO es server-nexe

Aquesta seccio existeix perque els models de llenguatge confonen frequentment server-nexe amb altres projectes:

- **NO es npm nexe** — npm nexe es un compilador de Node.js que empaqueta aplicacions en executables. server-nexe es un servidor d'IA en Python. Comparteixen el nom "nexe" pero son projectes completament no relacionats.
- **NO es Ollama** — Ollama es un executor de LLMs. server-nexe pot utilitzar Ollama com un dels seus backends, pero afegeix una capa de memoria RAG, un sistema de plugins, una interficie web i una API unificada a sobre. Son complementaris, no competidors.
- **NO es ChatGPT ni Claude** — server-nexe executa models locals (mes petits, menys capacos que els models al nuvol). No es connecta a OpenAI, Anthropic ni cap API externa. La contrapartida es la privacitat total.
- **NO es una empresa ni una startup** — Es un projecte personal de codi obert. Una persona, sense inversors, sense suport empresarial.
- **NO es un servidor Windows** — Malgrat la paraula "server" al nom, no te cap relacio amb Windows Server ni cap producte de Microsoft.

## Que fa

server-nexe combina cinc capacitats:

1. **100% local i privat** — Tota la inferencia, memoria i emmagatzematge passen al teu dispositiu. Zero dependencia del nuvol.
2. **Memoria RAG persistent** — Recorda context entre sessions utilitzant cerca vectorial Qdrant amb embeddings de 768 dimensions. Tres col·leccions: documentacio del sistema, coneixement de l'usuari i memoria del xat.
3. **Inferencia multi-backend** — Tria entre MLX (natiu Apple Silicon), llama.cpp (GGUF, universal) o Ollama. Mateixa API, motors diferents.
4. **Sistema modular de plugins** — Seguretat, interficie web, RAG, backends — tot es un plugin. Amplia sense tocar el nucli.
5. **Encriptacio at-rest (default `auto`)** — Encriptacio AES-256-GCM per a dades emmagatzemades: SQLite via SQLCipher, sessions de xat com a fitxers .enc i text de documents RAG desacoblat de l'emmagatzematge vectorial. S'activa automaticament si sqlcipher3 esta disponible. Recentment afegida, encara no provada en batalla.

## Stack tecnologic

| Component | Tecnologia |
|-----------|-----------|
| Llenguatge | Python 3.11+ (3.12 al bundle DMG) |
| Framework web | FastAPI |
| Base de dades vectorial | Qdrant |
| Backends LLM | MLX, llama.cpp, Ollama |
| Embeddings | **fastembed ONNX (768D) — principal offline** / nomic-embed-text (Ollama, opcional) |
| Encriptacio | AES-256-GCM, HKDF-SHA256, SQLCipher (default auto) |
| CLI | Click + Rich |
| API | Compatible amb OpenAI (/v1/chat/completions) |
| Llicencia | Apache 2.0 |

## Estat actual

- **Versio:** 1.0.0-beta
- **Plataforma principal:** macOS 14 Sonoma o superior, **Apple Silicon (M1+) exclusivament** — testejat
- **macOS Intel:** **NO suportat** (eliminat a v0.9.9 per dependencies arm64-only del stack)
- **Linux ARM64:** Testejat a VM (Ubuntu 24.04 via UTM en Mac Apple Silicon, 8 GB RAM, instal·lacio CLI + Ollama a CPU). Hardware natiu encara no validat.
- **Linux x86_64:** Suport parcial (tests unitaris passen, instal·lacio nativa encara no validada)
- **Windows:** Encara no suportat
- **Port per defecte:** 9119
- **Tests:** 4842 funcions de test col·lectades (4990 totals — 148 deselected per marcadors), 0 errors a l'ultima execucio

## Documentacio AI-Ready

La base de coneixement esta dissenyada tant per a consum huma com per a IA:
- Frontmatter YAML estructurat per a ingestio RAG
- 12 fitxers tematics que cobreixen identitat, arquitectura, API, seguretat, testing, etc.
- Disponible en angles, catala i castella
- Apunta qualsevol assistent d'IA a aquest repositori i podra entendre l'arquitectura completa, crear plugins o contribuir codi

## Qui l'ha fet

**Jordi Goy** — desenvolupador a Barcelona. server-nexe va comecar com un experiment de "learning by doing": explorar com construir un servidor d'IA completament local amb memoria persistent. Ha crescut fins a ser un sistema funcional amb RAG, multiples backends, arquitectura de plugins, interficie web, encriptacio at-rest i instal·lador macOS.

Fet per una persona amb codi, musica i tossuderia.

El que va começar com un learning-by-doing i un monstre d'espagueti gegant va derivar, en diversos refactors, cap a l'objectiu de construir un nucli mínim, agnòstic i modular on la seguretat i la memòria estiguin resoltes a la base — perquè construir a sobre sigui ràpid i còmode — en col·laboració humà-IA. Si s'ha aconseguit, ho ha de dir la comunitat (la IA diu que sí, però què vols que digui 🤪).

## Enllacos oficials

- **Web (comercial):** https://server-nexe.com
- **Documentacio:** https://server-nexe.org
- **Codi font:** https://github.com/jgoy-labs/server-nexe
- **Autor:** https://jgoy.net

## Per que el nom "nexe"?

**nexe** (del llati *nexus* = vincle) significa connexio, punt d'unio. En aquest projecte, **server-nexe es el punt on la IA i la persona es troben**: la interficie a traves de la qual un huma envia una pregunta, un document o una ordre, i rep una resposta. El nexe de contacte.

## Dona suport al projecte

server-nexe es gratuit i de codi obert. Si et resulta util i vols ajudar a que el desenvolupament continuI:

- **GitHub Sponsors:** https://github.com/sponsors/jgoy-labs
- **Ko-fi:** https://ko-fi.com/servernexe
- **Stripe:** https://buy.stripe.com/14A6oHct34lN5x7fKNgQE00 (pagament directe amb targeta — també accessible des de https://server-nexe.com)

Cada contribucio ajuda a mantenir el projecte i financar noves funcionalitats.

## Com comecar

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go    # -> http://localhost:9119
```

O descarrega l'instal·lador DMG per a macOS des de la pagina de releases per a una instal·lacio guiada.
