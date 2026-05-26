//! Auth token baseline — Sprint S10 (F013/F020) + security C25 (2026-04-21).
//!
//! UUID v4 generated once per process launch. 128 bits of entropy,
//! not reusable between restarts. The token lives exclusively on the Rust side.
//!
//! Zero Trust local: without this token, any process on localhost could
//! perform POST /admin/system/shutdown or queries to Qdrant/LLM (F013).
//!
//! # Security C25 — Bearer token never exposed to the webview
//!
//! The frontend calls `fetch_from_sidecar` and Rust injects the
//! `Authorization: Bearer <token>` before sending the request to the sidecar.
//! The webview never "sees" the raw token. `get_auth_token` removed (audit 2026-05-06).

use url::Url;

/// B2 Sprint 0.18 (2026-04-21) — structural sidecar URL validation.
///
/// The old `url.starts_with("http://127.0.0.1:")` accepted 4 bypass vectors
/// documented by security audit (consensus):
///
/// 1. `http://127.0.0.1:8000@evil.example.com/exfil` — userinfo hijack (real host evil.tld)
/// 2. `http://127.0.0.1:anything@attacker.tld/steal` — userinfo with password
/// 3. `http://127.0.0.1:0000000@192.0.2.1/ssrf` — userinfo + external IP
/// 4. `http://127.0.0.1:65536/` — invalid port (overflow)
///
/// When Phase 2 activates `reqwest`, the first userinfo-hijack call will send the body +
/// `Authorization: Bearer <token>` to the attacker's domain → credential leak + SSRF.
///
/// Fix: `url::Url::parse` decomposes authority into host/port/username/password per
/// RFC 3986 §3.2.1. We validate each field explicitly:
/// - scheme == "http" (sidecar is not HTTPS, localhost)
/// - host_str() == Some("127.0.0.1") (no `localhost`, no `[::ffff:127.0.0.1]` mapped)
/// - port present (explicit, no default 80); if `expected_port` is Some, it must match
/// - username empty + password absent (rejects the 4 userinfo vectors)
///
/// # Port policy
///
/// `expected_port = Some(p)` requires an exact match. This is the strict Phase 2 mode
/// when the `SidecarPort` state is available.
///
/// `expected_port = None` accepts any valid explicit port (no default, no overflow).
/// This is the pre-Phase 2 mode where the port is runtime-configurable and we do not
/// yet have the state injected into the command. The remaining validations (scheme, host,
/// userinfo) remain identical — the userinfo bypass is blocked in both modes.
///
/// # Contract
/// - `Ok(())` → URL passes all validations.
/// - `Err(&'static str)` → rejected with a static error code (log-friendly, no-alloc).
pub(crate) fn validate_sidecar_url(
    url_str: &str,
    expected_port: Option<u16>,
) -> Result<(), &'static str> {
    let parsed = Url::parse(url_str).map_err(|_| "INVALID_URL")?;

    // Exact scheme — sidecar is HTTP-only localhost (HTTPS is overkill for local IPC
    // and would imply cert management).
    if parsed.scheme() != "http" {
        return Err("INVALID_SCHEME");
    }

    // Exact host — only accepts literal "127.0.0.1". Rejects:
    //   - `localhost` (variable DNS resolution, may point outside 127.0.0.1 on custom setups)
    //   - `[::1]` (IPv6 loopback — although semantically equivalent, it is not the
    //     format the sidecar serves; we avoid interpretation branches)
    //   - `[::ffff:127.0.0.1]` (IPv4-mapped IPv6 — different representation, not literal "127.0.0.1")
    //   - Any other host with/without userinfo
    if parsed.host_str() != Some("127.0.0.1") {
        return Err("INVALID_HOST");
    }

    // Userinfo rejected — known red team B2 bypass vector. RFC 3986 §3.2.1:
    // `authority = [userinfo "@"] host [":" port]`. If `url::Url::parse` finds
    // userinfo, username() returns the segment before `:` and password() returns
    // Some(segment_after) or None.
    //
    // IMPORTANT: this check runs BEFORE the port check because
    // the 4 PoC vectors place the fake port in the userinfo. Once
    // userinfo is rejected, the real host (post-@) has already been caught by the previous check.
    if !parsed.username().is_empty() || parsed.password().is_some() {
        return Err("USERINFO_NOT_ALLOWED");
    }

    // Explicit port required. `url::Url::port()` returns `None` if the port is not
    // present OR if it matches the scheme default (80 for http); in both cases
    // we reject (we want an explicit port URL, never default).
    //
    // If `expected_port` is Some, we also require a match. If None, we accept
    // any valid explicit port (pre-Phase 2 mode, see § Port policy).
    match (parsed.port(), expected_port) {
        (None, _) => return Err("INVALID_PORT"),
        (Some(actual), Some(expected)) if actual != expected => {
            return Err("INVALID_PORT");
        }
        _ => {}
    }

    Ok(())
}

