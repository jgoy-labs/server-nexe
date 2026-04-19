# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-use-cases
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Practical use cases of server-nexe 1.0.1-beta: personal assistant with memory, private knowledge base, AI-assisted development (Cursor/Continue/Zed), semantic search, backend experimentation, secure local AI for compliance. Includes guidance on when server-nexe makes sense (privacy, offline, control) and when it does NOT (multi-user, frontier models, limited hardware, fine-tuning, SLA)."
tags: [use-cases, assistant, rag, cursor, continue, zed, api, privacy, local, compliance]
chunk_size: 600
priority: P2

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Use Cases — server-nexe 1.0.1-beta

server-nexe is designed for scenarios where **privacy, local control and persistent memory** have concrete value. This is the list of the most tested use cases, with practical context for each.

## 1. Personal assistant with memory

**For whom:** users who want an assistant that learns from their conversations without sending data to the cloud.

Ask about ongoing projects, preferences, deadlines. The **MEM_SAVE** system automatically remembers context (names, jobs, deadlines, decisions) and retrieves it in future sessions via RAG. Memory is persistent, encrypted at-rest, and lives only on your device.

**Example:** "Remember that next Monday I have a meeting with Xiri." → Weeks later: *"When did I meet with Xiri?"* → the system remembers.

## 2. Private knowledge base

**For whom:** professionals who work with sensitive documents (legal, medical, consulting) and cannot upload them to cloud services.

Upload `.txt`, `.md` or `.pdf` and they are automatically indexed in RAG. Query them in natural language. Each document is **isolated per session** — no cross-contamination between conversations without you wanting it.

**Example:** upload contracts and ask *"Which termination clauses mention financial penalties?"*

## 3. AI-assisted development (Cursor, Continue, Zed)

**For whom:** developers who want AI in their IDE without sending proprietary code to third parties.

The OpenAI-compatible API (`/v1/chat/completions`) works with any tool that accepts an OpenAI-like endpoint. Configure the base URL to `http://127.0.0.1:9119/v1` and your `.env` API key.

**Example Cursor config:** Settings → Models → Add Model → OpenAI-compatible → Base URL `http://127.0.0.1:9119/v1` + `X-API-Key` header with the value from `NEXE_PRIMARY_API_KEY`.

## 4. Semantic search

**For whom:** teams that want to search documents by *meaning*, not by exact keyword match.

`POST /v1/memory/search` returns the most similar fragments to your query, with similarity scores. Multilingual embeddings (fastembed, 768-dim, ONNX) work in Catalan, Spanish and English without any config change.

**Example:** search *"how to deploy"* → finds docs about *"release process"*, *"push to production"*, *"shipping"*, etc.

## 5. Model experimentation

**For whom:** users who want to empirically compare speed and quality of different backends and local models.

Switch between **MLX** (Apple Silicon native), **llama.cpp** (universal GGUF) and **Ollama** (easy management) with a config change. 16-model catalog across 4 RAM tiers — from Gemma 3 4B to ALIA-40B.

**Example:** try Qwen3.5 9B (Ollama, tier_16) vs Gemma 4 E4B (MLX, tier_16) to figure out which one fits your hardware and use case best.

## 6. Secure local AI (compliance, sensitive data)

**For whom:** organisations with compliance requirements (GDPR, HIPAA, professional secrecy) that cannot send data to an external provider.

Enable encryption at-rest (`NEXE_ENCRYPTION_ENABLED=auto`, fail-closed since v0.9.2) and all data is encrypted with AES-256-GCM: SQLite database (via SQLCipher), chat sessions (`.enc`), and RAG document text.

**Compliance note:** server-nexe has NOT passed external certifications. The encryption is strong but the system is an open-source project by a single developer, not an enterprise product with professional audits.

---

## When server-nexe is NOT the best tool

Be honest about limitations. There are use cases where other options are better:

| If you need... | Try... |
|----------------|--------|
| Frontier models (GPT-5, Claude Opus 4.5, Gemini 3) | Official cloud services — local models are still less capable |
| Multi-user with device sync | server-nexe is **mono-user by design**. Consider an external client-server deployment |
| Production Windows or Linux arm64 support | server-nexe requires **macOS 14+ Apple Silicon** since v0.9.9 |
| Model fine-tuning or training | Not a server-nexe feature. Use MLX, transformers or Axolotl directly |
| Uptime guarantees and SLA | It's an open-source project maintained by one person — no SLA |
| Professional security audit | Current audits are AI-assisted (Claude, Gemini, Codex), not by specialised human security firms |

## References

- [[INSTALLATION|How to install]] — DMG and CLI methods
- [[API|Full API]] — all endpoints
- [[USAGE|Daily usage]] — CLI commands and Web UI
- [[IDENTITY|What server-nexe is]]
- [[LIMITATIONS|Technical limitations]]
