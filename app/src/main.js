// Frontend entry point — splash screen + plugin:// iframe firewall.
//
// Phase 1 (splash): polls the sidecar health endpoint to drive the user-
// facing "iniciant…" countdown. The post-ready navigation to the UI is
// owned by the Rust `poll_sidecar_health` task (lib.rs) — it has the
// api_key the JS layer doesn't (api_key is not exposed via a Tauri
// command, on purpose: onboarding_cmd.rs comment). If Rust times out
// without navigating, the JS shows the timeout error here.

import { fetchFromSidecar, getSidecarPort } from "./api/commands.js";
import { invoke } from "@tauri-apps/api/core";

// -----------------------------------------------------------------------------
// Plugin postMessage firewall (ADR-0007 / ADR-0008 baseline + S13 F034 hardening).
//
// Third-party plugins run inside `<iframe sandbox="allow-scripts">` — no
// `allow-same-origin`, so their origin is `"null"`. They communicate with the
// host only via `window.parent.postMessage`. This handler enforces:
//
//   1. event.source MUST be a registered plugin iframe (prevents XSS-injected
//      iframes from spoofing as a legitimate plugin — F034).
//   2. event.origin MUST be literal string "null" (sandboxed iframe).
//   3. action MUST be in the whitelist.
//   4. Drop silently (console.warn) anything else.
// -----------------------------------------------------------------------------

const ALLOWED_PLUGIN_ACTIONS = new Set([
  "plugin.ready",
  "plugin.resize",
  "plugin.notify",
]);

// S13 F034 — registry of trusted iframe.contentWindow references.
// Call `registerPluginIframe(iframe)` right after you mount `<iframe src="plugin://...">`.
const REGISTERED_IFRAME_SOURCES = new Set();

export function registerPluginIframe(iframe) {
  if (iframe && iframe.contentWindow) {
    REGISTERED_IFRAME_SOURCES.add(iframe.contentWindow);
  }
}

/** @internal — test only. Not part of the production API. */
export function unregisterPluginIframe(iframe) {
  if (iframe && iframe.contentWindow) {
    REGISTERED_IFRAME_SOURCES.delete(iframe.contentWindow);
  }
}

/** @internal — test only. Not part of the production API. */
/* c8 ignore next 3 */
export function _resetPluginFirewallForTest() {
  REGISTERED_IFRAME_SOURCES.clear();
}

// Tauri IPC messages (isolation + core) — empirically verified on Windows ARM64 2026-04-19:
//   - Encrypted payload: `event.data` is a string (AES-GCM blob)
//   - Plain IPC: `event.data` has shape `{ cmd, callback, error, options?, payload? }`
// ALL have `event.origin === "null"` (same as sandboxed plugins). We cannot filter by origin;
// we filter by the data shape that Tauri injects.
function isTauriIpcMessage(data) {
  if (typeof data === "string") return true; // encrypted blob
  if (data && typeof data === "object"
      && typeof data.cmd === "string"
      && typeof data.callback === "number"
      && typeof data.error === "number") {
    return true; // plain IPC shape
  }
  return false;
}

// Main handler — exported for unit tests. Returns the action name if accepted,
// or null if rejected. In production it's only called via addEventListener (side effects).
export function handlePluginMessage(event) {
  // 1. Silently ignore Tauri IPC (isolation AES-GCM blobs + plain commands).
  //    They are legitimate (encryption/dispatching) but unrelated to plugins.
  if (isTauriIpcMessage(event.data)) {
    return null;
  }

  // 2. F034: source validation — iframe registrat?
  if (!REGISTERED_IFRAME_SOURCES.has(event.source)) {
    console.warn("[plugin-firewall] message from unregistered source");
    return null;
  }

  // 3. Only accept messages from null-origin iframes (sandboxed plugins).
  if (event.origin !== "null") {
    console.warn("[plugin-firewall] origin not null:", event.origin);
    return null;
  }

  const action = event.data?.action;
  if (!action || !ALLOWED_PLUGIN_ACTIONS.has(action)) {
    console.warn("[plugin-firewall] blocked message:", action);
    return null;
  }

  switch (action) {
    case "plugin.ready":
      console.info("[plugin-firewall] plugin ready:", event.data?.plugin_id);
      break;
    case "plugin.resize":
      // TODO: resize the iframe host element based on event.data.height
      break;
    case "plugin.notify":
      // TODO: show a native notification via Tauri command
      break;
    default:
      // Unreachable — the whitelist guard above catches it.
      return null;
  }
  return action;
}

window.addEventListener("message", handlePluginMessage);

// -----------------------------------------------------------------------------
// Splash screen — waits for sidecar then redirects to the web UI
// -----------------------------------------------------------------------------

const HEALTH_POLL_MS = 500;
const HEALTH_TIMEOUT_MS = 30_000;

function setStatus(text) {
  const el = document.querySelector("#splash-status");
  if (el) el.textContent = text;
}

function showError(text) {
  const el = document.querySelector("#splash-error");
  if (el) { el.textContent = text; el.style.display = "block"; }
  setStatus("");
  const spinner = document.querySelector(".spinner");
  if (spinner) spinner.style.display = "none";
}

window.addEventListener("DOMContentLoaded", async () => {
  try {
    // F5.3: show onboarding wizard on first run before sidecar polling.
    const firstRun = await invoke("check_first_run");
    if (firstRun) {
      const { initOnboarding } = await import("./onboarding/main.js");
      initOnboarding();
      return;
    }

    const port = await getSidecarPort();
    const healthUrl = `http://127.0.0.1:${port}/admin/system/health`;
    const deadline = Date.now() + HEALTH_TIMEOUT_MS;
    let elapsed = 0;

    while (Date.now() < deadline) {
      const secs = Math.round(elapsed / 1000);
      setStatus(secs > 0 ? `iniciant… (${secs}s)` : "iniciant…");
      try {
        await fetchFromSidecar(healthUrl, "GET", null);
        // Sidecar is healthy. Rust `poll_sidecar_health` will navigate the
        // webview to http://127.0.0.1:{port}/?nexe_api_key=... right after
        // its own health check passes (typically within the next poll tick).
        // Hold the spinner here; if Rust does not navigate within a small
        // grace window, surface a timeout below.
        setStatus("");
        await new Promise((r) => setTimeout(r, 5_000));
        showError("El servidor està actiu però la finestra no ha pogut canviar. Tanca i reobre l'app.");
        return;
      } catch {
        // Not ready yet — keep polling.
      }
      await new Promise((r) => setTimeout(r, HEALTH_POLL_MS));
      elapsed += HEALTH_POLL_MS;
    }

    showError(`El servidor no ha respost en ${HEALTH_TIMEOUT_MS / 1000}s.`);
  } catch (err) {
    showError(`Failed to start: ${err}`);
  }
});