/// F5 Sprint 0.18 (2026-04-21) — pure helper for HTTP method validation
/// of `fetch_from_sidecar`. Previously this logic lived inline in the command and the
/// test `fetch_from_sidecar_method_allowlist` replicated it locally, which
/// made it theatre (mutation testing of the command was not detected).
///
/// Allowlist:
/// - `GET`/`HEAD`/`DELETE` — no body (return `METHOD_DOES_NOT_ACCEPT_BODY`
///   if the caller attaches one).
/// - `POST`/`PUT` — optional body.
/// - The rest (`TRACE`, `CONNECT`, `OPTIONS`, `PATCH`, lowercase variants, ...)
///   → `INVALID_METHOD`.
///
/// # Mutation testing
///
/// If someone adds a method to the allowlist (e.g. `TRACE`), the test
/// `t5_method_allowlist_rejects_non_safe_methods_via_real_helper` fails.
/// If someone removes the `body.is_some()` check for bodyless methods, the test
/// `t5_method_allowlist_rejects_body_on_get_via_real_helper` fails.
pub(crate) fn validate_sidecar_method(
    method: &str,
    body: Option<&str>,
) -> Result<(), &'static str> {
    match method {
        "GET" | "HEAD" | "DELETE" => {
            if body.is_some() {
                return Err("METHOD_DOES_NOT_ACCEPT_BODY");
            }
            Ok(())
        }
        "POST" | "PUT" => Ok(()),
        _ => Err("INVALID_METHOD"),
    }
}

pub struct AuthToken(pub String);

impl AuthToken {
    pub(crate) fn generate() -> Self {
        AuthToken(uuid::Uuid::new_v4().to_string())
    }
}

/// Web UI API key for auto-login (distinct from the Tauri↔sidecar Bearer token).
///
/// The Bearer token (AuthToken) is the Tauri IPC credential — it never reaches the
/// webview (Security C25). The ApiKey is the credential the web UI uses to authenticate
/// against the server-nexe HTTP API. Rust injects it via the navigation URL query string;
/// the canonical app.js (plugins/web_ui_module/ui/app.js, served by the sidecar) reads
/// it once on first load and stores it in localStorage as `nexe_api_key`.
///
/// Passed to the sidecar as `NEXE_API_KEY` env var so server-nexe can accept it without
/// requiring the user to enter a key manually (Fase 2 auto-login).
pub struct ApiKey(pub String);

impl ApiKey {
    pub(crate) fn generate() -> Self {
        ApiKey(uuid::Uuid::new_v4().to_string())
    }
}

