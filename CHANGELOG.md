# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Refactored

- **`personality/` — 13 complexity findings eliminats** (lizard CCN+params+file_too_long). Refactor pur sense canvi de comportament: (A) `RouterContext` dataclass compacta `_attach_named_router`/`_attach_get_router` (6→2, 5→2 PARAM); (B) `LifecycleConfig` per `ModuleLifecycleManager.__init__` (7→2 PARAM), `_finalize_load_success` elimina param `module_info` + afegeix guard `KeyError`; (C) `SystemLifecycleConfig`/`DiscoveryConfig` per constructors `SystemLifecycleManager`/`ModuleDiscovery` (6→2, 5→2 PARAM); (D) `SecurityCheckContext` per `_check_plugin_security`, `RouteRegistration` per `register_module_routes`, `_save_integration_info` inline dict (6→3 PARAM); (E) `_error_rate`/`_avg_api_calls` extrets de `get_performance_summary` (CCN 11→5), `_check_single_path` extret de `_validate_paths` (CCN 10→4); (F) `PluginLoaderMixin` split — `module_manager.py` 687L→407L, mixin a nou `plugin_loader.py`. Nous fitxers: `personality/module_manager/types.py`, `personality/integration/types.py`, `personality/module_manager/plugin_loader.py`. 3 commits, 6113 tests, 0 regressions.

### Fixed

- **`core/config.py`: deep-merge `personality/server.toml` + root `server.toml`** (Fix B9). `load_config()` ara usa pattern "default + override" en comptes de "first wins": carrega `personality/server.toml` com a BASE i deep-mergia root `server.toml` com a OVERRIDE. Prioritat: `DEFAULT < personality/server.toml < root server.toml < ENV vars`. Corregeix que un `server.toml` parcial a l'arrel silenciava completament `personality/server.toml`, deixant 9 tests 404. Tests: `tests/test_config_merge.py` (6 escenaris TDD) + `tests/test_session_manager_robustness.py` (6 casos defensius B4).

### Added

- **Qwen3-VL models added to MLX catalog** (`installer/installer_catalog_data.py`). Three native vision-language models from the Qwen3-VL family are now offered as MLX options, confirmed available at `mlx-community` (sizes verified via HF Warehouse API 2026-05-06): `qwen3_vl_4b` (4B, 3.1 GB, tier small — `mlx-community/Qwen3-VL-4B-Instruct-4bit`), `qwen3_vl_8b` (8B, 5.8 GB, tier medium — `mlx-community/Qwen3-VL-8B-Instruct-4bit`), `qwen3_vl_30b_a3b` (30B-A3B MoE, 18.3 GB, tier xlarge — `mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit`). All three use `Qwen3VLForConditionalGeneration` architecture, already registered in `_VLM_ARCHITECTURES` and now covered by an explicit regression test. Ollama tags confirmed available: `qwen3-vl:4b`, `qwen3-vl:8b`, `qwen3-vl:30b-a3b` (verified 2026-05-06). SHA256 pins left `None` (legacy-mode, C19 backlog). Requires `torch`/`torchvision` wheels already bundled since TODO 1.3. Sprint v1.0.4-beta Fase 2.

- **C19 SHA256 pins poblats — 17/32 entrades verificades** (`installer/installer_catalog_data.py`). Primera població real de `MODEL_WEIGHT_SHA256` (backlog C19, v1.0.3-beta tots `None`). Mètode: MLX via `sha256_of_dir` sobre models a Wintermute; Ollama via digest config del manifest local `~/.ollama/models/manifests/`; GGUF via `shasum -a 256`. Pins verificats 2026-05-06: 6 MLX (gemma-4-e4b, gemma-3-12b, gemma-3-27b, gemma-4-31b, Qwen3-14B, gpt-oss-20b), 9 Ollama (gemma3:4b, qwen3.5:4b, qwen3:4b, gemma4:e4b, salamandra-7b, qwen3.5:9b, qwen3:14b, qwen3.5:27b, gemma4:31b, qwen3.5:35b-a3b), 1 GGUF (salamandra-7b-instruct-Q4_K_M). `None` restants (15): models Qwen3-VL i GGUF grans no descarregats localment — pins es poblaran quan s'instal·lin. Sprint v1.0.4-beta C19.

- **B4 recall@N A/B regression — implementació real** (`tests/test_embeddings_recall_ab.py`). Substitueix l'esquelet skip-only per una implementació completa i agnòstica de Qdrant. `InMemoryVectorStore` (numpy cosine similarity, zero dependència `qdrant_client`) implementa el protocol `VectorStore`. Dataset golden inline de 10 parells (query → doc rellevant, temàtica Nexe/IA en català). 5 tests: `recall@5 ≥ 0.50`, `recall@10 ≥ 0.70`, `top-1 hit rate ≥ 3/10`, search ordering, delete. Skip automàtic si `fastembed` no disponible al cache. Sprint v1.0.4-beta Fase 3.

- **C23 resolt: brackets CJK i matemàtics a `_filter_rag_injection`** (`core/endpoints/chat_sanitization.py`). NFKC no normalitza `「」 『』 〔〕 ⟦⟧` a ASCII — un document indexat podia embedre `「MEM_DELETE: x」` esquivant el filtre RAG. Fix: `_NON_NFKC_BRACKET_MAP` (str.maketrans, 8 parells) aplicat just after NFKC, mapejant tots els brackets a `[` / `]` ASCII abans del loop de regex. 4 nous tests a `tests/test_chat_sanitization_unicode.py` (CJK corner, CJK white, tortoise shell, mathematical). `test_docs_honest_claims` actualitzat per verificar la nova taula en comptes del gap. Sprint v1.0.4-beta Fase 3.

- **Test coverage `Qwen3VLForConditionalGeneration`** (`plugins/mlx_module/tests/test_multimodal.py`). `_VLM_ARCHITECTURES` already listed `Qwen3VLForConditionalGeneration` but had no explicit test case. Added `test_vlm_qwen3_vl_returns_true` to `TestDetectVlmCapability`, closing the gap between the architecture safelist and the regression suite. Suite: 22 passed (was 21). Sprint v1.0.4-beta Fase 2.

- **PyTorch + torchvision bundled wheels for VL/multimodal model support** (`installer/build-wheels-bundle.sh`, new `installer/wheels-checksums.txt`). Adds `torch==2.11.0` and `torchvision==0.26.0` (cp312, `macosx_11_0_arm64` — wheels publish min macOS 11.0, fully compat upward with macOS 14+ hosts) to `InstallNexe.app/Contents/Resources/wheels/`. Required at runtime by Qwen3 VL and other multimodal models — `Qwen3VLVideoProcessor` needs torchvision for image preprocessing. Not a direct import in the server-nexe codebase; an indirect engine dep that `mlx-vlm` (already in the bundle) pulls in when the user selects a VL model. Bundle size delta ~92 MB net (240 MB → 329 MB) — far below the 600 MB feared in the v1.0.4-beta master plan, because macOS arm64 PyTorch wheels do NOT ship CUDA/cuDNN libs (Linux-only `Requires-Dist`); MPS support is part of the binary core without inflating the wheel. **Supply-chain hardening (B8 pattern, same threat model as the Ollama bundle pin in r4):** `installer/wheels-checksums.txt` pins SHA256 of both wheels in `shasum -c`-compatible format. The build script's new Step 4b runs a manual loop with the local `_sha256()` helper (copied from `build-embedding-bundle.sh`) and aborts with distinct exit codes — `exit 6` (checksums file missing — refuses to ship a build with the supply-chain check disabled), `exit 7` (pinned wheel listed but absent from the bundle), `exit 8` (SHA256 mismatch with diagnostic output suggesting MITM / DNS hijack / CDN cache divergence as causes), `exit 9` (path-traversal in pinned filename, defense-in-depth), `exit 10` (zero verifications performed — empty / comments-only file is not a valid configuration). The verified-count counter and `while IFS= read -r line || [ -n "$line" ]; do` guard prevent silent bypasses from a truncated or trailing-newline-stripped checksums file. Initial pins captured 2026-05-01 cross-validated three independent ways: (1) `pip download --only-binary=:all:` then `sha256sum` of the local .whl; (2) PyPI JSON Warehouse API at `pypi.org/pypi/<pkg>/<ver>/json` reading `urls[].digests.sha256`; (3) `pip hash --algorithm sha256` of the local wheel — all three SHAs identical for both wheels (note: PyTorch does not publish macOS arm64 wheels on the GitHub releases page, only source, so a github.com cross-source as we use for Ollama is not available; the PyPI JSON API + local sha256sum + pip hash recomputation are independent enough channels for this threat model). Threshold sanity adjusted: `lt 100 / gt 500` → `lt 250 / gt 600` to reflect the new ~330 MB baseline. Runtime smoke test verified: `import torch, torchvision` works against an offline `pip install --no-index --find-links` from the bundle wheels (after the `sign-wheels-bundle.sh` re-sign step that hardened-runtime library validation requires), and `torch.backends.mps.is_available()` returns `True` on Apple Silicon. 11 test additions: 3 in `tests/test_installer_build_wheels.py` (ENGINES contain torch/torchvision pinned exactly, EXPECTED_SUBSTRINGS includes `torch-`/`torchvision-`, Step 4b is wired into executable code) and 8 in new `tests/test_installer_wheels_checksum.py` (file format, exactly two pins of the right packages, valid hex SHA, filename pattern, two-space separator, `shasum -c` rejects random-bytes sandbox, helper is defined and called outside comments, no silencing patterns + adversarial sandbox suite that extracts the real Step 4b block from the build script and runs it against tampered/missing/empty/path-traversal/legitimate inputs to exercise every exit branch in the actual code path, not a parallel reimplementation). Sprint v1.0.4-beta TODO 1.3.

### Security (BREAKING)

