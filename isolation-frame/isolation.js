// Isolation hook — Sprint 0.15 #3 / ADR-0013 active.
//
// Tauri 2 Isolation Pattern: every `invoke()` payload from the main webview
// flows through this hook BEFORE reaching the Rust core. Defense in depth
// against XSS on the main document — if the main app is compromised, the
// attacker still has to bypass this filter to call arbitrary commands.
//
// Contract: `window.__TAURI_ISOLATION_HOOK__` receives the payload and
// returns it (possibly modified) or throws to block the call.
//
// Policy: allowlist of commands with per-command argument validators.
// Any unknown command is rejected. Any invalid args throw.

(function () {
    "use strict";

    // S04 F074: Prototype-free allowlist (prevents pollution of `ALLOWED["constructor"]`
    // returning `Function.constructor`). Object.create(null) + explicit assignments.
    // Keep in sync with `#[tauri::command]` handlers registered in src-tauri/src/lib.rs.
    //
    // Tauri 2 payload shape (empirically verified on Windows ARM64 2026-04-19):
    //   invoke("greet", { name: "X" }) → hook receives { cmd, callback, error, payload: { name: "X" } }
    const ALLOWED = Object.create(null);
    ALLOWED.greet = (args) => {
        const name = args?.payload?.name;
        if (typeof name !== "string") {
            throw new Error("isolation: greet requires { payload: { name: string } }");
        }
        if (name.length < 1 || name.length > 200) {
            throw new Error("isolation: greet name length must be 1-200");
        }
        // No control characters (ANSI injection / log spoof)
        if (/[\x00-\x1F\x7F]/.test(name)) {
            throw new Error("isolation: greet name has control chars");
        }
    };

    // S05 F043 — no frontend payload required.
    // quit_app<R: Runtime>(app: tauri::AppHandle<R>) — Tauri injects app handle,
    // frontend sends no args. Triggers graceful_quit dialog via command.
    ALLOWED.quit_app = (_args) => {
        // No payload required. Triggers graceful_quit via command.
    };

    // Returns the dynamic sidecar port assigned at startup. No payload.
    ALLOWED.get_sidecar_port = (_args) => {
        // No payload required.
    };

    // F5.3 onboarding commands — no frontend payload for any of these.
    ALLOWED.get_hardware = (_args) => {
        // No payload required. Returns HardwareInfo struct.
    };
    ALLOWED.fetch_catalog = (_args) => {
        // No payload required. Returns Vec<CatalogModel>.
    };
    ALLOWED.check_first_run = (_args) => {
        // No payload required. Returns bool.
    };
    ALLOWED.mark_onboarding_complete = (_args) => {
        // No payload required. Writes completion flag to app_config_dir.
    };
    ALLOWED.check_partial_install = (_args) => {
        // No payload required. Returns bool (partial install detected).
    };
    ALLOWED.reset_installation = (_args) => {
        // No payload required. Removes onboarding flags + .extracted marker.
    };
    ALLOWED.open_external_url = (args) => {
        // url must be a non-empty string starting with http:// or https://.
        if (typeof args?.url !== "string" || !args.url.match(/^https?:\/\//)) {
            throw new Error("isolation: open_external_url requires https?:// url");
        }
    };
    // DO NOT allowlist a `get_nexe_api_key` command: exposing the primary
    // api_key via invoke() is an XSS exfiltration vector. The wizard
    // receives the api_key via /installer/finalize response body
    // (see src/onboarding/step5-apikey.js).

    // F5.3.1 — restart the sidecar after the onboarding wizard has persisted
    // the user's engine + model choice. No payload (Tauri injects AppHandle on
    // the Rust side). Returns u16 (the new ephemeral sidecar port).
    ALLOWED.restart_sidecar = (_args) => {
        // No payload required.
    };

    // Security C25 (2026-04-21) — Phase 2 Skeleton.
    // fetch_from_sidecar(url, method, body?) — intercepts calls to the server-nexe
    // sidecar and injects the Bearer token on the Rust side. The main webview
    // never touches the raw token (C25 auth token exposure mitigation).
    //
    // Local validators: URL only to sidecar 127.0.0.1, method allowlist,
    // body only for POST/PUT. Defense in depth — Rust validates again.
    //
    // B2 Sprint 0.18 (2026-04-21): structural parse via `new URL(...)`
    // (before: `startsWith("http://127.0.0.1:")` bypassed via userinfo).
    // Extracted to validateSidecarUrl + validateBody (Dev Session 2026-05-08) to reduce CCN.

    // Validates that the URL points exclusively to the local sidecar (B2 defense).
    // Throws Error if not valid.
    function validateSidecarUrl(url) {
        if (typeof url !== "string") {
            throw new Error("isolation: fetch_from_sidecar requires url: string");
        }
        if (url.length > 2048) {
            throw new Error("isolation: fetch_from_sidecar URL too long (>2048)");
        }
        if (/[\x00-\x1F\x7F]/.test(url)) {
            throw new Error("isolation: fetch_from_sidecar URL has control chars");
        }
        let parsed;
        try {
            parsed = new URL(url);
        } catch (_) {
            throw new Error("isolation: fetch_from_sidecar URL parse failed");
        }
        if (parsed.protocol !== "http:") {
            throw new Error("isolation: fetch_from_sidecar URL must target sidecar (http://127.0.0.1:)"); // nosemgrep
        }
        // Exact host — only accepts literal "127.0.0.1". Rejects `localhost`, // nosemgrep
        // `::1`, `[::ffff:127.0.0.1]`, and any host-via-userinfo-hijack.
        if (parsed.hostname !== "127.0.0.1") { // nosemgrep
            throw new Error("isolation: fetch_from_sidecar URL must target sidecar (http://127.0.0.1:)"); // nosemgrep
        }
        // Userinfo rejected — red team B2 bypass vector (4 PoC vectors).
        if (parsed.username !== "" || parsed.password !== "") {
            throw new Error("isolation: fetch_from_sidecar URL must not contain userinfo");
        }
        if (parsed.port === "") {
            throw new Error("isolation: fetch_from_sidecar URL must include explicit port");
        }
    }

    // Validates the HTTP method and, if present, the body. Throws Error if not valid.
    function validateMethodAndBody(method, body) {
        if (typeof method !== "string") {
            throw new Error("isolation: fetch_from_sidecar requires method: string");
        }
        const allowedMethods = ["GET", "HEAD", "POST", "PUT", "DELETE"];
        if (allowedMethods.indexOf(method) === -1) {
            throw new Error("isolation: fetch_from_sidecar method must be one of " + allowedMethods.join(","));
        }
        if (body !== undefined && body !== null) {
            if (typeof body !== "string") {
                throw new Error("isolation: fetch_from_sidecar body must be a string (or omitted)");
            }
            if (method !== "POST" && method !== "PUT") {
                throw new Error("isolation: fetch_from_sidecar body only allowed for POST/PUT");
            }
            if (body.length > 1024 * 1024) {
                throw new Error("isolation: fetch_from_sidecar body too large (>1MB)");
            }
        }
    }

    ALLOWED.fetch_from_sidecar = (args) => {
        const url = args?.payload?.url ?? args?.url;
        const method = args?.payload?.method ?? args?.method;
        const body = args?.payload?.body ?? args?.body;
        validateSidecarUrl(url);
        validateMethodAndBody(method, body);
    };

    // Validator for the Tauri 2 isolation payload shape.
    // Payload is { cmd, callback, error, ...args } or similar — the cmd key
    // is the authoritative command name. We validate structure first, then
    // dispatch to the per-command validator with the args subset.
    function validate(payload) {
        if (!payload || typeof payload !== "object") {
            throw new Error("isolation: payload must be an object");
        }
        const cmd = payload.cmd;
        if (typeof cmd !== "string" || cmd.length === 0) {
            throw new Error("isolation: payload.cmd must be a non-empty string");
        }
        const validator = ALLOWED[cmd];
        if (!validator) {
            throw new Error(`isolation: command '${cmd}' not in allowlist`);
        }
        // Build args object by stripping known Tauri-infra keys.
        const TAURI_INFRA_KEYS = new Set(["cmd", "callback", "error", "__tauriModule"]);
        const args = Object.fromEntries(
            Object.entries(payload).filter(([k]) => !TAURI_INFRA_KEYS.has(k) && !k.startsWith("__"))
        );
        validator(args);
    }

    window.__TAURI_ISOLATION_HOOK__ = (payload) => {
        validate(payload);
        // Pass through unchanged. To redact / mutate, return a modified copy.
        return payload;
    };

    // Export for unit tests (browser env only).
    if (typeof window !== "undefined") {
        window.__isolationValidate = validate;
        window.__isolationAllowed = ALLOWED;
    }
})();
