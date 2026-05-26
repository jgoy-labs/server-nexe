# Using this repo as a template

A clean starter for **Tauri v2 desktop apps**, with optional Python sidecar wiring. This document walks you through adapting it to your own app and extending it (Python backend, React/Svelte, auth).

> The default identifiers (`nexe-app`, `nexe_app`, `com.nexe.app`) are placeholders. Run [`./scripts/rename.sh my-app`](#rename) right after cloning to swap them.

- [Stack baseline](#stack-baseline)
- [Key architectural decisions](#key-architectural-decisions-adrs)
- [File layout](#file-layout)
- [First-use steps](#first-use-steps)
- [Rename](#rename)
- [Prerequisites](#prerequisites)
- [Adding a Python sidecar](#adding-a-python-sidecar)
- [Switching to React / Svelte / Vue](#switching-to-react--svelte--vue)
- [Adding auth baseline](#adding-auth-baseline)
- [What this template already solves](#what-this-template-already-solves)
- [What's still TODO](#whats-still-todo)

---

## Stack baseline

| Layer | Tech | Why |
|---|---|---|
| Shell | Tauri v2.10+ | Thin, Rust-safe, ~10MB binary |
| Frontend bundler | Vite 8 | Fast dev server, HMR, small build |
| JS testing | Vitest 4 | Symmetric with `cargo test` |
| Rust testing | `cargo test` | Pure-function unit tests for the `plugin://` resolver |
| Rust lint | `cargo clippy -- -D warnings` | Zero-warnings policy |
| Rust audit | `cargo-audit` (CI gate) | `.cargo/audit.toml` for justified transitive ignores |
| Tauri-modern JS | `@tauri-apps/api/core` ESM | No `window.__TAURI__` global |
| Logs | `tracing` + `tracing-subscriber` | Structured, control-char sanitized |
| CI | GitHub Actions matrix (macOS + Ubuntu) | Multi-platform from the start |
| License | Apache-2.0 | Permissive, attribution required |

## Key architectural decisions (ADRs)

See [`docs/adr/`](docs/adr/). Core ones:

- ADR-0001 — Shell = Tauri v2 (not Electron, not Flutter)
- ADR-0002 — Python sidecar via relocatable venv (if you need one)
- ADR-0003 — Agent browser = Playwright + Chromium (not inside the webview)
- ADR-0004 — Thin shell / thick backend
- ADR-0005 — IPC híbrid: HTTP/WS + Tauri Commands
- ADR-0007 — Plugins 3 tiers: core / first-party / third-party (iframe sandboxed)
- ADR-0008 — Zero Trust local — see `Implementation status` section for what's live vs planned
- ADR-0009 — `plugin://` URI scheme
- ADR-0010 — API contract v0 (7 endpoints for sidecar integration)
- ADR-0011 — Distribution channels (lite / full)
- ADR-0012 — `plugin://` on Linux WebKitGTK (empirical validation pending)
- ADR-0013 — Isolation Pattern active (every `invoke()` filtered; allowlist: `greet`, `quit_app`, `get_auth_token`, `fetch_from_sidecar`)
- ADR-0014 — Plugin integrity active (SHA-256 atomic snapshot verify+load)
- ADR-0015 — Reproducible builds — SLSA baseline

## File layout

```
.
├── LICENSE                       # Apache-2.0 — keep or replace
├── README.md                     # adapt for your app
├── SECURITY.md                   # vulnerability reporting policy
├── TEMPLATE.md                   # this file — delete from your fork
├── .editorconfig                 # editor defaults
├── .github/
│   ├── workflows/check.yml       # CI: fmt + clippy + test + audit + build
│   └── dependabot.yml            # weekly updates for cargo + npm + actions
├── rust-toolchain.toml           # channel stable + clippy + rustfmt
├── package.json                  # engines, packageManager, scripts
├── pnpm-lock.yaml                # regenerate after rename/edits
├── vite.config.js                # Vite + Vitest config
│
├── scripts/
│   ├── rename.sh                 # rename placeholders to your app name
│   └── verify.sh                 # run CI checks locally
│
├── src/                          # frontend (Vite root)
│   ├── index.html                # adapt UI (greet form is a demo)
│   ├── main.js                   # ESM entry point
│   ├── main.test.js              # vitest tests (greet, auth token, commands)
│   ├── api/commands.js           # invoke() wrappers (extend here)
│   ├── styles.css                # adapt
│   └── assets/                   # SVGs — replace / remove
│
├── src-tauri/                    # Rust backend
│   ├── .cargo/audit.toml         # justified cargo-audit ignores
│   ├── rustfmt.toml              # explicit defaults
│   ├── Cargo.toml                # deps, metadata, [profile.release] hardening
│   ├── tauri.conf.json           # CSP, window, bundle (incl. `resources`)
│   ├── capabilities/default.json # `core:default` only
│   ├── icons/                    # replace with your icons (use `tauri icon`)
│   └── src/
│       ├── main.rs               # keep
│       └── lib.rs                # adapt — see inline comments
│
├── plugins-dev/                  # fixture for the `plugin://` demo
│   └── rag/                      # ⚠️ SPIKE — remove or replace with real plugins
│
└── docs/
    ├── adr/                      # architecture decision records
    └── api-contract-v0.md        # HTTP/WS contract example (for sidecar)
```

## First-use steps

```bash
# 1. Get a copy and drop the original git history
git clone <this-repo> my-app
cd my-app
rm -rf .git && git init -b main

# 2. Rename placeholders across the codebase
./scripts/rename.sh my-app

# 3. Install
pnpm install
(cd src-tauri && cargo check)

# 4. Verify
./scripts/verify.sh    # runs the same checks as CI
cargo tauri dev        # opens the native window

# 5. Trim template-only files you don't need
rm TEMPLATE.md
# if you don't use the plugin:// scheme:
#   rm -rf plugins-dev/
#   — and remove the corresponding code from src-tauri/src/lib.rs
# adapt docs/adr/ to your own decisions (or delete what doesn't apply)
```

## Rename

`scripts/rename.sh` replaces three identifiers across text files:

| Placeholder | Where |
|---|---|
| `nexe-app` | Display names, file names, Tauri `productName`, npm `name`, Cargo `name` |
| `nexe_app` | Rust lib/bin identifiers (`nexe_app_lib`, `nexe_app::...`) |
| `com.nexe.app` | Tauri reverse-DNS `identifier` |

Usage:

```bash
./scripts/rename.sh my-app
# Afterwards verify (should print 0 matches):
rg -n 'nexe-app|nexe_app|com\.nexe\.app' . -g '!node_modules/*' -g '!target/*' -g '!dist/*'
```

The script enforces lowercase-kebab format and is idempotent on already-renamed trees.

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Rust | stable ≥ 1.88 | `rustup update stable` |
| Node.js | ≥ 22 (LTS recommended) | `nvm install --lts` |
| pnpm | ≥ 10 | `npm i -g pnpm@10` |
| tauri-cli | ^2.10 | `cargo install tauri-cli --version "^2.10"` |
| macOS | 13+ Ventura | WKWebView baseline |
| Linux | WebKitGTK 4.1+ | `apt install libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev` |

## Adding a Python sidecar

Tauri doesn't bundle directories as `externalBin` — only single binaries per target triple. For a venv tree, use `bundle.resources` (already wired for `plugins-dev/`) and spawn Python from Rust:

**1. Bundle the venv** (`src-tauri/tauri.conf.json`):

```jsonc
"bundle": {
  "resources": {
    "../plugins-dev/": "plugins/",
    "../python-bundle/": "python-bundle/"   // your relocatable venv
  }
}
```

**2. Extend capabilities** (`src-tauri/capabilities/default.json`):

```json
{
  "permissions": [
    "core:default",
    "shell:allow-execute"
  ]
}
```

**3. Spawn from Rust** (inside `src-tauri/src/lib.rs` setup):

```rust
use std::process::Command;

tauri::Builder::default()
    .setup(|app| {
        let python = app.path()
            .resource_dir()?
            .join("python-bundle/bin/python3");
        let sidecar = Command::new(python)
            .arg("-m").arg("my_sidecar")
            .spawn()?;
        app.manage(std::sync::Mutex::new(sidecar)); // for graceful shutdown
        Ok(())
    })
    // ...
```

**4. Extend CSP** (`src-tauri/tauri.conf.json`):

```jsonc
"security": {
  "csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:<PORT> ws://127.0.0.1:<PORT> ipc: http://ipc.localhost; ..."
}
```

**5. Graceful shutdown** (`src-tauri/src/lib.rs` `RunEvent::ExitRequested`):

```rust
if let tauri::RunEvent::ExitRequested { api, .. } = &event {
    // TODO: POST /shutdown → wait 5s → kill_process_tree(pid)
    // See the TODO comments in lib.rs for the full pattern.
}
```

**6. Playwright browsers path** (if the sidecar uses Playwright):

```bash
# In your run-sidecar script:
export PLAYWRIGHT_BROWSERS_PATH="${APP_DATA_DIR}/browsers"
```

## Switching to React / Svelte / Vue

The template is framework-agnostic at the Vite layer. To swap:

### React

```bash
pnpm add react react-dom
pnpm add -D @vitejs/plugin-react
```

Edit `vite.config.js`:

```js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  root: "src",
  // ... rest unchanged
});
```

Convert `src/index.html` and `src/main.js` to the usual `#root` + `createRoot` pattern.

### Svelte

```bash
pnpm add -D @sveltejs/vite-plugin-svelte svelte
```

Edit `vite.config.js` adding the `svelte()` plugin. Convert entry to `App.svelte`.

### Vue

```bash
pnpm add vue
pnpm add -D @vitejs/plugin-vue
```

Same pattern — add the plugin, convert entry to `App.vue`.

The Rust layer (`lib.rs`), CSP, capabilities, plugin scheme, and CI are unaffected.

## Auth baseline (S10 — active in the starter)

The starter **ships with a session token baseline active** (Zero Trust local). Every app launch generates a fresh UUID v4 (128 bits entropy) in `setup()` and exposes it via `get_auth_token` command.

### Rust side (already wired)

```rust
// src-tauri/src/lib.rs
pub struct AuthToken(pub String);

impl AuthToken {
    fn generate() -> Self {
        AuthToken(uuid::Uuid::new_v4().to_string())
    }
}

#[tauri::command]
fn get_auth_token(state: tauri::State<'_, AuthToken>) -> String {
    state.0.clone()
}

// .setup()
let token = AuthToken::generate();
app.manage(token);
```

### Sidecar wiring (Fase 2 — your responsibility)

1. Spawn the sidecar with the token as env var:
   ```rust
   // When spawning the Python sidecar:
   std::process::Command::new(python_bin)
       .env("NEXE_AUTH_TOKEN", &token.0)
       .spawn()?;
   ```

2. Sidecar reads the env var and enforces `Authorization: Bearer <token>` on every HTTP/WS request (see `docs/api-contract-v0.md` §Authentication for FastAPI middleware reference).

3. Use `hmac.compare_digest` (Python) or `subtle::ConstantTimeEq` (Rust) — avoid timing attacks.

### Frontend side

```js
import { invoke } from '@tauri-apps/api/core';

const token = await invoke('get_auth_token');
fetch('http://127.0.0.1:8000/health', {
  headers: { 'Authorization': `Bearer ${token}` }
})
```

**Never log the token.** Don't persist it (it regenerates every launch by design).

This stops CSRF from a rogue webpage or other local process hitting `localhost:<PORT>`.

## Frontend interaction pattern

This starter uses `withGlobalTauri: false` + Isolation Pattern. This means:
- Import `@tauri-apps/api/core` for `invoke()` — no `window.__TAURI__`
- All invoke calls pass through `isolation-frame/isolation.js` allowlist
- Adding a new `#[tauri::command]`? Add a validator to `ALLOWED` in `isolation.js` too
  (a drift check test will fail in CI if you forget)

## What this template already solves

Based on two rounds of security consultancy (see commit history):

### Code & security

- `env!("CARGO_MANIFEST_DIR")` leak fixed via dev/release split (`plugin_root()`).
- Path traversal protected (`canonicalize() + starts_with()` against per-plugin root, plus `is_file()` + 10 MB size cap).
- `validate_plugin_id()` lowercase-only to avoid APFS vs ext4 case ambiguity.
- Percent-decoded paths (Unicode / spaces work).
- 404 / 403 responses with no path leakage.
- 405 for any non-GET/HEAD method.
- Simple rate limiter (1000 req/s, mitigates DoS via JS loops).
- `tracing` logs with control-char sanitization (anti log-injection).

### Configuration

- Strict CSP on the main window (no `'unsafe-inline'`, no hardcoded backend port).
- Dedicated CSP header emitted by the `plugin://` handler for plugin iframes.
- `withGlobalTauri: false` + ESM-only imports.
- `capabilities/default.json` = `core:default` only.
- `bundle.resources` wired so `plugin://` works in release.
- `.cargo/audit.toml` with justified ignores (`cargo audit --deny warnings` is a real gate).
- `[profile.release]`: `strip`, `lto`, `panic = "abort"`.
- `rust-toolchain.toml` + `package.json` engines + `Cargo.toml rust-version`.

### Tests & CI

Baseline tests (pre-`v0.1.1-fase0-security`):
- **Rust:** 47 debug / 54 release (STRICT_INTEGRITY=true). Path traversal, cross-plugin, symlink escape, null byte, percent-encoding, directory, plugin integrity, TOCTOU, concurrent verify, rate limit LRU, Windows reserved names, etc.
- **Vitest:** 55 (2 test files: isolation.test.js + main.test.js, at v0.1.1-fase0-security).
- **Clippy:** clean on lib+bins.

Exact numbers verified at `v0.1.1-fase0-security` tag. See CHANGELOG.

- GitHub Actions matrix: macOS + Ubuntu 22.04 + Windows with timeout + concurrency group.
- Steps: `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `cargo audit`, `pnpm audit`, `pnpm build`, `pnpm test`, `pnpm tauri build --no-bundle` (smoke).
- `permissions: contents: read` on the workflow.
- Dependabot config for cargo + npm + actions.

### Housekeeping

- `scripts/verify.sh` runs the full CI locally.
- `scripts/rename.sh` swaps all placeholders in one go.
- `SECURITY.md` reporting policy.
- `.editorconfig` for consistent formatting across editors.

## What's still TODO

These are outside the starter's scope — opt-in when your app needs them:

- `graceful_quit()` — implement the shutdown HTTP → wait → kill sequence in the `RunEvent::ExitRequested` handler (depends on your sidecar's shutdown endpoint).
- `get_backend_port()` Tauri command (for dynamic sidecar port fallback).
- `kill_process_tree()` Unix + Windows `Job Object` (prevents sidecar zombies).
- Empirical validation of `plugin://` on Linux WebKitGTK (ADR-0012).
- Plugin signatures (SHA-256 per plugin subtree) — needed before opening a marketplace.
- SHA-pinning of GitHub Actions (Dependabot will help here once the repo is public).
- macOS signing + notarization + Linux AppStream metadata.
- Isolation Pattern is already active (ADR-0013). When adding commands, extend `isolation-frame/isolation.js` allowlist.

## License

Apache-2.0. Use freely; attribution required on redistribution.
