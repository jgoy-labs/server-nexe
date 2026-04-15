# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-limitations
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Honest documentation of server-nexe 0.9.7 limitations. Covers platform support (macOS tested, Linux partial, Windows not yet), model quality vs cloud (GPT-4/Claude), RAG limitations (embeddings, chunking, cold start, contradictions), API partial OpenAI compatibility, performance (single instance, concurrency), security constraints, encryption caveats (default auto, new, not battle-tested), and functional gaps (no multi-user, no sync, no fine-tuning)."
tags: [limitations, platform, models, rag, performance, security, api, compatibility, honest, encryption]
chunk_size: 800
priority: P2

# === OPCIONAL ===
lang: en
type: docs
author: "Jordi Goy"
expires: null
---

# Limitations — server-nexe 0.9.7

This document honestly describes what server-nexe cannot do or does not do well.

## Platform

| Platform | Status |
|----------|--------|
| macOS Apple Silicon | Tested, all 3 backends |
| macOS Intel | Tested, llama.cpp + Ollama (no MLX) |
| Linux x86_64 | Partial — unit tests pass, CI green, not production-tested |
| Linux ARM64 | Not directly tested |
| Windows | Not supported |

## Model Quality

Local models are less capable than cloud models (GPT-4, Claude, etc.). This is the trade-off for privacy.

- **Small models (2-4B):** Good for simple tasks, short answers. Limited reasoning.
- **Medium models (7-8B):** Adequate for most everyday tasks. Occasional hallucinations.
- **Large models (32B+):** Good quality, but require 32+ GB RAM and slow loading.
- **Catalan:** Salamandra models (BSC/AINA) are best for Catalan. Other models have limited Catalan support.

## Multimodal models (VLM)

The MLX backend supports vision models (image + text) via `mlx-vlm 0.4.4`. Detected architectures: Qwen2-VL, Qwen2.5-VL, Qwen3-VL, Llava (all), Gemma-3/4, PaliGemma, InternVL, MiniCPMV, Idefics2/3, Mllama and more. The detector also activates on `vision_config` in `config.json` or on keys `vision_tower`/`mm_projector` in `model.safetensors.index.json` (covers new architectures).

Current limitations:
- **Omni models with video (Qwen3.5 MoE, Qwen3-Omni, Kimi-VL, …):** Require `PyTorch` and `torchvision` for their `VideoProcessor`, which server-nexe **does not bundle** in the venv for size (~2 GB added to the DMG). They will load via `mlx-vlm.load()` but fail at the processor preparation stage. **Workaround:** use an image-only VLM (Gemma-4, Qwen2.5-VL, Llava) as default.
- **Recommended default:** `gemma-4-e4b-4bit` (4.9 GB) or `gemma-4-31b-8bit` (20 GB). Image only, no torch dependencies.
- **Audio/speech:** Not supported. Models like Qwen3-Omni, Kimi-VL or DeepSeek-VL-V2 have an audio branch in `mlx-vlm` but the server-nexe pipeline does not expose it yet.
- **Native video:** Not supported (see omni models).
- **VLM response streaming:** The current path (`_generate_vlm`) does not support token-by-token streaming; it returns the full text at the end. Text-only does have streaming.

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
| Vision/multimodal | Implemented since v0.9.7 (Ollama, MLX, llama.cpp, Web UI) |

## Performance

- **Single instance:** One server process, not clustered.
- **Concurrency:** Limited by model inference (one request at a time per backend).
- **Startup time:** 5-15 seconds (Qdrant + module loading + knowledge ingestion on first run).
- **Model loading:** 10-60 seconds depending on model size and backend.
- **RAM consumption:** Model + Qdrant + Python = significant. 8GB RAM is tight for 7B models.
- **Disk:** Models (1-40 GB) + Qdrant vectors + logs. Estimate 10-50 GB total.

## Security

- **Prompt injection:** Local models may follow injected instructions. Sanitizer catches common patterns (47 jailbreak patterns, 6 injection detectors with Unicode normalization) but not all.
- **No TLS by default:** HTTP on localhost. Use reverse proxy for HTTPS.
- **Single-user:** No multi-user isolation. One API key = full access.
- **AI audits, not external audits:** Security has been reviewed by autonomous AI sessions, not by third-party security firms. This is thorough but not exhaustive.
- **Ollama keep_alive bug:** keep_alive:0 doesn't always release VRAM (known Ollama issue).

## Encryption Caveats

- **Default `auto`:** Encryption at rest activates automatically if `sqlcipher3` is available. Can be forced with `NEXE_ENCRYPTION_ENABLED=true` or disabled with `false`.
- **New feature:** Added in v0.9.0, available since v0.9.7. Tested (68 tests, 0 failures) but not yet battle-tested in production with real users.
- **Key management:** Master key stored in OS Keyring, env var, or file. If the key is lost, encrypted data cannot be recovered.
- **SQLCipher dependency:** Requires `sqlcipher3` package. Falls back to plaintext SQLite with a warning if not installed.
- **Migration:** Migrating large datasets (many memories, many sessions) can take time. Backup before migrating.

## Functional Gaps

- **No multi-device sync** — Local only, no cloud sync.
- **No model fine-tuning** — Cannot train or fine-tune models.
- **No OCR** — Cannot extract text from images or scanned PDFs.
- **No multi-user** — Single API key, no user accounts.
- **No real-time collaboration** — Single-user, single-session design.
- **No scheduled tasks** — No cron-like automation built-in.
- **Web UI is functional but basic** — Not a full-featured chat app. Working streaming, uploads, memory, i18n, but no message editing, no branching, no export.

## Project Reality

- **One developer** — Built by a single person with AI-assisted development and auditing.
- **One real user** — Only the developer has used it so far. No third-party feedback or multi-user testing.
- **Not enterprise-grade** — It's a personal open-source project, not a product with SLA or support guarantees.
- **Active development** — Things change. APIs may evolve. Documentation may lag behind code.

## What server-nexe is NOT

- NOT a replacement for ChatGPT, Claude, or cloud AI services
- NOT an enterprise product with SLA
- NOT a multi-user platform
- NOT guaranteed bug-free (it's a personal open-source project)
- NOT npm nexe (Node.js compiler — completely unrelated)