- **AES-GCM AAD binding for encrypted sessions** (`core/crypto/provider.py`, `plugins/web_ui_module/core/session_manager.py`). Encrypted session files (`storage/sessions/*.enc`) now use the session ID (filename stem) as Additional Authenticated Data when encrypting and decrypting. This prevents swap attacks where an attacker with disk access could rename `A.enc` ↔ `B.enc` undetected — pre-fix, AES-GCM was called with `aad=None` so the ciphertext was not bound to its filename. Post-fix, any AAD mismatch (rename, tampering, or pre-1.0.3-beta sessions written without AAD) raises `cryptography.exceptions.InvalidTag`, is caught at load time, increments `SessionManager._corrupted_sessions_count`, and the file is logged at ERROR level (`MEK mismatch, AAD mismatch, or file corruption`). A defense-in-depth sanity check also rejects loaded sessions whose payload `id` differs from the filename stem. `CryptoProvider.encrypt`/`decrypt` accept the new `aad: bytes | None = None` keyword (default `None`) so non-session call-sites (text_store, persistence, memory_api, CLI) keep working unchanged. **Breaking:** sessions encrypted by versions <1.0.3-beta cannot be decrypted by 1.0.3-beta+ (AAD format mismatch). Affected users will need to re-login; their old encrypted session files will fail with `InvalidTag` and will be counted as corrupted. No automated migration is provided — to clean up: `rm storage/sessions/*.enc` before upgrading, or accept that pre-1.0.3-beta sessions are unrecoverable. Tests at `tests/test_crypto_aad.py` (5 cases: roundtrip with AAD, swap rejected, wrong AAD rejected, backward compat aad=None, integration swap-on-disk). Auditoria r4 B4.

### Security

- **Ollama bundle download SHA256 pinning** (`installer/build-ollama-bundle.sh`, new `installer/ollama-checksums.txt`). The DMG build downloaded `Ollama-darwin.zip` (~156 MB) from `https://ollama.com/download/Ollama-darwin.zip` with `curl -fSL` and validated only file size (≥50 MB) and zip integrity (`unzip -t`) — neither catches substitution of the archive with a same-shape backdoored zip when the build machine's network is compromised (proxy MITM, DNS hijack, malicious Wi-Fi). The result would be a Trojanized Ollama binary inside the DMG distributed to every user. New `installer/ollama-checksums.txt` pins the SHA256 of the upstream zip in standard `shasum -c` format; the build script now runs `shasum -a 256 -c` post-download (after the existing size and `unzip -t` checks, which are kept untouched) and aborts with `exit 4` on mismatch. The mismatched zip is **preserved on disk for forensic inspection** (no automatic `rm -f` on the SHA path — only the legacy size/integrity failures still clean up). Initial pin captured 2026-05-01 for Ollama v0.22.0 cross-validated three ways: (1) download via `ollama.com` CDN (latest redirect), (2) download via `github.com/ollama/ollama/releases/download/v0.22.0/Ollama-darwin.zip` (version-pinned URL), (3) compared against the official `sha256sum.txt` published by the Ollama maintainers at the same release — all three SHAs and a binary diff agreed (`a410e2f7…36b278` — full digest in `installer/ollama-checksums.txt` — 164167759 bytes). Update procedure documented inline in the checksums file: any pin bump requires re-validating from all three sources before commit, and on divergence the procedure mandates STOP + escalate (possible MITM or CDN cache divergence). 4 regression tests in `tests/test_installer_build_ollama_checksum.py` cover (a) checksums file format and 64-char hex SHA, (b) `shasum -c` correctly rejects a corrupt zip in a sandbox without any network download, (c) the build script actually invokes `shasum -a 256 -c` and contains the `exit 4` branch, and (d) no silencing patterns (`|| true`, `set +e`, `2>/dev/null` on shasum, `NEXE_SKIP_CHECKSUM` env var) are present. Auditoria r4 B8.
- **`_filter_rag_injection` aplica NFKC normalize abans del regex match** (`core/endpoints/chat_sanitization.py`). El filtre de patterns de prompt injection a contingut indexat (upload/ingest path) era ASCII-only: payloads fullwidth `［MEM_DELETE: x］` o `［CONTEXT］` passaven el filtre i s'indexaven al RAG, esdevenint vector d'envenament cross-session. Fix defense-in-depth: `unicodedata.normalize("NFKC", text)` abans del loop de regex (neutralitza fullwidth ［］ → []). Garanteix també que les substitucions ASCII-only `[/CONTEXT]` → `[/CONTEXT_ESCAPED]` i `[CONTEXT` → `[CONTEXT_ESCAPED` (línies 99-100) capten variants fullwidth post-normalize (finding 3 DeepSeek revalidació r4). **Breaking-change menor:** la funció ara retorna text NFKC-normalitzat (RAG indexing és pipeline one-way, acceptable); documentat al docstring. **Gap conegut (DOC-01 r4):** mathematical brackets `⟦⟧` (U+27E6/U+27E7) NO es normalitzen via NFKC — el cobreix B3 (`strip_memory_tags`) via regex extension explícita. CJK brackets `「」 『』 〔〕` tampoc es normalitzen via NFKC (tracked C23 v1.0.4). Tests nous a `tests/test_chat_sanitization_unicode.py` (15 casos: fullwidth + mathematical + mixed + INST + idempotent + finding 3 CONTEXT/escape + gap CJK documentat). Auditoria r4 B6.
- **`strip_memory_tags` neutralitza variants Unicode de brackets** (`plugins/security/core/input_sanitizers.py`). El regex original només cobria `[` ASCII (U+005B), permetent bypass amb fullwidth `［MEM_SAVE］` (U+FF3B/U+FF3D), CJK `「」 『』 〔〕 ｢｣` i mathematical `⟦⟧`. Fix defense-in-depth: `unicodedata.normalize("NFKC", text)` abans del regex match (neutralitza fullwidth + halfwidth + lletres fullwidth + espais fullwidth) + regex extension explícita per brackets CJK i mathematical (no NFKC-normalitzables). **Breaking-change menor:** la funció ara retorna text NFKC-normalitzat; documentat al docstring. Tests nous a `tests/test_input_sanitizers_unicode.py` (17 casos: parametrize fullwidth + CJK + preserva normal + anchor + idempotent + homoglyph negatiu). Auditoria r4 B3.

### Fixed

- **Plists `Nexe.app` i `NexeTray.app` desincronitzats** (`Nexe.app/Contents/Info.plist`, `installer/NexeTray.app/Contents/Info.plist`). Els bundles anaven amb `1.0.2-beta` mentre `pyproject.toml` ja era `1.0.3-beta`, fent fallar `core/tests/test_plist_versions.py::test_synced_plists_match_pyproject`. Resolt amb `python -m installer.sync_plist_versions` (eina ja existent al projecte). Auditoria r1 P0.2 (DeepSeek V3 / Turing).

### Changed

- **Test SQLi al chat: contracte ajustat al disseny** (`tests/test_chat_v1_validation.py`). `test_sql_injection_in_message_content_rejected` renombrat a `test_sql_injection_in_chat_passes_through_to_llm`: en `context="chat"` el sanitizer delega `check_sql` al LLM (Ollama), perquè el pipeline no toca cap SQL DB (RAG = Qdrant vector DB). Discutir "UNION SELECT" és tech talk legítim. El rebuig estricte de SQLi es manté a `context="param"` (model, engine), cobert per `test_sql_injection_in_model_field_rejected`. Cap canvi a `plugins/security/core/input_sanitizers.py` — la decisió `check_sql=False` en chat ja era intencionada i documentada (línies 153-156, 164-169). Auditoria r1 P0.1 (DeepSeek V3 / Turing).
- **Test `nexe stop` accepta sortida en català o anglès** (`tests/test_cli_stop_pid.py`). `test_stop_no_services_running` només verificava l'output anglès "No Nexe services are running"; quan `NEXE_LANG=ca` (per defecte al Mac de dev) el CLI imprimeix "Cap servei Nexe actiu" i el test fallava. Assert ampliat amb `or` per cobrir ambdós idiomes. Auditoria r1 P1 (DeepSeek V3 / Turing).

## [1.0.4-beta] — 2026-05-14

Sprint after 1.0.3-beta with 389 commits focused on security hardening, MLX
engine reliability, vision model support (Qwen3-VL family), observability,
and a comprehensive type-safety + complexity reduction pass.

### Security

- **NFKC unicode normalization** on RAG injection filter and memory tag
  stripper — defends against unicode-confusable bypass of `[MEM_SAVE]` and
  injection patterns.
- **API key now required on info/health endpoints** — previously some
  metadata endpoints leaked version/build info without auth.
- **Rate-limit on `/v1/memory/search`** (60/min) — prevents search
  enumeration.
- **Web UI graceful degradation when security plugin missing** — clean 503
  instead of stack trace.
- **SSE error message sanitization** — stream errors no longer leak
  internal paths; non-streaming completion content also sanitized.
- **AES-GCM AAD bound to session_id** — prevents session swap attacks on
  encrypted `.enc` files.
- **`chmod 600` on session `.enc` writes** + refuse plaintext `.json`
  sessions in production when crypto missing.
- **Ollama bundle SHA256 pinning** — first install verifies the bundle hash
  before extraction.
- **Stop logging partial API keys** in auth failure logs.

### Added

- **SHA256 pinning of installer downloads** — integrity check infrastructure
  for MLX snapshots, GGUF files, and Ollama manifests. DMG-bundled fastembed
  model gets a manifest with three digests. Catalog pins remain `None` at
  this release; pin population is roadmapped for the next sprint.
- **Live test suite** (`tests/test_live/`, `dev-tools/run_live.py`) — 53
  tests across all backends (Ollama, MLX, llama.cpp), MEM_SAVE, prompt
  injection, fail-closed, input validation, rate limit. Auto-starts the
  server if down.
- **Qwen3-VL family in MLX catalog** — 4B / 8B / 30B-A3B with vision
  capability detection.
- **PyTorch + torchvision bundled in installer** — vision/multimodal models
  run on first install without manual setup.
- **MLX hardware tier detection** (`low`/`mid`/`high`/`ultra`) for adaptive
  defaults per Apple Silicon variant.
- **Rotating `rag.log`** — daily rotation, 14-day retention.
- **Recall@N evaluation** (real, not synthetic) + bracket support for CJK
  and mathematical brackets.
- **Web UI thinking-state polish** — Mexican-wave per-letter animation,
  orange NEXE avatar with traffic-light cycle, placeholder border pulse,
  MODEL_LOADING banner guaranteed visible ≥ 700 ms.
- **Shared engine helpers** (`_common.py`, `_streaming.py`) — deduplicated
  Ollama/MLX/llama.cpp request and stream code.
- **`THREAT_MODEL.md`** plus per-language versions in `knowledge/`.
- **138 new docstrings** + `interrogate` configured to enforce coverage.

### Fixed

- **MLX cancel propagation** — HTTP client cancel now reaches the MLX
  streaming loop (no more zombie generation after disconnect).
- **MLX stream affinity** — single-worker executor pinning preserves
  per-thread default_stream, fixing intermittent stream corruption.