/// Path prefixes that the frontend must NOT reach via `fetch_from_sidecar`.
///
/// These endpoints are managed exclusively by Rust lifecycle commands (e.g.
/// `graceful_quit` calls /shutdown directly). Allowing the webview to trigger
/// them would let any plugin or XSS vector shut down the sidecar.
///
/// F3.1 BUG-NB-25 (2026-05-18): the previous list compared `path` against
/// these strings with `.contains(&path)`, i.e. exact equality. An attacker
/// could trivially bypass the guard with `/api/v1/system/shutdown/` (trailing
/// slash), `/API/V1/system/SHUTDOWN` (case variation),
/// `/api/v1/system/shutdown?foo=bar` (query string) or
/// `/api/v1/system/shutdown/x` (suffix). The guard is now a prefix match
/// over a normalised path (lower-cased, query/fragment stripped, trailing
/// slash trimmed) and covers both the legacy `/api/v1/...` mount and the
/// `/admin/...` mount introduced in F2.5.
///
/// Phase 2 migration: replace this blocklist with an explicit path allowlist
/// once the server-nexe API surface is stable and fully enumerated.
const SIDECAR_BLOCKED_PATH_PREFIXES: &[&str] = &[
    "/api/v1/system/shutdown",
    "/api/v1/system/restart",
    "/admin/system/shutdown",
    "/admin/system/restart",
    // The `/v1` mount itself currently exposes no lifecycle endpoints, but
    // anyone adding `/v1/system/shutdown` later (mirroring `/admin/system/*`)
    // would silently widen the attack surface. Block them defensively so
    // future endpoint additions do not regress this guard.
    "/v1/system/shutdown",
    "/v1/system/restart",
];

/// Normalise a request path for blocklist matching:
/// strip query string, strip fragment, trim trailing slash, lowercase.
fn normalize_path_for_blocklist(path: &str) -> String {
    let no_query = path.split('?').next().unwrap_or(path);
    let no_fragment = no_query.split('#').next().unwrap_or(no_query);
    let trimmed = no_fragment.trim_end_matches('/');
    trimmed.to_ascii_lowercase()
}

/// Path-level guard for `fetch_from_sidecar`.
///
/// Returns `Err("BLOCKED_PATH")` whenever the normalised path matches any
/// entry in `SIDECAR_BLOCKED_PATH_PREFIXES` either exactly or as a directory
/// prefix (`prefix` itself or `prefix + "/..."`). Called after
/// `validate_sidecar_url` has already confirmed host/port/scheme.
pub(crate) fn validate_sidecar_path(path: &str) -> Result<(), &'static str> {
    let normalised = normalize_path_for_blocklist(path);
    for prefix in SIDECAR_BLOCKED_PATH_PREFIXES {
        if normalised == *prefix || normalised.starts_with(&format!("{prefix}/")) {
            return Err("BLOCKED_PATH");
        }
    }
    Ok(())
}

