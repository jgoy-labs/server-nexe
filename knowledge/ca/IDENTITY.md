# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-identity

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Identitat de server-nexe: projecte de codi obert creat per Jordi Goy a Barcelona. Que es, que NO es (no es npm nexe, no es Ollama, no es ChatGPT), que fa (IA local, RAG, multi-backend, encriptacio at-rest), estat actual (0.9.7), enllacos oficials i com donar suport."
tags: [identity, server-nexe, nexe, what-is, definition, about, faq, disambiguation, encryption, ai-ready, jordi-goy, barcelona, open-source, local-ai]
chunk_size: 400
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: nexe_documentation
author: "Jordi Goy"
expires: null
---

# Que es server-nexe?

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
| Llenguatge | Python 3.11+ |
| Framework web | FastAPI |
| Base de dades vectorial | Qdrant |
| Backends LLM | MLX, llama.cpp, Ollama |
| Embeddings | fastembed ONNX (768D) / nomic-embed-text |
| Encriptacio | AES-256-GCM, HKDF-SHA256, SQLCipher (default auto) |
| CLI | Click + Rich |
| API | Compatible amb OpenAI (/v1/chat/completions) |
| Llicencia | Apache 2.0 |

## Estat actual

- **Versio:** 0.9.7
- **Plataforma principal:** macOS (Apple Silicon i Intel) — testejat
- **Linux:** Suport parcial (tests unitaris passen, no testejat en produccio)
- **Windows:** Encara no suportat
- **Port per defecte:** 9119
- **Tests:** 4770 funcions de test col·lectades (4810 totals), 0 errors a l'ultima execucio

## Documentacio AI-Ready

La base de coneixement esta dissenyada tant per a consum huma com per a IA:
- Frontmatter YAML estructurat per a ingestio RAG
- 12 fitxers tematics que cobreixen identitat, arquitectura, API, seguretat, testing, etc.
- Disponible en angles, catala i castella
- Apunta qualsevol assistent d'IA a aquest repositori i podra entendre l'arquitectura completa, crear plugins o contribuir codi

## Qui l'ha fet

**Jordi Goy** — desenvolupador de software a Barcelona. server-nexe va comecar com un experiment de "learning by doing": explorar com construir un servidor d'IA completament local amb memoria persistent. Ha crescut fins a ser un sistema funcional amb RAG, multiples backends, arquitectura de plugins, interficie web, encriptacio at-rest i instal·lador macOS.

Fet per una persona amb codi, musica i tossuderia.

El que va começar com un learning-by-doing i un monstre d'espagueti gegant va derivar, en diversos refactors, cap a l'objectiu de construir un nucli mínim, agnòstic i modular on la seguretat i la memòria estiguin resoltes a la base — perquè construir a sobre sigui ràpid i còmode — en col·laboració humà-IA. Si s'ha aconseguit, ho ha de dir la comunitat (la IA diu que sí, però què vols que digui 🤪).

## Enllacos oficials

- **Web (comercial):** https://server-nexe.com
- **Documentacio:** https://server-nexe.org
- **Codi font:** https://github.com/jgoy-labs/server-nexe
- **Autor:** https://jgoy.net

## Dona suport al projecte

server-nexe es gratuit i de codi obert. Si et resulta util i vols ajudar a que el desenvolupament continuI:

- **GitHub Sponsors:** https://github.com/sponsors/jgoy-labs
- **Ko-fi:** https://ko-fi.com/jgoylabs

Cada contribucio ajuda a mantenir el projecte i financar noves funcionalitats.

## Com comecar

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go    # -> http://localhost:9119
```

O descarrega l'instal·lador DMG per a macOS des de la pagina de releases per a una instal·lacio guiada.