- **Qwen3.5 thinking on MLX** — directive prepended with critical tags
  (append failed for prompt-length reasons), synthetic `<think>` opener
  re-emitted when the chat template injects it, `thinking_enabled`
  forwarded through the VLM branch and `apply_chat_template`.
- **VL model loading without PyTorch** — clear `MissingDependencyError`,
  auto-fallback to text-only mode, auto-disable stale safetensors index
  pointing at non-existent shards.
- **RAG recall: `MemoryAPI not available` on every chat request** — broken
  singleton (assigned before `initialize()`), permanent failure flag (no
  retry), and silent debug fallback all fixed. New 60-second retry window.
- **`GCDaemon` was never invoked** — score-based episodic pruning, budget
  enforcement, and tombstones existed but were dead code. Now wired into
  `DreamingCycle.run_cycle()` per active user.
- **`DreamingCycle` ran without an embedder** — `_sync_vector_index` was a
  no-op in production; episodic memories never reached the vector store.
- **Streaming**: `data: [DONE]` always emitted after post-processing (some
  clients hung waiting for the marker).
- **Installer**: int8 quantized ONNX variant for the embedding bundle
  (fp16 was incompatible with modern ONNX Runtime); Ollama bundle pinned to
  v0.22.1.
- **`cancel_event` scoped to MLX only** — Ollama and llama.cpp cancel
  natively via async transport.
- **Web UI**: 21 fixes including footer thinking-badge alignment, image
  MIME persisted in sessions, `NEXE_LLAMA_CPP_MODEL` honored in backend
  scan, vision icon for MLX Qwen3.5.
- **Dependency CVEs** patched: `pypdf`, `python-dotenv`, `python-multipart`,
  `filelock` (9 advisories from `osv-scanner`).

### Changed

