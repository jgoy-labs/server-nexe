// Unit tests for the Isolation Pattern filter (Sprint 0.15 #3 / ADR-0013 active).
// Runs isolation.js inside a sandboxed vm context with a window shim.

import { describe, it, expect, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import vm from "node:vm";

const ISOLATION_JS = readFileSync(
    resolve(__dirname, "isolation.js"),
    "utf-8"
);

function loadIsolationWithWindow() {
    const window = {};
    // B2 Sprint 0.18: the `fetch_from_sidecar` validator uses `new URL(...)`
    // for structural parsing (prevents userinfo bypass). In Node `URL` is
    // global, but vm contexts do not inherit it by default — we inject it
    // explicitly so the loaded code can parse URLs.
    const context = vm.createContext({ window, URL });
    vm.runInContext(ISOLATION_JS, context);
    return window;
}

describe("Isolation filter", () => {
    let win;

    beforeEach(() => {
        win = loadIsolationWithWindow();
    });

    it("installs __TAURI_ISOLATION_HOOK__ on window", () => {
        expect(typeof win.__TAURI_ISOLATION_HOOK__).toBe("function");
    });

    it("exports validator + allowlist for testing", () => {
        expect(typeof win.__isolationValidate).toBe("function");
        expect(win.__isolationAllowed).toBeTypeOf("object");
        expect(win.__isolationAllowed.greet).toBeTypeOf("function");
    });

    it("accepts a valid greet payload and returns it", () => {
        // Tauri 2 shape: args wrapped in .payload (verified on Windows ARM64)
        const payload = { cmd: "greet", payload: { name: "Jordi" } };
        const result = win.__TAURI_ISOLATION_HOOK__(payload);
        expect(result).toBe(payload);
    });

    it("rejects unknown commands", () => {
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "exfiltrate", data: "secret" })
        ).toThrow(/not in allowlist/);
    });

    it("rejects missing cmd", () => {
        expect(() => win.__TAURI_ISOLATION_HOOK__({})).toThrow(/cmd.*string/);
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "" })
        ).toThrow(/cmd.*string/);
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: 42 })
        ).toThrow(/cmd.*string/);
    });

    it("rejects non-object payload", () => {
        expect(() => win.__TAURI_ISOLATION_HOOK__(null)).toThrow(/object/);
        expect(() => win.__TAURI_ISOLATION_HOOK__("string")).toThrow(/object/);
        expect(() => win.__TAURI_ISOLATION_HOOK__(42)).toThrow(/object/);
    });

    it("rejects greet with missing name", () => {
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "greet" })
        ).toThrow(/name.*string/);
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "greet", payload: {} })
        ).toThrow(/name.*string/);
    });

    it("rejects greet with non-string name", () => {
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "greet", payload: { name: 42 } })
        ).toThrow(/name.*string/);
    });

    it("rejects greet with empty name", () => {
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "greet", payload: { name: "" } })
        ).toThrow(/length/);
    });

    it("rejects greet with oversized name (>200 chars)", () => {
        const big = "a".repeat(201);
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "greet", payload: { name: big } })
        ).toThrow(/length/);
    });

    it("rejects greet with control chars (ANSI injection)", () => {
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "greet", payload: { name: "Jordi\x1b[31m" } })
        ).toThrow(/control chars/);
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "greet", payload: { name: "Jordi\nEvil" } })
        ).toThrow(/control chars/);
    });

    it("ignores Tauri-infra keys (callback, error, __*) during arg validation", () => {
        const payload = {
            cmd: "greet",
            payload: { name: "Jordi" },
            callback: 123,
            error: 456,
            __tauriModule: "some-module",
            __internal: "whatever",
        };
        expect(() => win.__TAURI_ISOLATION_HOOK__(payload)).not.toThrow();
    });

    // S04 F074 — ALLOWED is Object.create(null); prototype lookups return undefined.
    it("blocks prototype pollution lookups (constructor, __proto__, toString)", () => {
        // Without Object.prototype, these keys cannot find anything in ALLOWED.
        expect(win.__isolationAllowed.constructor).toBeUndefined();
        expect(Object.getPrototypeOf(win.__isolationAllowed)).toBeNull();
        expect(win.__isolationAllowed.toString).toBeUndefined();
        expect(win.__isolationAllowed.hasOwnProperty).toBeUndefined();

        // And the hook explicitly rejects attempts to call them as commands.
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "constructor" })
        ).toThrow(/not in allowlist/);
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "toString" })
        ).toThrow(/not in allowlist/);
    });

    // C02 — quit_app (S05) takes no payload and must pass the hook.
    // get_auth_token removed (Codex audit 2026-05-06): exposed Bearer via XSS.
    it("rejects removed get_auth_token command", () => {
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "get_auth_token" })
        ).toThrow(/not in allowlist/);
    });

    it("accepts quit_app (S05 F043) with no args", () => {
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({ cmd: "quit_app" })
        ).not.toThrow();

        // Tauri-infra keys present (real Tauri 2 shape) — must also pass
        expect(() =>
            win.__TAURI_ISOLATION_HOOK__({
                cmd: "quit_app",
                callback: 1,
                error: 2,
                __tauriModule: "core",
            })
        ).not.toThrow();
    });

    // C02 drift detection — CI fails if someone adds a #[tauri::command] to lib.rs
    // without updating the isolation allowlist. Reads generate_handler![] directly
    // from Rust code and verifies that each command has a validator in the allowlist.
    //
    // IMPORTANT: this test does not use `require()` (the file is ESM); it reuses
    // readFileSync + resolve already imported in module scope.
    //
    // NOTE: we do not call __TAURI_ISOLATION_HOOK__({ cmd }) because commands like `greet`
    // require args and would throw on payload validation — not on absence from allowlist.
    // We check directly against __isolationAllowed that the validator exists.
    //
    // B1 Sprint 0.18 (2026-04-21): fix regex bypass via commented decoy.
    // The old test used .match() (without /g) and did not strip comments, so
    // a decoy comment `// generate_handler![greet]` BEFORE the real invocation
    // caused the regex to capture ONLY the decoy. A new command without a validator in
    // the allowlist would be registered and the test would pass silently (B1 bypass).
    //
    // Fix applied:
    //   1. Strip Rust comments (// and /* */) BEFORE the regex — simple but sufficient
    //      for the starter pattern (does not handle nested block comments, Rust allows them
    //      but the starter code does not use them).
    //   2. matchAll(/g) to capture ALL occurrences of generate_handler![...].
    //   3. Expect exactly 1 (Tauri pattern: single invocation per invoke_handler).
    //   4. Union commands from all captures and verify each against allowlist.
    it("allowlist covers all registered handler commands (drift check — comment-immune)", () => {
        const libRsPath = resolve(__dirname, "../src-tauri/src/lib.rs");
        const libRsRaw = readFileSync(libRsPath, "utf-8");

        // Strip Rust comments BEFORE the regex to immunize against decoys:
        //   - Block comments: /* ... */ (non-greedy, multiline)
        //   - Line comments:  // until end of line
        // Order matters: block first (may contain //), then line.
        const libRs = libRsRaw
            .replace(/\/\*[\s\S]*?\*\//g, "")   // block comments
            .replace(/\/\/[^\n]*/g, "");          // line comments

        // Capture ALL occurrences of generate_handler![...] (flag /g).
        const matches = [...libRs.matchAll(/generate_handler!\[([^\]]+)\]/g)];

        // Exactly 1 invocation expected (Tauri pattern for this app).
        // If 0 → the macro has disappeared (regression).
        // If >1 → unexpected situation; the drift check cannot guarantee
        //   coverage without manual analysis → explicit fail with clear message.
        expect(
            matches.length,
            "expected exactly one generate_handler! invocation in lib.rs " +
            "(0 = macro disappeared, >1 = multiple invocations not handled)"
        ).toBe(1);

        const cmds = matches[0][1]
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);

        // Must have at least the 3 current commands (greet, quit_app,
        // fetch_from_sidecar). get_auth_token removed (Codex audit 2026-05-06).
        expect(cmds.length).toBeGreaterThanOrEqual(3);

        // Every command registered in the Rust handler must have a validator in the allowlist.
        // We use __isolationAllowed directly to avoid args validation
        // (which would legitimately fail for commands requiring a payload like greet).
        for (const cmd of cmds) {
            expect(
                typeof win.__isolationAllowed[cmd],
                `Command '${cmd}' is registered in generate_handler! but missing from isolation allowlist`
            ).toBe("function");
        }
    });

    // B1 mutation test — commented decoy vector + extra command without allowlist.
    // This test verifies that the B1 fix (comment-strip + matchAll) is NOT theatre:
    // it simulates the attack vector directly at text level and checks that the detection
    // logic fails correctly when there is an extra command without a validator.
    //
    // IMPORTANT: this test does NOT read lib.rs from disk — it operates on a synthetic
    // string that replicates the attack pattern. Does not modify any real file.
    it("drift check rejects decoy comment hiding an extra command (B1 mutation vector)", () => {
        // Simulates poisoned lib.rs: commented decoy + real extra command without allowlist.
        const poisonedLibRs = `
// S05 F043 + S10 F013/F020 + security C25: registered commands.
// redteam legacy snippet (DO NOT REMOVE): generate_handler![greet, quit_app, get_auth_token, fetch_from_sidecar]
        .invoke_handler(tauri::generate_handler![
            greet,
            quit_app,
            get_auth_token,
            fetch_from_sidecar,
            evil_cmd
        ])
`;

        // Apply the same strip + matchAll pipeline as the real test.
        const stripped = poisonedLibRs
            .replace(/\/\*[\s\S]*?\*\//g, "")
            .replace(/\/\/[^\n]*/g, "");

        const matches = [...stripped.matchAll(/generate_handler!\[([^\]]+)\]/g)];
        expect(matches.length).toBe(1);

        const cmds = matches[0][1]
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);

        // evil_cmd must be present in the extracted commands (the strip removed the decoy,
        // and matchAll captured the real invocation that contains evil_cmd).
        expect(cmds).toContain("evil_cmd");

        // evil_cmd is NOT in the allowlist — we simulate the check the drift test would do.
        // We use win.__isolationAllowed from beforeEach (real app allowlist).
        const unallowlisted = cmds.filter(
            (cmd) => typeof win.__isolationAllowed[cmd] !== "function"
        );
        // Must have at least 1 command not in the allowlist (evil_cmd).
        expect(
            unallowlisted.length,
            `Expected at least one command missing from allowlist (evil_cmd), got none. ` +
            `Commands extracted: ${cmds.join(", ")}`
        ).toBeGreaterThan(0);
        expect(unallowlisted).toContain("evil_cmd");
    });

    // Security C25 — fetch_from_sidecar: allowlist validator + defense in depth.
    // The main webview does not touch the token; Rust injects the Bearer. The Isolation
    // Hook validates URL + method + body before letting it pass to Rust.
    describe("fetch_from_sidecar (security C25)", () => {
        it("accepts well-formed sidecar GET", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api/v1/chat",
                        method: "GET",
                    },
                })
            ).not.toThrow();
        });

        it("accepts well-formed sidecar POST with body", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api/v1/chat",
                        method: "POST",
                        body: JSON.stringify({ prompt: "hello" }),
                    },
                })
            ).not.toThrow();
        });

        it("rejects non-sidecar URL (external host)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://evil.example.com/steal",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
        });

        it("rejects https scheme (sidecar is HTTP-only localhost)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "https://127.0.0.1:8000/api",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
        });

        it("rejects file:// scheme (directory traversal via protocol)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "file:///etc/passwd",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
        });

        it("rejects missing url", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: { method: "GET" },
                })
            ).toThrow(/url.*string/);
        });

        it("rejects non-string url", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: { url: 42, method: "GET" },
                })
            ).toThrow(/url.*string/);
        });

        it("rejects oversized URL (>2048)", () => {
            const big = "http://127.0.0.1:8000/" + "a".repeat(2100);
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: { url: big, method: "GET" },
                })
            ).toThrow(/too long/);
        });

        it("rejects control chars in URL (log spoof)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api\x1b[31mEVIL",
                        method: "GET",
                    },
                })
            ).toThrow(/control chars/);
        });

        it("rejects invalid method", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api",
                        method: "TRACE",
                    },
                })
            ).toThrow(/method/);
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api",
                        method: "CONNECT",
                    },
                })
            ).toThrow(/method/);
        });

        it("rejects body on GET (RFC semantics)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api",
                        method: "GET",
                        body: "ignored",
                    },
                })
            ).toThrow(/POST\/PUT/);
        });

        it("rejects oversized body (>1MB)", () => {
            const bigBody = "x".repeat(1024 * 1024 + 1);
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api",
                        method: "POST",
                        body: bigBody,
                    },
                })
            ).toThrow(/body too large/);
        });

        // ─────────────────────────────────────────────────────────────────
        // B2 Sprint 0.18 (2026-04-21) — structural URL parse
        //
        // Claude-ext + Codex red team (consensus 2/2 AIs, P1 latent Phase 2)
        // detected 4 bypass vectors in the old `startsWith("http://127.0.0.1:")`.
        // These tests exercise the fix (structural parse via `new URL(...)`).
        // Mutation test: with the old `startsWith` all these vectors passed.
        // ─────────────────────────────────────────────────────────────────

        it("B2 rejects userinfo bypass (4 red team PoC vectors)", () => {
            // Vector 1: userinfo with fake port, real host evil.example.com
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000@evil.example.com/exfil",
                        method: "GET",
                    },
                })
            ).toThrow(); // any error (sidecar/userinfo); what matters: it does not pass
            // Vector 2: userinfo arbitrari → attacker.tld
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:anything@attacker.tld/steal",
                        method: "GET",
                    },
                })
            ).toThrow();
            // Vector 3: userinfo → external IP 192.0.2.1 (TEST-NET-1)
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:0000000@192.0.2.1/ssrf",
                        method: "GET",
                    },
                })
            ).toThrow();
            // Vector 4: userinfo with empty password → evil.tld
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://user:@evil.tld:8000/",
                        method: "GET",
                    },
                })
            ).toThrow();
        });

        it("B2 rejects userinfo on valid host 127.0.0.1 (specifically USERINFO)", () => {
            // URL with userinfo but real host is 127.0.0.1 → must be rejected
            // by the userinfo check (not the host check).
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://user:pass@127.0.0.1:8000/api",
                        method: "GET",
                    },
                })
            ).toThrow(/userinfo/);
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://admin@127.0.0.1:8000/api",
                        method: "GET",
                    },
                })
            ).toThrow(/userinfo/);
        });

        it("B2 accepts valid sidecar URL (baseline)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:8000/api/v1/chat",
                        method: "GET",
                    },
                })
            ).not.toThrow();
            // Different port also OK (no expected_port in the JS validator)
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1:9876/api?foo=1",
                        method: "POST",
                        body: "{}",
                    },
                })
            ).not.toThrow();
        });

        it("B2 rejects localhost hostname (not literal 127.0.0.1)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://localhost:8000/api",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
        });

        it("B2 rejects IPv6 loopback (not literal 127.0.0.1)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://[::1]:8000/api",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
            // IPv4-mapped IPv6 also
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://[::ffff:127.0.0.1]:8000/api",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
        });

        it("B2 rejects missing explicit port", () => {
            // URL without explicit port — `new URL(...)` interprets port="" (default http=80)
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "http://127.0.0.1/api",
                        method: "GET",
                    },
                })
            ).toThrow(/explicit port/);
        });

        it("B2 rejects wrong scheme (https, file, ftp)", () => {
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "https://127.0.0.1:8000/api",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
            expect(() =>
                win.__TAURI_ISOLATION_HOOK__({
                    cmd: "fetch_from_sidecar",
                    payload: {
                        url: "ftp://127.0.0.1:8000/",
                        method: "GET",
                    },
                })
            ).toThrow(/sidecar/);
        });
    });
});