/// **Phase 2 Skeleton** — `fetch_from_sidecar` intercepts calls to the
/// server-nexe sidecar and injects the `Authorization: Bearer <token>` on the Rust side,
/// so that the main webview never touches the raw token.
///
/// # Contract
///
/// - `url` must start with `http://127.0.0.1:` followed by the sidecar port
///   (dynamically assigned at setup). Any other scheme/host returns
///   `Err("INVALID_URL")` — prevents turning it into an open proxy.
/// - `method` ∈ {"GET", "POST", "PUT", "DELETE", "HEAD"}. The rest returns
///   `Err("INVALID_METHOD")`.
/// - `body` only valid for `POST`/`PUT`; other methods must send `None`.
///
/// # Status (Phase 0/1)
///
/// Returns `Err("NOT_IMPLEMENTED")`. Activating in Phase 2 requires:
/// 1. Dep `reqwest = { version = "0.12", default-features = false, features = ["rustls-tls", "json"] }`
///    in `Cargo.toml` (excluded from W5 of this sprint).
/// 2. A `SidecarPort` state (port assigned at `setup()`).
/// 3. URL validator against `format!("http://127.0.0.1:{port}")`.
/// 4. Real request with `reqwest::Client` + header `Authorization: Bearer {token}`.
///
/// # Security C25
///
/// This command is the **only** IPC the frontend should use to talk to the sidecar.
/// The Isolation Hook (`isolation-frame/isolation.js`) must validate the URL + method
/// before letting it pass to Rust. In Phase 2, `get_auth_token` will be removed from
/// `invoke_handler` and the deprecation will become a hard error.
/// Real `fetch_from_sidecar` implementation (2026-05-02).
///
/// Async to allow non-blocking `reqwest::Client::send().await`. Accepted as
/// `#[tauri::command]` directly — Tauri 2 supports async commands via
/// the tokio runtime it already includes.
///
/// # Contract
///
/// - `auth_state`: bearer token injected into the header (never exposed to the frontend).
/// - `port_state`: sidecar port — strictly required (vs `None` pre-Phase 2)
///   by `validate_sidecar_url`. Defense in depth: a URL to the wrong port
///   (perhaps another localhost service) is rejected with `INVALID_PORT`.
/// - `url` / `method` / `body`: contract already documented in the previous skeleton.
///
/// # Errors
///
/// Returns `Err(String)` with static codes (`INVALID_URL`, `INVALID_HOST`,
/// `INVALID_METHOD`, `METHOD_DOES_NOT_ACCEPT_BODY`) or dynamic codes
/// (`reqwest send: ...`, `body decode: ...`) when the error comes from the HTTP client.
#[tauri::command]
pub(crate) async fn fetch_from_sidecar(
    auth_state: tauri::State<'_, AuthToken>,
    port_state: tauri::State<'_, crate::SidecarPort>,
    http: tauri::State<'_, crate::HttpClient>,
    url: String,
    method: String,
    body: Option<String>,
) -> Result<String, String> {
    // URL validation against the real sidecar port (strict).
    // F5.3.1: `port_state.get()` is a lock-free atomic read; the port may have
    // been updated by a recent `restart_sidecar` — we always validate against
    // the current value.
    if let Err(code) = validate_sidecar_url(&url, Some(port_state.get())) {
        tracing::warn!(
            target: "auth::fetch_from_sidecar",
            %url,
            reject_code = code,
            "rejected non-sidecar URL"
        );
        return Err(code.into());
    }

    // Method validation (allowlist GET/HEAD/DELETE/POST/PUT, body only
    // POST/PUT). Pure helper F5 Sprint 0.18.
    if let Err(code) = validate_sidecar_method(&method, body.as_deref()) {
        return Err(code.into());
    }

    // Path-level blocklist — reject Rust-managed endpoints (e.g. /shutdown).
    // URL was already validated above, so a second parse cannot fail.
    let parsed_for_path = Url::parse(&url).map_err(|_| "INVALID_URL".to_string())?;
    if let Err(code) = validate_sidecar_path(parsed_for_path.path()) {
        tracing::warn!(
            target: "auth::fetch_from_sidecar",
            %url,
            reject_code = code,
            "rejected blocked sidecar path"
        );
        return Err(code.into());
    }

    // Bug fix: shared client from state (registered at setup()). `Client`
    // internally is `Arc<ClientRef>` → `.clone()` is cheap (~ref count bump).
    // An earlier patch did `Client::builder().build()` inside this function,
    // creating a NEW client per invoke → connection pool leak (fds), DNS resolver
    // re-init, TLS session cache cleared.
    let client = http.0.clone();
    let http_method = reqwest::Method::from_bytes(method.as_bytes())
        .map_err(|_| "INVALID_METHOD".to_string())?;
    let token = &auth_state.0;
    let mut req = client
        .request(http_method, &url)
        .header("Authorization", format!("Bearer {token}"));
    if let Some(b) = body {
        // POST/PUT — raw body. The sidecar decides the Content-Type per
        // the endpoint (FastAPI route handlers).
        req = req.body(b);
    }
    let resp = req
        .send()
        .await
        .map_err(|e| format!("reqwest send: {e}"))?;

    // F3.1 BUG-NA-2 (OOM): cap response body size at 10 MiB before draining it
    // into memory. A misbehaving (or malicious) sidecar could otherwise return
    // a multi-GB body and exhaust the Tauri process memory. 10 MiB covers the
    // worst-case JSON streaming payloads observed during normal use.
    const MAX_RESPONSE_BYTES: u64 = 10 * 1024 * 1024;
    if let Some(declared) = resp.content_length() {
        if declared > MAX_RESPONSE_BYTES {
            return Err(format!(
                "body too large: Content-Length {declared} exceeds {MAX_RESPONSE_BYTES} bytes"
            ));
        }
    }
    let bytes = resp
        .bytes()
        .await
        .map_err(|e| format!("body decode: {e}"))?;
    if bytes.len() as u64 > MAX_RESPONSE_BYTES {
        return Err(format!(
            "body too large: read {} bytes (cap {})",
            bytes.len(),
            MAX_RESPONSE_BYTES
        ));
    }
    String::from_utf8(bytes.to_vec()).map_err(|e| format!("body utf8: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    // ─────────────────────────────────────────────────────────────────
    // B2 Sprint 0.18 (2026-04-21) — `validate_sidecar_url` tests
    //
    // Security audit (P1 latent Phase 2): detected 4 bypass vectors in the old
    // `starts_with("http://127.0.0.1:")`.
    // These tests call `validate_sidecar_url` directly (the real production
    // function) with the PoC vectors — if someone reverts the code to
    // `starts_with`, mutation testing (pre-fix) shows FAIL on all of them.
    // ─────────────────────────────────────────────────────────────────

    /// B2 — The 4 red team PoC vectors (userinfo bypass) must return an error
    /// (none of them should pass `Ok(())`). With the old `starts_with`
    /// all of these passed (empirical red team verdict 2026-04-21).
    ///
    /// Security invariant: **all PoC vectors must be `Err(_)`**. The specific
    /// error code (INVALID_HOST, USERINFO_NOT_ALLOWED, etc.) depends on check order;
    /// `url::Url::parse` decomposes authority into parts, so a URL like
    /// `http://127.0.0.1:8000@evil.tld/` has host_str="evil.tld" and
    /// userinfo="127.0.0.1:8000" — the first check that fires is INVALID_HOST,
    /// which also correctly rejects the vector. The important thing is that it does not pass.
    #[test]
    fn validate_sidecar_url_rejects_userinfo() {
        let vectors = [
            (
                "http://127.0.0.1:8000@evil.example.com/exfil",
                "vector 1: userinfo host-hijack",
            ),
            (
                "http://127.0.0.1:anything@attacker.tld/steal",
                "vector 2: userinfo+password→attacker.tld",
            ),
            (
                "http://127.0.0.1:0000000@192.0.2.1/ssrf",
                "vector 3: userinfo→external IP SSRF",
            ),
            (
                "http://user:@evil.tld:8000/",
                "vector 4: userinfo with empty password",
            ),
        ];

        for (url, msg) in vectors.iter() {
            let result = validate_sidecar_url(url, None);
            assert!(
                result.is_err(),
                "{msg} must be rejected, got {result:?} for URL {url}"
            );
        }
    }

    /// B2 — Purely userinfo case (real host is 127.0.0.1 + userinfo present):
    /// must return specifically `USERINFO_NOT_ALLOWED`. This validates that the
    /// userinfo check fires when the rest of the checks pass.
    #[test]
    fn validate_sidecar_url_userinfo_on_valid_host_rejects_specifically() {
        // URL with userinfo but real host 127.0.0.1 (no @ after). This
        // is the case that specifically exercises the USERINFO_NOT_ALLOWED check.
        // Format: `http://user:pass@127.0.0.1:8000/`
        assert_eq!(
            validate_sidecar_url("http://user:pass@127.0.0.1:8000/api", None),
            Err("USERINFO_NOT_ALLOWED"),
            "userinfo on valid host 127.0.0.1 must return USERINFO_NOT_ALLOWED"
        );
        // Username only
        assert_eq!(
            validate_sidecar_url("http://admin@127.0.0.1:8000/api", None),
            Err("USERINFO_NOT_ALLOWED"),
            "username alone on valid host must return USERINFO_NOT_ALLOWED"
        );
    }

    /// B2 — Correct sidecar URL (no userinfo, exact host, explicit port)
    /// passes all validations.
    #[test]
    fn validate_sidecar_url_accepts_exact_localhost() {
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1:8000/api/v1/chat", None),
            Ok(()),
            "benign sidecar URL must pass"
        );
        // With matching explicit expected_port also passes
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1:8000/api/v1/chat", Some(8000)),
            Ok(())
        );
        // With query string + complex path still OK
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1:9000/api?v=1&id=42", None),
            Ok(())
        );
    }

    /// B2 — `localhost` hostname (not literal IP) must be rejected. The sidecar
    /// binds to literal 127.0.0.1; DNS resolution of `localhost` may vary
    /// (custom /etc/hosts setups, Docker bridges).
    #[test]
    fn validate_sidecar_url_rejects_localhost_hostname() {
        assert_eq!(
            validate_sidecar_url("http://localhost:8000/api", None),
            Err("INVALID_HOST"),
            "hostname `localhost` is not literal 127.0.0.1"
        );
    }

    /// B2 — IPv4-mapped IPv6 `[::ffff:127.0.0.1]` must be rejected.
    /// Semantically equivalent to 127.0.0.1 but `url::Url::host_str` returns the
    /// canonical IPv6 representation, not the literal "127.0.0.1".
    #[test]
    fn validate_sidecar_url_rejects_ipv6_mapped() {
        assert_eq!(
            validate_sidecar_url("http://[::ffff:127.0.0.1]:8000/", None),
            Err("INVALID_HOST"),
            "IPv4-mapped IPv6 is not literal \"127.0.0.1\""
        );
        // Also ::1 (pure IPv6 loopback)
        assert_eq!(
            validate_sidecar_url("http://[::1]:8000/", None),
            Err("INVALID_HOST"),
            "IPv6 loopback `::1` is not literal 127.0.0.1"
        );
    }

    /// B2 — HTTPS scheme rejected. The sidecar is HTTP-only localhost.
    #[test]
    fn validate_sidecar_url_rejects_wrong_scheme() {
        assert_eq!(
            validate_sidecar_url("https://127.0.0.1:8000/", None),
            Err("INVALID_SCHEME"),
            "https rejected — sidecar is HTTP-only"
        );
        assert_eq!(
            validate_sidecar_url("file:///etc/passwd", None),
            Err("INVALID_SCHEME"),
            "file:// rejected (directory traversal via protocol)"
        );
        assert_eq!(
            validate_sidecar_url("ftp://127.0.0.1:8000/", None),
            Err("INVALID_SCHEME")
        );
    }

    /// B2 — `expected_port = Some(p)` requires exact match. Different port
    /// than expected returns `Err("INVALID_PORT")`.
    #[test]
    fn validate_sidecar_url_rejects_wrong_port() {
        // Port different from expected
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1:9999/api", Some(8000)),
            Err("INVALID_PORT"),
            "port 9999 ≠ expected 8000"
        );
        // Same URL with correct expected_port passes
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1:9999/api", Some(9999)),
            Ok(())
        );
    }

    /// B2 — Missing port rejected. `url::Url::port()` returns `None` when not
    /// explicit (e.g. `http://127.0.0.1/` → default http port 80, treated as None).
    /// We always want an explicit port (no ambiguity).
    #[test]
    fn validate_sidecar_url_rejects_missing_port() {
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1/api", None),
            Err("INVALID_PORT"),
            "URL without explicit port rejected"
        );
    }

    /// B2 — Red team PoC vector 4: `http://127.0.0.1:65536/` port overflow.
    /// `url::Url::parse` must return a parse error directly (port > 65535
    /// is invalid per RFC 3986).
    #[test]
    fn validate_sidecar_url_rejects_port_overflow() {
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1:65536/", None),
            Err("INVALID_URL"),
            "port 65536 (overflow) must fail at parse"
        );
        assert_eq!(
            validate_sidecar_url("http://127.0.0.1:99999/", None),
            Err("INVALID_URL"),
            "port > u16::MAX must fail at parse"
        );
    }

    /// F5 Sprint 0.18 (2026-04-21) — T5b rewritten for real mutation testing.
    ///
    /// **Test history:**
    /// - Original version (pre-F5) was THEATRE: the test defined its own
    ///   `fn validate_method(...)` and tested it. The real command logic
    ///   `fetch_from_sidecar` was a copy of the same code, but if someone
    ///   added a method to the real allowlist (e.g. `TRACE`), the test stayed
    ///   green because the test's `validate_method` did not touch the real one.
    ///   Empirically verified: command mutation → test ok (theatre).
    /// - Identified empirically via local replication.
    ///
    /// **F5 refactor:** the real logic was extracted to
    /// `validate_sidecar_method(method: &str, body: Option<&str>) -> Result<(), &'static str>`
    /// in the `auth` module. The `fetch_from_sidecar` command calls the helper.
    ///
    /// **Rigorous mutation testing:**
    /// - Adding `TRACE` to the real allowlist makes
    ///   `t5_method_allowlist_rejects_non_safe_methods_via_real_helper` fail.
    /// - Removing the `body.is_some()` check for `GET` makes
    ///   `t5_method_allowlist_rejects_body_on_get_via_real_helper` fail.
    /// - No local replication: the test calls the real `validate_sidecar_method`.
    #[test]
    fn t5_method_allowlist_accepts_safe_methods_via_real_helper() {
        // Allowlisted methods. Each one exercises the real helper match.
        assert_eq!(validate_sidecar_method("GET", None), Ok(()));
        assert_eq!(validate_sidecar_method("HEAD", None), Ok(()));
        assert_eq!(validate_sidecar_method("DELETE", None), Ok(()));
        assert_eq!(validate_sidecar_method("POST", Some("{}")), Ok(()));
        assert_eq!(validate_sidecar_method("PUT", Some("{}")), Ok(()));
        // POST/PUT also accept body=None (body is optional).
        assert_eq!(validate_sidecar_method("POST", None), Ok(()));
        assert_eq!(validate_sidecar_method("PUT", None), Ok(()));
    }

    /// F5 Sprint 0.18 — NOT allowlisted methods rejected. Mutation: if
    /// someone adds `TRACE`/`CONNECT`/`OPTIONS`/`PATCH` to the real allowlist,
    /// this test fails.
    #[test]
    fn t5_method_allowlist_rejects_non_safe_methods_via_real_helper() {
        // Methods outside the allowlist — must return INVALID_METHOD.
        // Includes: non-allowlisted HTTP methods (TRACE/CONNECT/OPTIONS/PATCH),
        // case variants (lowercase/mixed), and CRLF/whitespace malformed injection.
        let rejected = [
            "TRACE",
            "CONNECT",
            "OPTIONS",
            "PATCH",
            "get",
            "Get",
            "post",
            "Post",
            "GET\r\nHost: evil",
            "",
            " ",
            "GET POST",
        ];
        for method in rejected {
            assert_eq!(
                validate_sidecar_method(method, None),
                Err("INVALID_METHOD"),
                "method {method:?} must be rejected as INVALID_METHOD (not allowlisted)"
            );
        }
    }

    /// F5 Sprint 0.18 — GET/HEAD/DELETE do not accept body. Mutation: if someone
    /// removes the `body.is_some()` check from the helper, this test fails.
    #[test]
    fn t5_method_allowlist_rejects_body_on_get_via_real_helper() {
        assert_eq!(
            validate_sidecar_method("GET", Some("{\"foo\":1}")),
            Err("METHOD_DOES_NOT_ACCEPT_BODY"),
            "GET with body must return METHOD_DOES_NOT_ACCEPT_BODY"
        );
        assert_eq!(
            validate_sidecar_method("HEAD", Some("payload")),
            Err("METHOD_DOES_NOT_ACCEPT_BODY"),
            "HEAD with body must return METHOD_DOES_NOT_ACCEPT_BODY"
        );
        assert_eq!(
            validate_sidecar_method("DELETE", Some("payload")),
            Err("METHOD_DOES_NOT_ACCEPT_BODY"),
            "DELETE with body must return METHOD_DOES_NOT_ACCEPT_BODY"
        );
    }

    // ─────────────────────────────────────────────────────────────────
    // Fase 2 prep — `validate_sidecar_path` blocklist tests
    // ─────────────────────────────────────────────────────────────────

    /// Blocked paths return BLOCKED_PATH. Mutation: removing the path from
    /// SIDECAR_BLOCKED_PATHS makes this test fail.
    #[test]
    fn validate_sidecar_path_blocks_shutdown() {
        assert_eq!(
            validate_sidecar_path("/api/v1/system/shutdown"),
            Err("BLOCKED_PATH"),
            "/shutdown must be blocked — Rust-managed lifecycle endpoint"
        );
    }

    /// F3.1 BUG-NB-25: bypass attempts that the previous exact-match guard
    /// allowed must now all return BLOCKED_PATH after the normalisation.
    #[test]
    fn validate_sidecar_path_blocks_normalised_bypasses() {
        let bypasses = [
            // Trailing slash.
            "/api/v1/system/shutdown/",
            // Case variations.
            "/API/V1/system/SHUTDOWN",
            "/Api/V1/System/Shutdown",
            // Query string + fragment.
            "/api/v1/system/shutdown?foo=bar",
            "/api/v1/system/shutdown#anchor",
            "/api/v1/system/shutdown/?token=abc",
            // Path suffix (would still hit the shutdown handler if mounted).
            "/api/v1/system/shutdown/extra",
            // Restart endpoint (server returns 501 in sidecar mode but the
            // client must never even attempt it).
            "/api/v1/system/restart",
            "/api/v1/system/restart/",
            "/API/v1/SYSTEM/restart",
            // F2.5 admin mount.
            "/admin/system/shutdown",
            "/admin/system/shutdown/",
            "/ADMIN/SYSTEM/SHUTDOWN",
            "/admin/system/restart",
            // Future-proof: bare /v1 mount must never expose shutdown/restart.
            "/v1/system/shutdown",
            "/v1/system/shutdown/",
            "/v1/system/restart",
            "/V1/SYSTEM/SHUTDOWN",
        ];
        for path in bypasses {
            assert_eq!(
                validate_sidecar_path(path),
                Err("BLOCKED_PATH"),
                "path {path:?} should be blocked after F3.1 BUG-NB-25 normalisation"
            );
        }
    }

    /// Allow-list sentinel: paths that contain "shutdown" or "restart" as a
    /// substring but live outside the system mount must keep working.
    #[test]
    fn validate_sidecar_path_does_not_overblock_substrings() {
        let allowed = [
            "/api/v1/knowledge/shutdown-procedures",
            "/api/v1/chat/restart-conversation",
            "/api/v1/memory/restart_flag",
        ];
        for path in allowed {
            assert_eq!(
                validate_sidecar_path(path),
                Ok(()),
                "substring match alone must not trigger BLOCKED_PATH for {path:?}"
            );
        }
    }

    /// Normal API paths pass through unchanged.
    #[test]
    fn validate_sidecar_path_allows_normal_paths() {
        let allowed = [
            "/api/v1/chat/",
            "/api/v1/chat/completions",
            "/api/v1/knowledge/search",
            "/admin/system/health",
            "/api/v1/memory/query",
            "/health/ready",
            "/",
        ];
        for path in allowed {
            assert_eq!(
                validate_sidecar_path(path),
                Ok(()),
                "path {path:?} should be allowed"
            );
        }
    }

    /// ApiKey generates distinct UUIDs (same property as AuthToken).
    #[test]
    fn api_key_generate_is_distinct() {
        let k1 = ApiKey::generate();
        let k2 = ApiKey::generate();
        assert_ne!(k1.0, k2.0, "each ApiKey must be a unique UUID v4");
        assert_eq!(k1.0.len(), 36, "UUID v4 is 36 chars with hyphens");
    }
}
