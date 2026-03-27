# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-limitations

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Honest documentation of server-nexe 0.8.2 limitations. Covers platform support (macOS tested, Linux partial, Windows not yet), model quality vs cloud (GPT-4/Claude), RAG limitations (embeddings, chunking, cold start, contradictions), API partial OpenAI compatibility, performance (single instance, concurrency), security constraints, and functional gaps (no multi-user, no sync, no fine-tuning)."
tags: [limitations, platform, models, rag, performance, security, api, compatibility, honest]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: en
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Limitations — server-nexe 0.8.2

This document honestly describes what server-nexe cannot do or does not do well.

## Platform

| Platform | Status |
|----------|--------|
| macOS Apple Silicon | Tested, all 3 backends |
| macOS Intel | Tested, llama.cpp + Ollama (no MLX) |
| Linux x86_64 | Partial — unit tests pass (3901/3901), CI green, not production-tested |
| Linux ARM64 | Docker supported, not directly tested |
| Windows | Not supported |

## Model Quality

Local models are less capable than cloud models (GPT-4, Claude, etc.). This is the trade-off for privacy.

- **Small models (2-4B):** Good for simple tasks, short answers. Limited reasoning.
- **Medium models (7-8B):** Adequate for most everyday tasks. Occasional hallucinations.
- **Large models (32B+):** Good quality, but require 32+ GB RAM and slow loading.
- **Catalan:** Salamandra models (BSC/AINA) are best for Catalan. Other models have limited Catalan support.

## RAG Limitations

- **Homonyms:** "bank" (seat) vs "bank" (finance) get similar embeddings. Same word, different meanings.
- **Negations:** "I don't like Python" ≈ "I like Python" in embedding space.
- **Cold start:** Empty memory = RAG contributes nothing. Need to populate first.
- **Top-K misses:** If you have lots of data, relevant info may not be in Top-3/5 results.
- **Contradictory info:** RAG may retrieve conflicting facts from different time periods.
- **Chunk boundaries:** Information split across chunk boundaries may be partially retrieved.
- **Embedding model:** 768-dimensional vectors capture meaning well but not perfectly. Specialized domain vocabulary may have lower accuracy.

## API Compatibility

Partially compatible with OpenAI API format:

| Feature | Status |
|---------|--------|
| /v1/chat/completions | Functional (messages, temperature, max_tokens, stream) |
| /v1/embeddings (standard) | Not implemented (use /v1/embeddings/encode instead) |
| /v1/models | Not implemented |
| /v1/completions (legacy) | Not implemented |
| /v1/fine-tuning | Not implemented |
| Function calling | Not implemented |
| Vision/multimodal | Not implemented |

## Performance

- **Single instance:** One server process, not clustered.
- **Concurrency:** Limited by model inference (one request at a time per backend).
- **Startup time:** 5-15 seconds (Qdrant + module loading + knowledge ingestion on first run).
- **Model loading:** 10-60 seconds depending on model size and backend.
- **RAM consumption:** Model + Qdrant + Python = significant. 8GB RAM is tight for 7B models.
- **Disk:** Models (1-40 GB) + Qdrant vectors + logs. Estimate 10-50 GB total.

## Security

- **Prompt injection:** Local models may follow injected instructions. Sanitizer catches common patterns (69 jailbreak patterns) but not all.
- **No TLS by default:** HTTP on localhost. Use reverse proxy for HTTPS.
- **Single-user:** No multi-user isolation. One API key = full access.
- **Qdrant unencrypted:** Vectors on disk in plaintext. Use disk encryption.
- **Ollama keep_alive bug:** keep_alive:0 doesn't always release VRAM (known Ollama issue).

## Functional Gaps

- **No multi-device sync** — Local only, no cloud sync.
- **No model fine-tuning** — Cannot train or fine-tune models.
- **No OCR** — Cannot extract text from images or scanned PDFs.
- **No multi-user** — Single API key, no user accounts.
- **No real-time collaboration** — Single-user, single-session design.
- **No scheduled tasks** — No cron-like automation built-in.
- **Web UI is functional but basic** — Not a full-featured chat app. Working streaming, uploads, memory, i18n, but no message editing, no branching, no export.

## What server-nexe is NOT

- NOT a replacement for ChatGPT, Claude, or cloud AI services
- NOT an enterprise product with SLA
- NOT a multi-user platform
- NOT guaranteed bug-free (it's a personal open-source project)
- NOT npm nexe (Node.js compiler — completely unrelated)
