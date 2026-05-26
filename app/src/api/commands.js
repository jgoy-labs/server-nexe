// Centralized wrappers for Tauri commands.
//
// Keeping invoke() calls in one place makes the API easier to mock in tests
// (via `@tauri-apps/api/mocks`) and easier to migrate to TypeScript later.
//
// When adding a new #[tauri::command] on the Rust side, add its wrapper here.

import { invoke } from "@tauri-apps/api/core";

/** @param {string} name */
export const greet = (name) => invoke("greet", { name });

/** Returns the dynamic sidecar port assigned at startup. */
export const getSidecarPort = () => invoke("get_sidecar_port");

/**
 * Wrapper for `fetch_from_sidecar` (auth.rs). Original 2026-05-02.
 * Rust injects the Bearer token internally; the frontend never sees the raw token.
 *
 * @param {string} url     - http://127.0.0.1:<port>/path validated by Rust
 * @param {string} method  - GET | HEAD | DELETE | POST | PUT
 * @param {string|null} body - optional, POST/PUT only
 * @returns {Promise<string>} raw body from the sidecar (frontend does JSON.parse if needed)
 */
export const fetchFromSidecar = (url, method, body = null) =>
  invoke("fetch_from_sidecar", { url, method, body });