- **Documentation honesty pass** — `README.md`, `SECURITY.md`,
  `IDENTITY.md` aligned with actual behavior on telemetry ("scoped to
  runtime"), encryption defaults (`auto` is not fail-closed), CSP
  (`style-src 'unsafe-inline'` is allowed for Web UI), and "agnostic"
  scope (backend choice only, not platform).
- **297 test files migrated** from packages to `tests/` root for unified
  discovery.
- **Multiple complexity reductions** across the chat handler, response
  generator, web UI helpers, and runner — facade helpers extracted, no
  behavior change.
- **Comprehensive type-safety pass** across plugins, memory, and core.

### Removed

- Internal one-shot scripts and personal tooling (kept locally via
  `git rm --cached`); all four added to `.gitignore`.
- Personal path references from `COMMANDS.md` and four test/docs files
  (anonymized).
- Stale `type: ignore` annotations and orphan whitelist entries in lint
  configs.

## [1.0.3-beta] — 2026-04-24

### Security

- **`RemovedDirectRoutesGuard` middleware** (`core/middleware.py`, `core/loader/manifest_base.py`, `core/loader/protocol.py`). New `manifest.toml:removed_direct_routes` field is enforced at request time (403 with `direct_plugin_endpoint_disabled` error code) and at plugin load time (`PluginLoadError` on collision between declared-removed and registered routes). Applied to `/mlx/chat`, `/llama-cpp/chat`, `/ollama/api/chat`. Guard runs before SlowAPI, CORS, and route dispatch — blocked requests consume no rate-limit budget and return no CORS headers. `protected_routes` is intentionally unchanged (ambiguous semantics across plugins, scope-separated for a future follow-up). 14 tests in `tests/test_removed_direct_routes_guard.py` (includes 2 Ollama regression tests verifying `/api/pull` and `/api/models/{name}` DELETE are unaffected). Closes DoD audit §2.11 follow-up.
- **SHA256 pinning — post-audit hardening** (`core/integrity/hashing.py::sha256_of_dir`, `installer/installer_setup_models.py::_download_gguf_model`). Follow-up review of the F4.1 landing found two polish-level gaps. (1) `_download_gguf_model`'s broad `except Exception` branch caught `DownloadIntegrityError` in interactive mode and downgraded it into "here are manual commands to finish the download", which defeats the integrity check on the path the user actually clicks through. A dedicated `except DownloadIntegrityError: raise` now propagates the error unconditionally (headless already did the right thing via the inner `if headless: raise`). (2) `sha256_of_dir` followed symlinks without bounding them to the root, so a tampered snapshot could fold attacker-controlled bytes (`/etc/passwd` or any file whose SHA256 is known) into the hash. Policy aligned with `verify_embedding_bundle._find_bundle_file`: resolve each entry, skip + log a WARNING when the target escapes the root. Regression tests added for both.
- **SHA256 pinning of downloaded model weights** (new `core/integrity/hashing.py`, `installer/download_verify.py`, `installer/installer_catalog_data.py::MODEL_WEIGHT_SHA256`, `installer/installer_setup_models.py`, `installer/installer_setup_env.py::_seed_fastembed_cache`, `installer/build-embedding-bundle.sh`). Addresses DoD audit finding `DoD-AUD-SX-0423 §2.7`: the installer previously trusted every weight returned by `huggingface_hub.snapshot_download`, `ollama pull` and `curl`-downloaded GGUF files without any integrity check. After F4.1, every first-boot download is hashed and compared against the catalog pin — a mismatch aborts the install with a `DownloadIntegrityError` that preserves the artefact on disk and emits backend-specific retry instructions. Three surfaces are covered: Hugging Face MLX snapshot directories (`sha256_of_dir`, dotfile-filtered to skip HF cache noise), GGUF single files (`sha256_of_file`), and Ollama manifest digests (`ollama show --json`, tolerates both `details.digest` and legacy top-level `digest`, stripping the `sha256:` prefix). The DMG-bundled fastembed model is now accompanied by an `embeddings.manifest.json` written by `build-embedding-bundle.sh` Step 6 (three SHA256 digests: `model*.onnx`, `tokenizer.json`, `config.json`); `verify_embedding_bundle` re-hashes the files at copy time and refuses symlink targets that escape the bundle root. Legacy-friendly: catalog entries with `None` pins emit a visible `⚠️ not pinned` warning instead of aborting, so v1.0.2-beta installs keep working while the catalog is filled in over time. **Status at v1.0.3-beta: ALL 26 catalog entries (8 MLX + 14 Ollama + 4 GGUF) ship with `None` pins** — the integrity infrastructure is in place but no model is yet pinned. Pin population is roadmapped for v1.0.4-beta (backlog item C19: `scripts/populate_sha256_pins.py` will compute `sha256_of_dir` / `sha256_of_file` / `ollama show --json` digests once per model and commit the results). Until then every install logs `Integrity: no SHA256 pin for <engine>:<model> — accepted in legacy mode` for each downloaded weight (visible at `WARNING` level). Coverage ≥90 % on all new code (`core/integrity/hashing.py`: 100 %, `installer/download_verify.py`: 95 %). Installer runtime footprint: no new dependencies, `hashlib` only. The `Ollama.app` install/bundle helpers moved out of `installer_setup_models.py` into a new `installer_ollama_install.py` so the download module stays under the 500-line threshold after the F4.1 additions; `ensure_ollama_installed` is re-exported from the old module for backward compatibility with `install_headless.py` / `install.py`.
- **Plaintext-mode startup banner is now loud** (`core/crypto/__init__.py:format_plaintext_startup_banner`, `core/lifespan.py`). When the server starts with `NEXE_ENCRYPTION_ENABLED=auto` and `sqlcipher3` is not installed, the previous single-line `WARNING` ("Encryption not available…") got buried in verbose startup logs. Replaced with a multi-line banner that states explicitly that encryption at rest is DISABLED, which data categories are affected (memories, sessions, RAG documents), and the exact commands to either require encryption (`pip install sqlcipher3-binary && export NEXE_ENCRYPTION_ENABLED=true`) or silence the notice for dev/CI (`NEXE_ENCRYPTION_ENABLED=false`). Default behaviour is unchanged — this is a visibility fix only. 5 tests in `tests/test_plaintext_startup_banner.py`.
- **Bounded recursion in `detect_nosql_injection`** (`plugins/security/core/injection_detectors.py`). The detector recursed over dict/list inputs with no depth cap; a deeply-nested JSON payload (≥1000 levels) raised a `RecursionError` from Python's C stack and bubbled up as HTTP 500 — a trivial DoS on any endpoint that validated user dicts. New module constant `MAX_NOSQL_DEPTH=100`; inputs nested deeper are flagged suspicious (return `True`) instead of recursing further. Signature stays backward-compatible (`_depth` is an internal-only keyword). 9 regression tests in `plugins/security/tests/test_detect_nosql_depth.py`.
- **chmod failure on master-key parent directory now logs a WARNING** (`core/crypto/keys.py:_try_file_set`). Previously wrapped in `try/except: pass`, so a failure to `chmod 0o700` the `~/.nexe/` directory (noexec mounts, ACL-restricted filesystems, sandboxed runtimes) left it with broader permissions and no trace in logs. The key file itself is still created 0o600 via `os.open`, but operators now see a `WARNING` when the enclosing dir can't be tightened. 2 tests in `tests/test_crypto_keys_chmod_warning.py`.
- **SQL detector now skipped in `context="chat"`** (`plugins/security/core/input_sanitizers.py:validate_string_input`). `command`, `ldap`, and `path_traversal` detectors were already disabled in chat context to prevent false positives on free-form text ("the admin ran..." triggered no op, but "UNION SELECT * FROM logs" as a legitimate tech-talk prompt returned HTTP 400). SQL was the remaining inconsistency. XSS stays active (rendered chat output can reach the browser). `context="param"` and `context="path"` behaviour unchanged. 8 tests in `plugins/security/tests/test_validate_string_chat_context.py`.
- **RAG recall: `MemoryAPI not available` on every `/ui/chat` request** (`memory/memory/api/v1.py`, `plugins/web_ui_module/core/memory_helper.py`). Every `/ui/chat` request produced `RAG recall: MemoryAPI not available (init failed or not ready)` and the AI had no access to user memories. Root cause: three bugs working in concert. (1) **Broken singleton** — `v1.get_memory_api()` assigned `_memory_api = MemoryAPI()` *before* calling `initialize()`. A failed `initialize()` (e.g., `FASTEMBED_CACHE_PATH` not set in dev, model not found) left the global pointing to an uninitialized object. The next caller received this broken object without an exception, reached `collection_exists()`, raised `RuntimeError("MemoryAPI not initialized")`, and set `_memory_api_init_failed = True`. Fixed by assigning the global *after* successful `initialize()` via a local variable. (2) **Permanent failure flag** — `_memory_api_init_failed = True` was never reset, permanently silencing RAG for the process lifetime after a single transient failure. Added `_memory_api_last_failure_ts` and a 60-second retry interval (`_MEMORY_API_RETRY_INTERVAL_S`); flag reset is performed inside the `_memory_init_lock` to avoid a race between concurrent callers both seeing `elapsed ≥ 60s`. (3) **Silent fallback** — the `except Exception` that caught `v1.get_memory_api()` failures used `logger.debug`, making initialization errors invisible in production logs. Promoted to `logger.warning`. Also fixed a pre-existing `f-string` log call to `%s`-style args. 19 new tests in `tests/test_memory_helper_recall.py` (unit: F1 warning, Bug A v1 singleton, F3 retry) and `tests/test_rag_recall_e2e.py` (E2E: 3-turn conversation storing "el gos de Jordi es diu Ruf" and retrieving it via vector search). See diari 2026-04-24.

### Changed

- **Documentation honesty pass** (`README.md`, `README-ca.md`, `README-es.md`, `SECURITY.md`, `knowledge/{ca,en,es}/IDENTITY.md`). Aligning user-visible promises with what the code actually does:
  - "No telemetry, no external calls, no cloud dependency" acotat a runtime. First-run still downloads the chosen LLM and the `fastembed` embedding model from Hugging Face / Ollama; after that, zero data leaves the device.
  - "Encryption at rest, fail-closed" acotat. Default `NEXE_ENCRYPTION_ENABLED=auto` uses SQLCipher when available, else plaintext with a startup `WARNING`. Strict fail-closed only when the operator sets `NEXE_ENCRYPTION_ENABLED=true` — now spelled out everywhere the feature is advertised.
  - CSP policy documented precisely: `script-src 'self'` without `unsafe-inline`, but `style-src 'self' 'unsafe-inline'` is allowed for Web UI inline styles (documented trade-off, not an oversight). Earlier doc phrasing "no `unsafe-inline`" implied the stricter variant.
  - "Agnostic" scoped to backend choice (MLX / llama.cpp / Ollama). Platform support remains macOS 14+ Apple Silicon, which the Platform Support table already reflects.

### Fixed

- **Memory: `GCDaemon` was never invoked** (`memory/memory/workers/dreaming_cycle.py`, new `memory/memory/workers/gc_daemon.run_gc_for_active_users`). `GCDaemon` (score-based episodic pruning + budget enforcement + tombstone creation) existed and was exported, but nothing on the server ever called it — `DreamingCycle._gc_lightweight` only expired TTL rows. Integrated a default `GCDaemon` instance inside `DreamingCycle`; `run_cycle()` now runs it for every active user at the end of each cycle. No thread offload because `SQLiteStore._connect()` is not thread-safe (would hit `ProgrammingError`), but the work is light enough to run synchronously between `asyncio.sleep(0)` yields. Throttleable via `_gc_heavy_every` (defaults to every cycle).
- **Memory: `DreamingCycle` was running without an embedder, so `_sync_vector_index` was a no-op in production** (`core/lifespan_modules.py`). `lifespan_modules.start_memory_service_v1` constructed `DreamingCycle(store=..., vector_index=...)` without passing `embedder=`. `_sync_vector_index` returned early if `self._embedder is None`, so every episodic entry written via `MemoryService` stayed in SQLite with `vector_synced=0` and never reached Qdrant — semantic search over episodic memories returned nothing from the background pipeline. Now `SimpleEmbedder(DEFAULT_EMBEDDING_MODEL)` is loaded via `asyncio.to_thread` (first-use ONNX init can block 5-30 s) and passed explicitly; failure to load is non-fatal and only skips vector sync.
- **Tests: 18 regression fails in `test_manifest_coverage.py` after the session manager late-init fix** (`5abd171`). `test_manifest.py` got the new `_ensure_module_initialized` autouse fixture but the coverage-focused companion did not, so every `TestClient` request in that file raised `_SessionManagerProxy: accessed before initialize()`. Applied the same fixture pattern (+ moved `disable_rate_limiter` teardown to restore previous state instead of hard-coding `True`).
- **Tests: `test_memory_delete.test_delete_returns_deleted_facts` asserted `deleted == 2`** against a design that deletes only the top-scored match per collection (`plugins/web_ui_module/core/memory_helper.py:614`, comment: "prevents collateral deletion of unrelated facts"). Test was outdated, not a prod bug. Updated the assertion and documented the `results[:1]` contract in the docstring.
- **Tests: `llama_cpp` `TestModelPoolMmproj` patched a non-existent attribute** — `model_pool.py` imports `Llama` lazily inside `_create_instance`, so `patch("plugins.llama_cpp_module.core.model_pool.Llama", ...)` raised `AttributeError`. Patched `llama_cpp.Llama` at the source module instead.
- **Tests: `mlx` VLM bifurcation test relied on the `_is_vlm` singleton** which `execute()` stopped using in favour of `_detect_vlm_capability(config.model_path)` (comment: "more accurate, no stale state on model switch"). Patched the detector to `True` alongside the existing singleton setup.
- **Tests: `test_manifest.py` full-suite fails (5 pollutions) came from slowapi rate-limiter state carried over from `test_coverage_gaps.py`**, not from session-manager pollution as initially suspected. Added the `disable_rate_limiter` autouse fixture already present in `test_manifest_coverage.py` / `test_module.py`.
- **Tests: integration fixtures `TestRAGChatOllama.rag_client` / `TestRAGChatMLX.rag_client_mlx` wrote to the real dev `storage/vectors/`** and (MLX path) called `delete_collection('personal_memory')` on the shared Qdrant — a confirmed test-leak. Isolated with `tmp_path_factory` + `NEXE_QDRANT_PATH` env override, restored on teardown.

### Added

- `memory/memory/tests/test_dreaming_gc_integration.py` — 8 tests covering GCDaemon invocation, no-users fastpath, throttling, logging, exception isolation, cooperative stop, default daemon build, and full `run_cycle` wiring.
- `core/tests/test_lifespan_dreaming_embedder.py` — 2 tests verifying that `start_memory_service_v1` passes an embedder to `DreamingCycle` and survives embedder load failures.

### Documentation

- **Formal STRIDE threat model** (new `THREAT_MODEL.md` at repo root + `knowledge/{en,ca,es}/THREAT_MODEL.md`; `SECURITY.md:86` now points to it; `README.md`, `README-ca.md`, `README-es.md` "AI-Ready Documentation" section bumped from 13 to 14 thematic documents; `knowledge/{en,ca,es}/README.md` "Related documentation" list extended). Addresses DoD audit finding `DoD-AUD-SX-0423 §2.11`: the informal threat model at `SECURITY.md:3-15` is now a reviewed artefact — 8 trust boundaries (browser / CLI / Qdrant embedded / Ollama daemon / Hugging Face / filesystem / macOS Keyring / LAN-bootstrap), 6 asset categories, full STRIDE matrix with per-boundary mitigations citing `file:line` against the current codebase (post-F4.1), explicit out-of-scope enumeration (shell access, nation-state, multi-tenant, Python supply-chain pre-bundle, Apple firmware, malicious IDE extensions, offline `storage/` copies), honest residual-risks section (jailbreak speed-bump is not a safety classifier, `/ui/*` CSRF exemption trades cookie-CSRF for `X-API-Key`, loopback TLS is not enforced, no automated CVE tracking between releases, no external pen-test), and a LINDDUN privacy appendix covering MEM_SAVE exfiltration via prompt injection. Doc-only change — no code, no tests, no behaviour modification.

### Fixed

- **Security filter: SQL detector false positives on natural text** (`plugins/security/core/injection_detectors.py`). The pattern `r'--\s'` triggered on legitimate user input such as email visual separators (`----------`), RFC 3676 signature delimiters (`-- \n`), em-dashes in prose and dash-separated enumerations. Chat messages containing any of these returned HTTP 400 "SQL detected" at `/ui/chat`. Replaced with `r'[\'"]\s*--'`, which only matches the quote-dashdash signature of real SQL comment injection attacks. All 5 real SQL attacks in `test_real_attacks_still_blocked` remain blocked via other patterns. 4 regression tests added covering the natural-text cases.
- **UI: LaTeX math notation in chat output** (`plugins/web_ui_module/core/latex_sanitizer.py`, `plugins/web_ui_module/api/routes_chat.py`, `personality/server.toml`). Some models (notably Gemma-4-31B-8bit) emit LaTeX like `$\rightarrow$`, `$\times 2$`, `$\sqrt{x}$` and `\pi` in normal chat answers; the web UI renders Markdown via `marked.js` with no LaTeX engine, so users saw literal strings. Fixed server-side at the streaming boundary so web UI + future clients all benefit, without shipping KaTeX or any JS dependency. New `latex_to_unicode()` (two-pass inline-span + bare-command substitution, ~35 commands covered) and `LatexStreamBuffer` for chunked streams (retains trailing incomplete `\letters` and unclosed `$` so tokens split across chunks are reassembled before substitution). Currency (`$24.50`), shell variables (`$HOME`) and bare dollars survive untouched. FORMAT instruction added to all 6 system prompts (ca/es/en × small/full). 35 new pytest cases.
- **Session manager: double-init race hid encrypted sessions and silently wrote unencrypted ones** (`plugins/web_ui_module/module.py`, `plugins/web_ui_module/api/routes.py`). `WebUIModule.__init__` created a `SessionManager()` without crypto before `initialize()` could build the real one with the `crypto_provider`. The loader (`core/loader/manifest_base._get_module`) then called `instance._init_router()` immediately after `__init__`, and `create_router()` captured `session_mgr = module_instance.session_manager` into a local — snapshotting the crypto-less manager. Later `initialize()` replaced `self.session_manager` with an encrypted manager that had correctly loaded all `.enc` files, but the router routes still pointed at the original. Consequences: the web UI only listed `.json` sessions (`.enc` invisible though decryptable), new sessions were persisted unencrypted, and a reboot's `.json → .enc` migration could overwrite existing `.enc` files belonging to a different conversation with the same session id (collision observed in the wild). Fixed with a `_SessionManagerProxy` that re-reads `module_instance.session_manager` on every attribute access (late-binding), and a single `SessionManager(crypto_provider=crypto)` construction in `initialize()` (the placeholder in `__init__` was removed). Result: one real SessionManager per plugin life, routes always see it, encrypted sessions visible, new sessions written `.enc`.
- **Installer wizard tier mismatch on 48+ GB machines** (`installer/swift-wizard/Sources/InstallNexe/HardwareDetector.swift`). `ramTier` still returned `tier_64` / `tier_48` strings that the Python backend had removed from `models.json` when the catalog narrowed to 4 tiers in v1.0.0-beta. On machines with 48 GB+ RAM the wizard proposed a tier with no corresponding model set, so the defaults fell through. Trimmed the Swift branches to the four tiers actually shipped (16 / 24 / 32 / 32-plus) so the wizard and backend now agree.

### Changed

- **Knowledge-base embeddings regenerated** (`knowledge/.embeddings/`) to close two accumulated stale cases (FUNDING.yml ko-fi URL update from 2026-04-17 and the `[IMAGEN ADJUNTA] → [IMATGE ADJUNTA]` marker fix from 2026-04-20). Version references inside the knowledge base bumped to `1.0.2-beta` and re-embedded in the same pass.

## [1.0.2-beta] - 2026-04-21

End-of-line for the 1.0.x knowledge-base regeneration cycle. See `[1.0.3-beta]`
above for the F4.1 SHA256 pinning, F4.2 STRIDE threat model, and the security
DoD F1-F4 fixes that landed since.

### Documentation

- Knowledge-base embeddings regenerated (778 chunks × 3 languages) to close
  two accumulated stale cases (FUNDING.yml ko-fi URL update from 2026-04-17
  and the `[IMAGEN ADJUNTA] → [IMATGE ADJUNTA]` marker fix from 2026-04-20).
- Version metadata bumped from `1.0.1-beta` to `1.0.2-beta` across `pyproject.toml`,
  `personality/server.toml`, READMEs, `SECURITY.md`, `CONTRIBUTING.md`, the
  installer `Info.plist` files, and the knowledge base.

### Notes

- No public release tag was cut for 1.0.2-beta; the version was used internally
  during the F4.1 / F4.2 work and is documented here for chronological
  completeness so consumers comparing `pyproject.toml` against this changelog
  can trace the missing intermediate bump.

## [1.0.1-beta] - 2026-04-20

### Added

- **Linux ARM64 support** documented (tested via UTM, Ubuntu 24.04).
- **Installer: bundled Ollama offline** + fixed model tier threshold.
- **Memory: delete confirmation flow**, atomic fact splitter, VLM role fixes.

### Fixed

- **Installer (Linux)**: copy to `~/.local/share/nexe/` when source is Downloads dir (avoids permission issues).

### Changed

- Dependency security bumps from gitoss sync: `fastapi`, `python-multipart`, `pytest`.
- Version metadata bumped from `1.0.0-beta` to `1.0.1-beta` (pyproject, personality/server.toml, READMEs, SECURITY, CONTRIBUTING, installer Info.plist, knowledge base).
- Plugin-owned versions (`plugins/*/manifest.toml` and `plugins/*/module.py`) untouched: plugins follow their own release cycle (version = codi introduït), independent of product bumps.

## [1.0.0-beta] - 2026-04-16

### Summary

First public pre-1.0 release. Confidence bump from `0.9.9` after the final documentation coherence audit — no functional code changes beyond what `0.9.9` already shipped. The project is now considered a **minimum viable product for the real world**, open to community feedback.

### Changed

- Version metadata bumped to `1.0.0-beta` across the codebase (pyproject, plugins, installer, knowledge base).
- Knowledge base consolidated (13 thematic documents × 3 languages = 39 files), with Table of Contents and "In 30 seconds" quick intros added to user-facing docs (IDENTITY, INSTALLATION, USAGE, RAG).
- New document: `USE_CASES.md` (ca/en/es) covering 6 practical use cases and "when server-nexe is NOT the best tool".
- New section: `ERRORS.md` "How to report an error" with privacy warning for logs.
- Honest coverage figure (~85%) replaces inflated historical badges (97.4%/91.1%/93%).
- Security audits attribution expanded: Claude + Gemini + Codex + cross-model reviews (not just Claude).
- `AI collaboration` credit in author metadata: `"Jordi Goy with AI collaboration"`.
- Stripe / Ko-fi / GitHub Sponsors URLs corrected (Ko-fi was wrong: `/jgoylabs` → `/servernexe`).
- Root READMEs synchronised across CA/EN/ES with screenshots (`.github/screenshots/`) and the "giant spaghetti monster → minimal core" story framing.

### Unchanged (still true from 0.9.9)

- All functional fixes from 0.9.9 remain (Bug #18 MEM_DELETE, Bug #19 crypto/memory/session/installer, offline install 100%, macOS 14+ Apple Silicon target, `llama-cpp-python==0.3.19` pin).
- 4842 tests collected, ~85% global coverage.

### Known limits

- AI-only audits: no external human security audit yet.
- Single-user by design.
- Community feedback welcome via GitHub Issues and the forum at `server-nexe.com`.

## [0.9.9] - 2026-04-16

Pre-release consolidated: Bug #18 MEM_DELETE cirurgia + Bug #19 (4 sub-bugs) + offline-install bundle + Apple Silicon / macOS 14 narrowing + thinking toggle. Last P0 blockers closed before v1.0.

### Security

- **RAG injection via memory tags (#18 P0)**: `_filter_rag_injection` now
  neutralizes `[MEM_DELETE:…]`, `[MEM_SAVE:…]`, `[OLVIDA|OBLIT|FORGET:…]`
  and `[MEMORIA:…]` at ingest time (ingest_docs, ingest_knowledge) and at
  retrieval time (`_sanitize_rag_context`). Previously a malicious document
  could embed a MEM_DELETE tag in its body; the LLM would copy it verbatim
  into its response and the pipeline would execute the delete. Now every
  such tag becomes `[FILTERED]` before the model ever sees it. 4 new tests
  in `test_rag_sanitization.py`.

### Added

- **E2E integration tests for MEM_DELETE (#18 P0)**: new
  `tests/integration/test_mem_delete_e2e.py` with 8 tests against a real
  Qdrant (embedded, tmp_path) + real fastembed embedder. Covers the full
  save/list/delete/list-empty cycle, short-query-vs-long-stored matching
  under the 0.20 threshold, unrelated-fact survival guard, clear_memory
  wipe + safety rail, and RAG injection neutralization end-to-end.
  Closes the empirical gap flagged by BUS v0.9.0 feedback ("mocks enganyen").
  Marker `@pytest.mark.integration` — excluded from the default fast
  suite, run explicitly.
- **Thinking toggle endpoint**: `PATCH /session/{id}/thinking` (HOMAD,
  rate-limited at 10/min) lets the UI flip `<think>` output on/off per
  session. Backed by a `THINKING_CAPABLE` family safelist (qwen3.5,
  qwen3, qwq, deepseek-r1, gemma3/4, llama4, gpt-oss) and a `can_think(model)`
  helper; default is OFF, with a 400-retry fallback if the backend
  refuses. UI adds the ✨ sparkles toggle + 🧠 model dropdown. New
  env var `NEXE_OLLAMA_THINK`.
- `installer/build-wheels-bundle.sh` — pre-downloads all Python wheels
  (`--only-binary=:all:` for `macosx_14_0_arm64` + `cp312`) into
  `InstallNexe.app/Contents/Resources/wheels/`. Validates critical wheels
  are present and the total size is in range.
- `installer/build-embedding-bundle.sh` — uses a temporary venv with
  fastembed to pre-download the default multilingual embedding model into
  `InstallNexe.app/Contents/Resources/embeddings/`. Validates the ONNX +
  tokenizer + config artefacts are present.
- `build_dmg.sh` Step 5a/5b: orchestrates both new scripts before codesign
  and validates bundle sizes (exit code 14 on failure).
- Four new helpers in `installer/installer_setup_env.py`:
  `_find_bundle_resources`, `_write_venv_pip_conf`, `_seed_fastembed_cache`,
  `_default_fastembed_cache_dir`.
- Regression guards that grep `installer_setup_env.py` and
  `plugins/llama_cpp_module/module.py` for `CMAKE_ARGS` — fail the test
  suite if the flag is ever reintroduced.
- 40+ new tests across `test_installer_build_wheels.py`,
  `test_installer_build_embedding.py`, `test_installer_build_dmg.py`, and
  new classes in `test_installer_setup_env.py`.

### Changed

- **BREAKING — Apple Silicon only, macOS 14 Sonoma+**. The installer
  target narrows to Apple Silicon (arm64). Intel Macs and macOS 13
  Ventura are no longer supported. Knowledge base updated in ca/es/en.
- **Offline install: all Python wheels + embedding model bundled in the DMG**.
  The installer no longer downloads anything from PyPI or HuggingFace at
  install time. DMG size goes from ~20 MB to **~1.2 GB** (wheels + the
  fastembed multilingual model). On the client, the venv's `pip.conf` is
  configured with `find-links=<wheels>` and `no-index=true` so
  `pip install -r requirements.txt` uses only bundled wheels, and the
  fastembed cache is seeded from the bundled embedding model so
  `install.py` finds it already present. Root cause fixed: clean M1
  installs previously triggered the Xcode Command Line Tools prompt because
  `CMAKE_ARGS="-DGGML_METAL=on"` forced a `llama-cpp-python` source build
  even though the PyPI arm64 macOS wheel already ships with Metal. The
  installer now drops `CMAKE_ARGS` entirely. See
  `installer/build-wheels-bundle.sh`, `installer/build-embedding-bundle.sh`,
  and the `--skip-bundles` flag on `build_dmg.sh` for dev iteration.
- **`llama-cpp-python` pinned to `0.3.19`**. The `0.3.20` arm64 macOS
  wheel on PyPI is corrupted (Bad CRC-32) and fails to install from a
  clean venv. Pin held until upstream republishes a valid wheel.
- **Ollama `keep_alive: 0` on model switch (#14)**. When the UI switches
  models, the previous model is now unloaded explicitly so the new one
  gets VRAM immediately instead of waiting for Ollama's default TTL.
- **Image-attached prompt priority**. The internal `[IMATGE ADJUNTA]`
  marker makes the attached image take precedence over RAG snippets in
  the prompt, so multimodal backends see the picture instead of stale
  retrieval context.
- **Model catalog final layout**: 16 models across 4 tiers (8 / 16 / 24 /
  32 GB). The 64 GB tier is removed; Salamandra 2B, Qwen3.5 2B,
  Phi-4-mini, Llama 3.2 3B, Llama 4 Scout/Maverick, Mixtral, Mistral 7B,
  Qwen2.5 32B, QwQ 32B and GPT-OSS 120B are dropped from the catalog.

### Fixed

- **"Oblida tot" no longer arbitrarily deletes random facts (#18 P0)**:
  previously `detect_intent("Oblida tot")` returned `('delete', 'tot')`,
  which semantic-searched "tot" and deleted ~5 random facts similar to
  that token. Added explicit `CLEAR_ALL_TRIGGERS` (ca/es/en) checked
  **before** delete triggers, with a new `clear_all` intent. The pipeline
  arms a 2-turn confirmation (`session._pending_clear_all`) — the user
  must answer `sí, esborra-ho tot` / `yes delete everything` / `confirmo`
  / `go ahead` to actually wipe. Any other reply cancels and falls through
  as normal chat. Cables through to the previously-orphaned
  `clear_memory(confirm=True)`.
- **DELETE_THRESHOLD 0.70 → 0.20 (#18 P0)**: empirical finding from the
  new e2e integration suite — fastembed + paraphrase-multilingual scored
  even verbatim queries below 0.55. With the old 0.70 threshold, realistic
  flows like `save "L'usuari es diu Jordi i viu a Barcelona"` →
  `delete "em dic Jordi"` silently returned 0 matches and the fact was
  never deleted. 0.20 guarantees the forget actually forgets; occasional
  over-match on loosely related facts accepted as the better UX tradeoff
  for a "forget" primitive.
- **Bug #19a (P0) — personal_memory no longer wipes on restart.** The
  MemoryAPI singleton init previously contained a `delete_collection +
  create_collection` branch that fired whenever the Qdrant-reported vector
  size for `personal_memory` or `user_knowledge` did not match
  `DEFAULT_VECTOR_SIZE` (768). A transient `qdrant_client` anomaly or local
  storage corruption could cause the read to return a wrong size and
  silently wipe every saved memory. `DEFAULT_VECTOR_SIZE` is the single
  source of truth and nothing in the normal runtime path produces a
  different size, so the defensive branch was removed. If a real mismatch
  ever appears, Qdrant now surfaces a clear error at the next upsert rather
  than destroying user data.
- **Bug #19b (P0) — encrypted sessions (`.enc`) survive Keychain resets.**
  The Master Encryption Key (MEK) fallback chain is reordered to
  **file → keyring → env → generate**, and the file at `~/.nexe/master.key`
  (mode 0o600) is now written on every generation AND synced from the
  keyring when only the keyring has a key. Autonomous agents that reboot
  after a macOS upgrade, Keychain reset, or sandbox change keep their
  historical sessions and SQLCipher data readable. Atomic temp-file
  writes now use `tempfile.mkstemp` (unique name per call) to avoid
  collisions between concurrent in-process sync calls.
- **Bug #19c (P1) — images persisted with chat messages.**
  `ChatSession.add_message` now accepts an optional `image_b64` argument
  and stores it alongside the message text. On reload, attached images
  reappear inline in the UI. The field is emitted in the serialised JSON
  only when a value is present, preserving backward compatibility with
  existing session files. Corrupted `.enc` files now log at ERROR level
  (they represent invisible user data) and `SessionManager` exposes
  `corrupted_sessions_count` for health checks.
- **Bug #19d — single Nexe.app installation.** The installer no longer
  duplicates `Nexe.app` to `/Applications/Nexe.app`. The bundle lives
  only at `<install_dir>/Nexe.app` (next to `venv/`, so the Swift
  launcher resolves paths locally without relying on a marker file).
  Dock and Login Items now target the install-dir bundle. Legacy
  `/Applications/Nexe.app` left behind by earlier installs is removed
  at install time, with a guard against accidental self-deletion when
  `install_path == /Applications`.

### Removed

- `CMAKE_ARGS="-DGGML_METAL=on"` block + try/except fallback in
  `installer_setup_env.py` (caused the CLT prompt on clean M1).
- Unused `print_warn` import in `installer_setup_env.py`.
- `CMAKE_ARGS=...` suggestion in the error message of
  `plugins/llama_cpp_module/module.py` (obsolete advice that would
  re-trigger the same CLT prompt if a user followed it).

## [0.9.8] - 2026-04-15

Robust VLM detection + mlx-vlm 0.4 API port + installer / KB updates.

### Fixed

- **MLX VLM detection (silent degrade)**: `_detect_vlm_capability()` now combines
  three any-of signals: `architectures[]` (expanded set with Qwen2_5_VL, Qwen3VL,
  Qwen3_5Moe, Gemma4, LlavaOnevision, InternVL2, MiniCPMV, Idefics3, Mllama),
  `vision_config` presence, and `model.safetensors.index.json` weight map keys
  (`vision_tower`, `vision_model`, `visual.`, `mm_projector`, `image_newline`,
  `patch_embed`). Previously unknown VLM architectures fell through to `mlx_lm`
  and dumped 333 unmatched tensor names to the UI (Qwen3.5-MoE case).
- **_generate_vlm ported to mlx-vlm ≥ 0.4**: (1) `image=` now expects str path or
  List[str], not PIL.Image — incoming bytes are written to a NamedTemporaryFile
  and its path is passed (cleanup in `finally`). (2) `generate()` returns a
  `GenerationResult` dataclass, not raw str — we extract `.text` and map real
  metrics (`prompt_tokens`, `generation_tokens`, `prompt_tps`, `generation_tps`,
  `peak_memory`) into the response dict. Legacy str-result fallback kept.
- **llama_cpp VLM passthrough (BUG #9)**: images were extracted in `execute()` but never
  passed to `_generate()`/`_generate_streaming()`. Added VLM bifurcation with dedicated
  `_generate_vlm()`/`_generate_vlm_streaming()` methods (consistent with MLX pattern).
  Images encoded as base64 data URIs in OpenAI-compatible message format.
- **Versions hardcoded (BUG #10)**: 16+ locations had stale 0.9.0/0.9.1/1.0.0 strings.
  Created `core/version.py` (reads from `pyproject.toml` via `tomllib`) as single source
  of truth. All Python files now import `__version__`; Info.plist updated to 0.9.7.
- **Readiness check (P0)**: `ollama_module`, `mlx_module`, `llama_cpp_module` now return
  `DEGRADED` (not `UNHEALTHY`) when the LLM backend is unavailable (Ollama not running,
  model not loaded). The Web UI was blocked at "Iniciant..." on fresh installs because
  `UNHEALTHY` caused the overall readiness to fail; `DEGRADED` unblocks the UI.
- **Wizard: default install folder** now `/Applications/server-nexe` (was `~/server-nexe`).
- **Wizard: models show RAM (ram_gb)** instead of disk size (disk_gb) in model cards.
- **Wizard: tier selector (RAM tabs)** now centered (removed `minWidth: 640` ScrollView).
- **Wizard: "Obrir Nexe" button** shows a 10-second countdown with tray explanation before
  launching. Eliminates the screen flash caused by `killall Dock` at click time.
- **Dock icon "?"**: `doAddToDock()` now uses the actual install path (`engine.installPath`)
  instead of hardcoded `/Applications/Nexe.app`. Fixes broken Dock entry on non-standard paths.
- **Login item path** (`doAddLoginItem`) also fixed to use `engine.installPath`.
- **Logo glitch** on "Iniciant..." overlay: switched from `logo.png` to `logo.svg` for
  crisp rendering at all resolutions without pixel artifacts.

### Changed

- **Installer pins**: `mlx-lm 0.30.7 → 0.31.2` and `mlx-vlm 0.1.27 → 0.4.4`
  (adds support for gemma4, qwen3_5_moe, qwen3_vl, llava_onevision, and the
  full modern VLM zoo). Side effect: `numpy 1.26 → 2.4` and `opencv 4.10 →
  4.13`. Full test suite rerun after upgrade: 4679 passed, zero regressions
  (the 11 pre-existing failures on readiness/i18n unchanged).
- **Knowledge base**: new "Multimodal models (VLM)" section in
  `knowledge/{ca,es,en}/LIMITATIONS.md` documenting supported architectures,
  detection heuristics, torch dependency requirements for omni-video models
  (Qwen3.5-MoE, Qwen3-Omni, Kimi-VL — NOT bundled in the DMG for size),
  recommended default `gemma-4-e4b-4bit` / `gemma-4-31b-8bit`, and current
  pipeline gaps (no audio, no native video, no VLM streaming yet).

### Tests

- +9 tests in `plugins/mlx_module/tests/test_multimodal.py` (12 → 21): new
  architectures, `vision_config` detector, safetensors weight-map detector,
  malformed JSON safety, `_generate_vlm` path + GenerationResult extraction.

## [0.9.7] - 2026-04-12

Multimodal VLM: suport d'imatges als 4 backends (Ollama, MLX, Llama.cpp, Web UI).

### Added

- **Multimodal images (Ollama)**: `OllamaChat._build_payload()` and `chat()` accept
  `images: Optional[List[str]]` (base64 strings). Passed through to Ollama `/api/chat`.
- **Multimodal images (MLX)**: `_detect_vlm_capability()` reads `config.json` to detect
  VLM architectures (Qwen2-VL, LLaVA, PaliGemma, Gemma3, InternVL). `MLXChatNode._get_model()`
  bifurcates between `mlx_lm.load` (text) and `mlx_vlm.load` (VLM). New `_generate_vlm()`
  method uses `mlx_vlm.generate()` with `PIL.Image`.
- **Multimodal images (Llama.cpp)**: `mmproj_path` config field (env `LLAMA_MMPROJ_PATH`).
  `ModelPool` passes `clip_model_path` to `Llama()` when set. Graceful fallback: images
  ignored with warning if `mmproj_path` not configured.
- **Multimodal images (Web UI backend)**: `/ui/chat` endpoint validates `image_b64` +
  `image_type` (JPEG/PNG/WebP, max 10 MB). Passes `_images_arg` to all 3 engine call paths.
- **Camera button UI**: `#imageBtn` (camera icon), `#imagePreviewBar` (thumbnail strip),
  `#imageInput` (file picker, JPEG/PNG/WebP). `_handleImageSelect()` + `_clearSelectedImage()`.
  `sendMessage()` includes `image_b64` / `image_type` when image pending.
- **Dependency**: `mlx-vlm==0.1.27` added to installer (Apple Silicon). Compatible with
  `mlx-lm==0.30.7` and `transformers>=4.57`.
- **Tests**: 34 new multimodal tests across the 4 plugins (`test_multimodal.py`).

## [0.9.3] - 2026-04-12

Dependency: replace `sentence-transformers` + PyTorch (~600 MB) with `fastembed` (ONNX, ~50 MB).

### Changed

- **Embeddings backend**: `sentence-transformers` replaced by `fastembed` (ONNX runtime). Same
  model (`paraphrase-multilingual-mpnet-base-v2`), same 768-dim vectors, same cosine similarity
  results. No change to Qdrant collections or stored vectors.
- **SSOT**: embedding model name centralised in `memory/embeddings/constants.py`
  (`DEFAULT_EMBEDDING_MODEL`). Change model in one place — `personality/server.toml` or
  `constants.py` — propagates everywhere.
- **Installer**: downloads fastembed model to `~/.cache/fastembed/` instead of HuggingFace cache.
- `requirements.txt`: `sentence-transformers>=4.0.0` → `fastembed>=0.3.6`

### Removed

- PyTorch (`torch`) transitive dependency — no longer pulled in by `sentence-transformers`.
  Saves ~600 MB from the install footprint.

## [0.9.2] - 2026-04-12

Security hardening: 4 P1 fixes from mega-consultoria 2026-04-11.

### Security fixes

- **P1-A** — Rate limit UI auth failures per IP. `make_require_ui_auth()` now
  tracks failed authentication attempts in a per-IP in-memory dict with a 60s
  sliding window. After 20 failures, returns `429 Too Many Requests`. Protects
  `/ui/*` endpoints against brute force. Dict-in-memory is intentional (no
  persistence needed between restarts; nexe 0.9.x is single-worker).
  Commit `6651848`.

- **P1-B** — Auth failures from the Web UI are now logged to the security log.
  Previously `make_require_ui_auth()` raised `401` without calling
  `security_logger.log_auth_failure()`, making brute force against `/ui/chat`
  invisible to SIEM/security monitoring. Now uses the same lazy-import pattern
  as `auth_dependencies.py:185-195`. Commit `293fd45`.

- **P1-C** — Symlink upload attack blocked. Attack vector: `ln -s /etc/passwd
  evil.pdf && curl -F "file=@evil.pdf"` ingested 17 chunks of `/etc/passwd`
  into `user_knowledge`. Fix: `_is_symlink_outside_uploads()` check via
  `os.path.realpath()` immediately after `save_file()`. If the saved path
  resolves outside the uploads directory, the file is deleted and a `400` is
  returned. Does NOT affect model symlinks (MLX/llama.cpp/Ollama never go
  through `/upload`). Commit `353e1f6`.

- **P1-D** — Encryption default changed from `false` to `auto`. Previously all
  sessions were stored in plain text by default, contradicting the
  "privacy-first" README. New behaviour: if `sqlcipher3` is available,
  encryption is auto-enabled at startup; if not, a `WARNING` is logged and the
  server continues in plain text. `NEXE_ENCRYPTION_ENABLED=false` suppresses
  the warning. Existing plain-text data can be migrated with
  `nexe encryption encrypt-all`. Commit `a9970d7`.

## [0.9.1] - 2026-04-11

Consolidated release: Cirurgia Bloc 2 (2026-04-08) + Mega-consultoria hardening (2026-04-11).

### Security fixes (Mega-consultoria 2026-04-11)

Derived from a full security audit (mega-consultoria) with plan v2.4.

- **P0-1** — httpx split timeout for Ollama (chat + models). Previously a
  single 600s default meant Ollama hangs took up to 10 minutes to detect.
  Now `connect=5s` fails fast on a dead server, `read=600s` for chat
  (preserves thinking models like DeepSeek-R1 and QwQ), `read=60s` for
  models list/info/delete (fast operations). Env vars:
  `NEXE_OLLAMA_{CONNECT,READ,MODELS_READ,WRITE,POOL}_TIMEOUT`.
  Commit `61a72a3`.

- **P0-2** — llama_cpp_module ghost detection fixed. `/status` now reports
  `engines_available.llama_cpp` accurately. Three combined changes:
  - **P0-2.b** `core/lifespan_modules.py`: loader removes modules from
    `app.state.modules` when `initialize()` returns `False`. Also uses
    `list(plugin_modules.items())` to iterate safely while popping (avoids
    `RuntimeError: dictionary changed size during iteration`). Commit `af32c2c`.
  - **P0-2.a** `plugins/llama_cpp_module/module.py`: `import llama_cpp`
    check at `initialize()` returns `False` immediately if the native lib
    is missing (no phantom routes). Commit `06d5000`.
  - **P0-2.c** `core/endpoints/root.py`: extracted `_check_llama_cpp_available(modules)`
    helper that verifies `_node is not None`, symmetric with the existing
    MLX check. Helper extraction enables unit testing without a real
    `starlette.Request` (slowapi's `@limiter.limit` rejects `MagicMock`).
    Commit `3cccd7f`.

- **P0-3** — Model switching concurrency: added short `asyncio.Lock()`
  around the `body.model` singleton mutation block in
  `routes_chat.py:_chat_inner`. Commit `7aa18cb`.

    **Design note**: server-nexe v0.9.x is architecturally single-user
    (uvicorn workers=1, class-level singletons `LlamaCppChatNode._pool`
    and `MLXChatNode._model`, in-process state, global
    `_chat_semaphore(2)`). The short lock is a **pragmatic mitigation**
    for the rare edge case of two concurrent requests racing to mutate
    the same singletons. For mono-user local usage the scenario is
    effectively never triggered. A full multi-user architecture refactor
    (multi-pool LRU cache + `config_override` per request + removal of
    class-level singletons + horizontal uvicorn workers) is **deferred**
    until multi-user becomes an actual use case. See the complete
    deferred-work scope documented in ISSUE-multiuser-refactor.md.

- **P1-1** — Jailbreak speed-bump: regex detector for common patterns
  (ca/en: "ignora instruccions", "you are now a/an WORD", "forget your
  rules", "DAN mode", "do anything now", etc.). Hooked after
  `validate_string_input` in `/ui/chat`. **Opció B**: injects a
  `[SECURITY NOTICE]` prefix instead of rejecting (400) to preserve UX on
  false positives. Pattern #3 (`you are now a|an \w+`) is deliberately
  tight to avoid false positives on conversational English ("you are now
  at home", "you are now free to go", etc.). Commit `f8b75b7`.

    **Note**: defense-in-depth only. Sophisticated attackers evade via
    Unicode lookalikes, base64/gzip encoding, chained prompts, language
    switching, etc. For real protection use content moderation at the
    model level.

- **P1-2** — Memory tag strip regex anchored to line start. Catches
  `[MEMORIA:]`, `[MEM:]`, `[SYSTEM:]`, `[USER:]`, `[ASSISTANT:]`,
  `[TOOL:]`, `[FUNCTION:]`, `[MEMORY:]` in addition to the original
  `[MEM_SAVE:]`. Newlines are preserved via capture group 1. Commit `4a91058`.

    **BREAKING** from v0.9.0 (documented inline in the updated tests):
    - Mid-line tags are NO longer stripped. Before: any occurrence of
      `[MEM_SAVE:...]` was stripped regardless of position. From 0.9.1:
      only tags at the start of a line (or after `\n`) are stripped.
      Rationale: reduce false positives on inline text like
      `"review this [USER: Jordi] part"`.
    - Empty tags like `[SYSTEM]` (no colon, no content) now match at
      line start. Closes a jailbreak vector where attackers use bare
      role tags.
    - Equals separator `[MEMORIA=value]` also matches (not only `:`).
    - Accepted tradeoff: `[memoria]` at the very start of a message
      IS stripped even when used as a normal word. Users can work
      around with any prefix.

- **P1-4** — Upload content denylist for sensitive patterns. Scans the
  first 8KB of each upload and rejects with HTTP 400 if a known pattern
  is found. Patterns are tuned to the real stack used by this project:
  - System: `root:x:0:0:` (most specific /etc/passwd signature)
  - PEM private keys: RSA, OpenSSH, PKCS8, EC, DSA, PGP
  - API tokens: `sk-ant-` (Anthropic / Claude Code), `sk-proj-` (OpenAI
    GPT / Codex CLI / Responses API), `ghp_` + `github_pat_` (GitHub
    PAT classic + fine-grained), `AIzaSy` (Google Gemini / AI Studio /
    Cloud / Firebase).

  Commit `145d742`.

    **Note**: speed-bump only, trivially bypassed by `gzip`, `base64`,
    `xor`, or any custom encoding. Protects against accidental drag&drop
    of sensitive files, not determined adversaries. Generic AWS patterns
    were explicitly NOT included — this project does not use AWS and a
    generic OWASP checklist would add noise without value.

### Cirurgia Bloc 2 — Security & Memory Pipeline (2026-04-08)

#### Fixed

- **Item 17 — MEM_SAVE bug**: `POST /v1/memory/store` was rejected by the Gate heuristic (`reason="model_generated"`) because `source="api"` mapped to `is_user_message=False` and `is_mem_save` was not passed. Fixed by passing `is_mem_save=True` — the store endpoint IS an explicit MEM_SAVE operation and should bypass the "model_generated" gate.
- **Item 21 — SQLCIPHER false sense of security**: `core/lifespan.py` declared "encryption ENABLED" without checking `SQLCIPHER_AVAILABLE`. If `sqlcipher3` was missing, sessions were encrypted but the `memories.db` database was not. Fixed with fail-closed behavior: server refuses to start with a clear `RuntimeError` if encryption is requested but `sqlcipher3` is not installed.

#### Security

- **Item 19 — Memory injection via direct API**: `POST /v1/chat/completions` did not apply `strip_memory_tags` to user messages, allowing `[MEM_SAVE: ...]` injection via the API while the Web UI was protected. Fixed.
- **Item 20 — Prompt injection via auto-ingest**: `core/ingest/ingest_knowledge.py` and `core/ingest/ingest_docs.py` did not apply `_filter_rag_injection` to document chunks before storing, while the upload UI path was protected. Fixed.

#### Changed

- **Item 22 — Workflows metadata honest**: `GET /v1/` metadata updated: `workflows.status` changed from `"implemented"` (false) to `"stub-v0.9.1"`. New `core/endpoints/workflows.py` router added that returns `501 Not Implemented` for any `/v1/workflows/*` path.
- **Item 24 — Pipeline unique enforced**: Removed 3 plugin chat endpoints that bypassed the canonical pipeline (`/mlx/chat`, `/llama-cpp/chat`, `/ollama/api/chat`). All chat must go through `/ui/chat` (canonical) or `/v1/chat/completions` (OpenAI-compat). Item 23 (auth bypass) resolved by this removal.

### Deferred to 0.9.2+

- **P1-3** — Auth rate limiting (`TTLCache` + `NEXE_TRUST_PROXY`
  opt-in for `X-Forwarded-For` parsing). Only relevant when exposing
  server-nexe to the internet via a reverse proxy (Caddy, Traefik,
  Tailscale Funnel). For the current mono-user local deployment it is
  unnecessary. Trigger: decision to expose beyond localhost.

- **P0-3 full refactor** — Multi-pool LRU cache at `LlamaCppChatNode` +
  `MLXChatNode`, `config_override` parameter through
  `chat() → execute() → _get_model()`, `dataclasses.replace()` for
  immutable per-request configs, removal of class-level singletons,
  horizontal uvicorn workers, session manager migration.
  Trigger: multi-user becomes an actual use case.

- **QI-37 — Version string consolidation**: Resolved in commit `67242c9`
  (34 files synced to 0.9.1). Future: adopt single-source-of-truth pattern
  (e.g. `importlib.metadata.version("server-nexe")`).

### Known issues

- None. All pre-existing test failures resolved (commit `3e3dad7`:
  test_routes_lang_i18n synced with current_language assignment).

## [0.9.0] - 2026-03-31

### Added
- **Memory v1** — Automatic fact extraction, semantic deduplication, dreaming (offline consolidation). 22 new files, ~4765 lines. Qdrant embedded, zero external processes.
- Qdrant singleton pool for thread-safe concurrent access
- MEM_SAVE input injection prevention (strip user-side tags)
- Security false positive tests (47 scenarios)

### Fixed
- **Tray keyboard lock**: moved RAM polling (`_get_process_ram`) to background daemon thread (`_RamMonitor`). The main event loop (NSApplication/rumps) never calls `subprocess.run` now, preventing keyboard freeze after long runtime
- Installer venv no longer depends on DMG mount path after ejection
- GPT-OSS thinking detection now works during streaming (not retroactively)
- SEC-002: MEM_SAVE tags stripped from user input before LLM processing

### Changed
- Version bump from 0.8.5 to 0.9.0

## [0.8.5] - 2026-03-28

### Added
- Encryption at-rest (opt-in): AES-256-GCM via CryptoProvider with HKDF-SHA256 key derivation
- Master key management: OS Keyring, environment variable, or file-based fallback chain
- SQLCipher support for encrypted SQLite databases with automatic migration from plaintext
- Encrypted session files (.json to .enc migration with AES-256-GCM)
- TextStore for RAG document text (text removed from Qdrant payloads, stored in SQLite/SQLCipher)
- CLI commands: `nexe encryption status`, `nexe encryption encrypt-all`, `nexe encryption export-key`
- Encryption status displayed in server startup banner
- `NEXE_ENCRYPTION_ENABLED` environment variable for Docker/CI configuration
- Docker support: Dockerfile, docker-compose.yml, docker-entrypoint.sh (removed in 0.9.1 — untested, bare-metal only)
- Linux compatibility: conditional imports for macOS-only dependencies, platform-specific install guards
- `NEXE_DEFAULT_MAX_TOKENS` environment variable to configure LLM response length
- CLI `--verbose` flag for detailed per-source RAG weight information
- RAG relevance score bars in Web UI and CLI (aggregate + per-source detail)
- Model size (GB) displayed in model selector dropdown for all three backends
- Model loading indicator with real-time timer in Web UI
- Auto-scroll for thinking/reasoning output box in Web UI
- Ollama auto-start on server boot (macOS background launch, Linux `ollama serve`)
- Ollama VRAM cleanup on server shutdown (unloads all models)
- Backend auto-fallback: if configured backend is unavailable, selects first available backend
- Language selector in Web UI footer (Catalan, Spanish, English) with instant switching
- RAG info panel toggle explaining the relevance filter slider
- Automatic memory via LLM: MEM_SAVE extracts personal facts from conversation
- Memory delete intent: "Forget that..." / "Oblida que..." / "Olvida que..." in three languages
- Per-session document isolation: uploaded documents only visible in their session
- Upload overlay with spinner, filename, and real-time progress timer
- Knowledge base: 36 files (12 documents x 3 languages) with Mermaid architecture diagrams
- Cache-busting for static assets
- Modules loaded count in `/modules` endpoint response
- Trailing slash route for `/v1/` to prevent 307 redirects
- `COMMANDS.md` user-facing command reference documentation

### Fixed
- Streaming broken on second message due to render timer not being nullified
- `httpx.ReadTimeout` errors now logged with `repr()` instead of empty `str()`
- Safari HTTPS redirect: system tray uses `127.0.0.1` instead of `localhost`
- Streaming initialization delay for non-thinking models
- `asyncio.CancelledError` caught in MLX and llama.cpp stream generators
- Router prefix dead code in 4 plugins
- Thinking tokens from Ollama models using `message.thinking` field
- Module discovery: cache validation, correct plugin scan paths, TOML list format
- RAG now searches `nexe_documentation` collection
- RAG `nexe_web_ui` collection always searched
- MEM_SAVE counter shows only successful saves
- MEM_SAVE filters out hallucinated or negative facts before saving
- RAG relevance threshold lowered from 0.40 to 0.30 for better abstract query matching
- Ollama non-streaming response format converted to OpenAI-compatible structure
- MEM_SAVE tags stripped from non-streaming responses
- MEM_SAVE delete-then-re-save loop resolved
- `/v1/memory/search` searches all collections by default
- MLX `config.json` missing treated as error instead of silent warning
- `/ui/info` returns actual runtime backend instead of config default
- `i18n` labels no longer destroy child DOM elements
- CSP-safe language injection via `data-nexe-lang` HTML attribute
- Qdrant health endpoint corrected to `/health`
- Dead code removed: 3 orphan modules, unused imports
- `chunk_text()` unified to single implementation
- `PROJECT_ROOT` resolution standardized via `get_repo_root()`
- 7 silent `except: pass` blocks replaced with proper logging
- Logger lazy formatting in 5 locations
- macOS installer: Python bundled binary signing, payload extraction, venv symlinks

### Security
- Encryption at-rest: Qdrant payloads no longer contain plaintext content (vectors + IDs only)
- Input validation on all Web UI endpoints using `validate_string_input()`
- Path traversal protection on session ID parameters
- Filename validation on file uploads
- Rate limiting on all Web UI endpoints (5-30 requests/minute per endpoint)
- Unicode normalization (NFKC) applied to all 6 injection detectors
- RAG context sanitization aligned between API and UI pipelines
- Server process security hardened
- Auth failure logging captures real client IP address
- Runtime `print()` calls migrated to `logger.info()`

### Changed
- `chat.py` refactored from 1187 to 230 lines (split into 8 submodules)
- `routes.py` refactored from 974 to 87 lines (split into route modules)
- `tray.py` refactored from 707 to 419 lines
- `lifespan.py` refactored from 681 to 416 lines
- `vector_size=768` centralized to single constant
- 19 HTTPException messages internationalized (ca/es/en)
- System prompt rewritten: general-purpose personal assistant with persistent memory
- Knowledge base rewritten for RAG-optimized chunking
- Request timeout increased from 30s to 600s
- Codebase consolidation: 52 quality findings applied
- `colorama` dependency removed; `pyyaml` bumped; `tomli` removed
- Requires new dependencies: `cryptography>=44.0.0`, `keyring>=25.0.0`, `sqlcipher3>=0.5.0`
- Test suite: 4143 passing tests at release time (4572 as of 0.9.1)

## [0.8.2] - 2026-03-23

### Fixed
- RAG document deduplication on ingestion
- WebSocket control frame handling (ping/pong)
- Web UI sessionStorage race condition
- Memory `.count` endpoint consistency
- Llama.cpp conditional import (avoid crash when not installed)
- Circuit breaker resilience pattern hardened
- Chat endpoint streaming timeout for thinking models (300s configurable via NEXE_OLLAMA_STREAM_TIMEOUT)
- `num_predict` increased to 4096 for thinking models
- Security: injection detectors, input sanitizers, request validators improved
- Sanitizer pattern matching edge cases
- Module manager: discovery, lifecycle, registry, sync wrapper, path discovery refactored
- Plugin loading pipeline: extractor, finder, importer, lifecycle, validator hardened
- Memory persistence engine and text chunker edge cases
- OpenAPI merger and route manager stability
- Ollama health check reliability
- Llama.cpp config validation
- Event system and metrics collector robustness
- 35 test fixes across core, plugins, personality, and memory
- Web UI module tests (manifest, memory helper async, module)
- Security test coverage gaps and module allowlist tests

## [0.8.1] - 2026-03-21

### Added
- Headless installer for DMG wizard integration (install_headless.py)
- macOS menu bar tray app: start/stop server, RAM monitor, uptime, uninstaller (tray.py)
- Model catalog JSON export for Swift wizard (export_catalog_json.py)
- Tray icons with graceful fallback if missing
- Qwen3.5 models (2B, 4B, 9B, 27B) added to catalog (Ollama only — multimodal)

### Fixed
- Logger crash: "Attempt to overwrite 'module' in LogRecord" — reserved field renamed
- Web UI always showed English regardless of installation language — server now injects NEXE_LANG into HTML
- Qwen3.5 MLX removed from catalog (vision_tower incompatible with mlx_lm text-only)
- Uninstaller simplified: double confirmation dialog instead of text input
- export_catalog_json.py creates output directory if missing

## [0.8.0] - 2026-03-16

### Added
- Web UI with chat, file upload, and session management
- RAG (Retrieval-Augmented Generation) with Qdrant vector store
- Multi-engine support: MLX, Llama.cpp, Ollama
- Prefix caching for MLX (prompt cache manager)
- Session compaction with LLM summarization
- Security module with injection detection and sanitization
- Modular plugin architecture with personality system
- i18n support (Catalan, Spanish, English)
- CLI client for chat, memory, and status
- Guided installer with hardware detection

### Security
- API key authentication for all endpoints
- CSP headers (script-src 'self', no unsafe-inline)
- CSRF protection
- Rate limiting
- Input sanitization (jailbreak + injection detection)
- Trusted host middleware

### Fixed
- HuggingFace offline mode enforcement
- API key first-run UX message
- compactMatch scope variable declaration
- MAX_TAGS limit increased to 15
