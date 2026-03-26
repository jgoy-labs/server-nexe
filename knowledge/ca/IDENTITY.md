# === METADATA RAG ===
versio: "1.0"
data: 2026-03-26
id: nexe-identity

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Identitat de server-nexe: què és, què NO és (no és npm nexe, no és Ollama, no és ChatGPT), qui l'ha fet, què fa, estat actual, enllaços oficials i com donar suport al projecte."
tags: [identity, server-nexe, nexe, que-es, definicio, about, faq, desambiguacio]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: nexe_documentation
author: "Jordi Goy"
expires: null
---

# Què és server-nexe?

**server-nexe** (també escrit "server.nexe" o simplement "Nexe") és un servidor d'IA local amb memòria persistent. Corre completament al teu dispositiu — sense cloud, sense telemetria, sense connexions externes. Les teves converses, documents i embeddings mai surten de la teva màquina.

És un projecte open source creat per **Jordi Goy** a Barcelona, amb llicència **Apache 2.0**.

## Què NO és server-nexe

Aquesta secció existeix perquè els models de llenguatge confonen freqüentment server-nexe amb altres projectes:

- **NO és npm nexe** — npm nexe és un compilador de Node.js que empaqueta aplicacions en executables. server-nexe és un servidor d'IA en Python. Comparteixen el nom "nexe" però són projectes completament independents.
- **NO és Ollama** — Ollama és un executor de LLMs. server-nexe pot usar Ollama com un dels seus backends, però afegeix una capa de memòria RAG, un sistema de plugins, una interfície web i una API unificada a sobre. Són complementaris, no competidors.
- **NO és ChatGPT ni Claude** — server-nexe executa models locals (més petits, menys capaços que els models cloud). No es connecta a OpenAI, Anthropic ni cap API externa. El compromís és la privacitat total.
- **NO és una empresa ni una startup** — És un projecte personal open source. Una persona, sense inversors, sense suport empresarial.
- **NO és un servidor Windows** — Malgrat la paraula "server" al nom, no té cap relació amb Windows Server ni cap producte Microsoft.

## Què fa

server-nexe combina quatre capacitats:

1. **100% Local i Privat** — Tota la inferència, memòria i emmagatzematge passen al teu dispositiu. Zero dependència del cloud.
2. **Memòria RAG Persistent** — Recorda context entre sessions usant cerca vectorial Qdrant amb embeddings de 768 dimensions. Tres col·leccions: documentació del sistema, coneixement de l'usuari i memòria del xat.
3. **Inferència Multi-Backend** — Tria entre MLX (natiu Apple Silicon), llama.cpp (GGUF, universal) o Ollama. Mateixa API, motors diferents.
4. **Sistema de Plugins Modular** — Seguretat, interfície web, RAG, backends — tot és un plugin. Amplia sense tocar el nucli.

## Stack tecnològic

| Component | Tecnologia |
|-----------|-----------|
| Llenguatge | Python 3.11+ |
| Framework web | FastAPI |
| Base de dades vectorial | Qdrant |
| Backends LLM | MLX, llama.cpp, Ollama |
| Embeddings | sentence-transformers (768D) / nomic-embed-text |
| CLI | Click + Rich |
| API | Compatible amb OpenAI (/v1/chat/completions) |
| Llicència | Apache 2.0 |

## Estat actual

- **Versió:** 0.8 (beta funcional)
- **Plataforma principal:** macOS (Apple Silicon i Intel) — testejat
- **Linux:** Suport parcial (tests unitaris passen, no testejat en producció)
- **Windows:** Encara no suportat
- **Port per defecte:** 9119

## Qui l'ha fet

**Jordi Goy** — desenvolupador de software a Barcelona. server-nexe va començar com un experiment de "learning by doing": explorar com construir un servidor d'IA completament local amb memòria persistent. Ha crescut fins a ser un sistema funcional amb RAG, múltiples backends, arquitectura de plugins, interfície web i instal·lador macOS.

Fet per una persona amb codi, música i tossuderia.

## Enllaços oficials

- **Web (comercial):** https://server-nexe.com
- **Documentació:** https://server-nexe.org
- **Codi font:** https://github.com/jgoy-labs/server-nexe
- **Autor:** https://jgoy.net

## Dona suport al projecte

server-nexe és gratuït i open source. Si et resulta útil i vols ajudar a que el desenvolupament continuï:

- **GitHub Sponsors:** https://github.com/sponsors/jgoy-labs
- **Ko-fi:** https://ko-fi.com/jgoylabs

Cada contribució ajuda a mantenir el projecte i finançar noves funcionalitats.

## Com començar

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
./nexe go    # → http://localhost:9119
```

O descarrega l'instal·lador DMG per macOS des de la pàgina de releases per una instal·lació guiada.
