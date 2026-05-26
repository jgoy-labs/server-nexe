# ADR-0013: Isolation Pattern — ACTIVE (Sprint 0.15 #3)

**Date:** 2026-04-18
**Status:** Accepted — **Active** (Sprint 0.15 #3)
**Decided by:** Jordi Goy
**Previous status:** deferred to plugin marketplace phase (Sprint 0.14)

## Context

Tauri v2 ships an [Isolation Pattern](https://v2.tauri.app/security/isolation/) that inserts an intermediate iframe between the main webview and the Rust core. This isolation frame filters and validates each IPC call before it reaches Rust, providing defense in depth against XSS on the main document.

Previously deferred because the starter only exposes the `greet` demo command. Reactivated in Sprint 0.15 because:
- Activating earlier bakes the pattern into the starter's DNA — downstream forks inherit defense-in-depth by default.
- The cost is modest (~100 lines JS + 2 config changes).
- Zero runtime overhead (validation is synchronous micro-checks).

## Decision

**Activate Isolation Pattern on the starter. Every IPC call flows through a filter that enforces an allowlist of commands + per-command argument validation.**

## Implementation

### Directory structure

```
isolation-frame/
├── index.html          # minimal shell loading isolation.js (no inline scripts)
├── isolation.js        # __TAURI_ISOLATION_HOOK__ implementation + allowlist
└── isolation.test.js   # vitest suite (12 tests, vm sandbox)
```

### Tauri config

`src-tauri/tauri.conf.json`:
```json
"security": {
  "csp": "...; frame-src 'self' plugin: https://tauri.localhost; ...",
  "pattern": {
    "use": "isolation",
    "options": { "dir": "../isolation-frame" }
  }
}
```

`frame-src` includes `https://tauri.localhost` because Tauri serves the isolation frame from that origin.

### Cargo features

`src-tauri/Cargo.toml`:
```toml
[build-dependencies]
tauri-build = { version = "2", features = ["isolation"] }

[dependencies]
tauri = { version = "2", features = ["tray-icon", "isolation"] }
```

### Filter logic (`isolation.js`)

- `__TAURI_ISOLATION_HOOK__(payload)` receives every IPC payload.
- Validates structure: non-null object with string `cmd`.
- Dispatches to per-command validator via allowlist (`ALLOWED[cmd]`).
- Unknown commands → `throw` (Tauri blocks the call).
- Invalid args → `throw` with descriptive message.
- Valid payload → passed through unchanged.

Current allowlist:
- `greet(args)` — args.name: string, 1-200 chars, no control chars.
- `get_auth_token(_args)` — no frontend payload; returns session Bearer token for sidecar HTTP/WS auth (S10 active).
- `quit_app(_args)` — no frontend payload; triggers graceful_quit dialog via command (S05 active).

When adding a new `#[tauri::command]` to `src-tauri/src/lib.rs`, add a matching validator here. The starter makes this the explicit pattern to prevent "just add a command without security review" drift.

### Integration with client

`src/main.js` already uses `invoke()` from `@tauri-apps/api/core` (ESM import). The Isolation Pattern is transparent at the client API level — no change needed; Tauri routes the IPC through the frame automatically.

## Alternatives (re)considered

| Option | Motiu descart |
|---|---|
| Keep deferred | Invites "just add a command" drift; activating now bakes security into the template. |
| Custom JS firewall (Sprint 0.14 #T2 postMessage style) | Already present for `postMessage` from plugins; doesn't cover IPC (`invoke`). Complementary, not alternative. |
| Per-command attestation (signed args) | Overkill for this scale. |

## Consequences

**Positives:**
- Attacker who achieves XSS on the main webview still has to bypass the isolation filter to invoke arbitrary commands. Defense in depth.
- Allowlist pattern surfaces every new command at review time — "did you add a validator?".
- Forward-compatible: plugin marketplace phase (ADR-0007) inherits this frame and can tighten per-plugin.

**Negatives / risks:**
- Every `invoke()` incurs a tiny ms of frame round-trip. Benchmarked as negligible (<1ms for `greet`).
- If `isolation.js` has a bug, IPC breaks silently. Mitigated by vitest suite.
- Must remember to add validator when registering new commands. Mitigated by doc in `isolation.js` header + this ADR.

## Tests (`isolation-frame/isolation.test.js`)

Tests passing in vitest (loaded via `node:vm` sandbox):
- Hook installed on window.
- Allowlist exposed for inspection.
- Valid greet passes through.
- Unknown command rejected.
- Missing / non-string / empty cmd rejected.
- Non-object payload rejected.
- greet with missing/non-string/empty/oversized/control-char name rejected.
- Tauri-infra keys (callback, error, `__*`) ignored during arg validation.
- `get_auth_token` and `quit_app` pass through with no-payload validators.

## Verification

- `cargo check` — passes (features `isolation` added to tauri-build + tauri).
- `pnpm test` — isolation tests + main.js tests passing.
- IPC round-trip empirically verified on Windows ARM64 (2026-04-19, cargo tauri dev).
- Allowlist covers all registered commands: `greet`, `quit_app`, `get_auth_token`.

## References

- [Tauri Isolation docs](https://v2.tauri.app/security/isolation/)
- [ADR-0007 Plugins 3 tiers](ADR-0007-plugins-tres-nivells.md)
- [ADR-0008 Zero Trust local](ADR-0008-seguretat-zero-trust.md)
- `isolation-frame/` — implementation.
- `src-tauri/tauri.conf.json` — pattern config.
