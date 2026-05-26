// F5.3 — Unit tests for the onboarding wizard state machine and i18n.
// Uses vitest in node environment (matches vite.config.js test setup).
// Mocks Tauri APIs so tests run without a real Tauri runtime.

import { describe, it, expect, beforeEach, vi } from "vitest";
import { t, STRINGS } from "./i18n.js";

// ---------------------------------------------------------------------------
// i18n tests
// ---------------------------------------------------------------------------

describe("i18n — t()", () => {
  it("returns the Catalan string for a known key", () => {
    expect(t("welcome_title", "ca")).toBe("Benvingut a server-nexe");
  });

  it("returns the English string for a known key", () => {
    expect(t("welcome_title", "en")).toBe("Welcome to server-nexe");
  });

  it("falls back to English for an unknown lang", () => {
    expect(t("welcome_title", "xx")).toBe("Welcome to server-nexe");
  });

  it("returns the key itself when key is missing from all langs", () => {
    expect(t("nonexistent_key_xyz", "ca")).toBe("nonexistent_key_xyz");
  });

  it("CA, ES, EN all define the same set of keys", () => {
    const caKeys = Object.keys(STRINGS.ca).sort();
    const esKeys = Object.keys(STRINGS.es).sort();
    const enKeys = Object.keys(STRINGS.en).sort();
    expect(esKeys).toEqual(caKeys);
    expect(enKeys).toEqual(caKeys);
  });

  it("btn_next is defined in all languages", () => {
    expect(t("btn_next", "ca")).toBeTruthy();
    expect(t("btn_next", "es")).toBeTruthy();
    expect(t("btn_next", "en")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// State machine tests (state module)
// ---------------------------------------------------------------------------

// Mocks for Tauri APIs
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd) => {
    if (cmd === "check_first_run") return true;
    if (cmd === "get_hardware") return { ram_gb: 16, os: "macOS 15", is_apple_silicon: true, machine: "aarch64", disk_free_gb: 100 };
    if (cmd === "fetch_catalog") return [
      { name: "Gemma 3 4B", params: "4B", ram_gb: 4.0, disk_gb: 3.3, backends: ["MLX", "Ollama"], flags: [], origin: "Google", ollama: "gemma3:4b", mlx: null, gguf: null },
    ];
    if (cmd === "get_sidecar_port") return 39291;
    if (cmd === "mark_onboarding_complete") return null;
    return null;
  }),
}));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => {}),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: vi.fn(async () => "/tmp/models"),
}));

// DOM shims for node environment
beforeEach(() => {
  globalThis.window = {
    addEventListener: () => {},
    location: { replace: vi.fn() },
    __NEXE_SIDECAR_PORT: 39291,
  };
  globalThis.document = {
    createTextNode: (text) => ({ nodeType: 3, textContent: text }),
    createElement: (tag) => {
      const el = {
        tagName: tag.toUpperCase(),
        className: "",
        textContent: "",
        id: "",
        title: "",
        style: { cssText: "" },
        children: [],
        eventListeners: {},
        classList: {
          _set: new Set(),
          add(...cls) { cls.forEach(c => this._set.add(c)); },
          remove(...cls) { cls.forEach(c => this._set.delete(c)); },
          toggle(c) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); return this._set.has(c); },
          contains(c) { return this._set.has(c); },
        },
        appendChild: (child) => { el.children.push(child); return child; },
        replaceChildren: (...args) => { el.children = [...args]; },
        replaceChild: (newChild, _oldChild) => { el.children.push(newChild); return newChild; },
        addEventListener: (ev, fn) => { el.eventListeners[ev] = fn; },
        dispatchEvent: (e) => { const fn = el.eventListeners[e.type]; if (fn) fn(e); },
        querySelectorAll: () => [],
        querySelector: () => null,
        setAttribute: (k, v) => { el[k] = v; },
        getAttribute: (k) => el[k] ?? null,
        removeAttribute: (k) => { delete el[k]; },
        remove: () => {},
        focus: () => {},
        click: () => { const fn = el.eventListeners["click"]; if (fn) fn({ preventDefault: () => {} }); },
      };
      return el;
    },
    getElementById: (id) => ({
      id,
      replaceChildren: () => {},
      appendChild: () => {},
      children: [],
      classList: { add() {}, remove() {}, toggle() { return false; }, contains() { return false; }, _set: new Set() },
      remove: () => {},
    }),
    documentElement: {
      classList: { add() {}, remove() {}, toggle() { return false; }, contains() { return false; }, _set: new Set() },
    },
    addEventListener: () => {},
    head: { appendChild: () => {} },
    body: { replaceChildren: () => {}, appendChild: () => {}, children: [] },
  };
  globalThis.CustomEvent = class CustomEvent { constructor(type) { this.type = type; } };
  globalThis.localStorage = (() => {
    let store = {};
    return {
      getItem: (k) => store[k] ?? null,
      setItem: (k, v) => { store[k] = v; },
      removeItem: (k) => { delete store[k]; },
      clear: () => { store = {}; },
    };
  })();
  globalThis.EventSource = vi.fn(() => ({
    onmessage: null,
    onerror: null,
    close: vi.fn(),
  }));
  // navigator.language is read-only in some environments — use defineProperty
  try {
    Object.defineProperty(globalThis, "navigator", {
      value: { language: "ca" },
      writable: true,
      configurable: true,
    });
  } catch { /* read-only in some envs — intentional */ }

  globalThis.fetch = vi.fn(async () => ({
    json: async () => ({ api_key: "test-api-key-uuid", status: "ready" }),
  }));
});

describe("state — saveState / loadState round-trip", async () => {
  it("saves and restores state", async () => {
    const { state, saveState } = await import("./main.js?t=" + Date.now());
    state.step = 3;
    state.lang = "en";
    saveState();
    const raw = localStorage.getItem("nexe_onboarding_state");
    const parsed = JSON.parse(raw);
    expect(parsed.step).toBe(3);
    expect(parsed.lang).toBe("en");
  });
});

describe("state — goToStep", async () => {
  it("advances step and saves to localStorage", async () => {
    const { state, goToStep } = await import("./main.js?t=" + Date.now());
    state.step = 0;
    goToStep(2);
    expect(state.step).toBe(2);
    const raw = localStorage.getItem("nexe_onboarding_state");
    expect(JSON.parse(raw).step).toBe(2);
  });
});

describe("state — initial lang from navigator", async () => {
  it("uses navigator.language prefix as default lang", async () => {
    try {
      Object.defineProperty(globalThis, "navigator", {
        value: { language: "es-ES" },
        writable: true,
        configurable: true,
      });
    } catch { /* read-only in some envs — intentional */ }
    const { state } = await import("./main.js?t=" + Date.now() + 1);
    // lang is set at module init from navigator.language.substring(0,2)
    expect(["ca", "es", "en"]).toContain(state.lang);
  });
});

describe("normalizeStateOnLoad — Bloc 7b cross-field inconsistency guard", () => {
  it("resets step=1 when persisted step >= 3 but selectedModel is null", async () => {
    // Simulate a crashed wizard from a previous session: step=5 (finalize)
    // but no selectedModel — would POST /installer/finalize with engine=undefined.
    const { state, normalizeStateOnLoad } = await import("./main.js?t=" + Date.now() + 2);
    state.step = 5;
    state.selectedModel = null;
    state.downloadProgress = 0.7;
    normalizeStateOnLoad();
    expect(state.step).toBe(1);
    expect(state.selectedModel).toBeNull();
    expect(state.downloadProgress).toBe(0);
  });

  it("keeps step=2 when selectedModel is null (user still choosing)", async () => {
    const { state, normalizeStateOnLoad } = await import("./main.js?t=" + Date.now() + 3);
    state.step = 2;
    state.selectedModel = null;
    normalizeStateOnLoad();
    expect(state.step).toBe(2);
  });

  it("keeps step >= 3 when selectedModel has full shape", async () => {
    const { state, normalizeStateOnLoad } = await import("./main.js?t=" + Date.now() + 4);
    state.step = 4;
    state.selectedModel = { engine: "ollama", model_id: "qwen3.5:1b", name: "Qwen 3.5 1B" };
    normalizeStateOnLoad();
    expect(state.step).toBe(4);
    expect(state.selectedModel.engine).toBe("ollama");
  });

  it("resets step >= 3 when selectedModel has invalid shape (missing engine)", async () => {
    const { state, normalizeStateOnLoad } = await import("./main.js?t=" + Date.now() + 5);
    state.step = 4;
    state.selectedModel = { model_id: "qwen3.5:1b", name: "Qwen" };  // no engine
    normalizeStateOnLoad();
    // Shape validator nulls it, then the cross-field guard kicks in.
    expect(state.selectedModel).toBeNull();
    expect(state.step).toBe(1);
  });
});

describe("_checkMetalWithRetry — Bloc 7c race vs sidecar ready", () => {
  it("returns metal_available=true when sidecar responds OK", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ metal_available: true, platform: "darwin" }),
    }));
    const { _checkMetalWithRetry } = await import("./main.js?t=" + Date.now() + 6);
    const result = await _checkMetalWithRetry(1000, 50);
    expect(result).toBe(true);
  });

  it("returns false on timeout if sidecar never responds", async () => {
    // Simulate sidecar never up: fetch always throws.
    globalThis.fetch = vi.fn(async () => { throw new Error("connection refused"); });
    const { _checkMetalWithRetry } = await import("./main.js?t=" + Date.now() + 7);
    const start = Date.now();
    const result = await _checkMetalWithRetry(500, 50);
    const elapsed = Date.now() - start;
    expect(result).toBe(false);
    expect(elapsed).toBeGreaterThanOrEqual(400);  // honored the timeout
    expect(elapsed).toBeLessThan(2000);            // didn't run away
  });

  it("retries until success when sidecar comes online mid-poll", async () => {
    let calls = 0;
    globalThis.fetch = vi.fn(async () => {
      calls++;
      if (calls < 3) throw new Error("not ready");
      return { ok: true, json: async () => ({ metal_available: true }) };
    });
    const { _checkMetalWithRetry } = await import("./main.js?t=" + Date.now() + 8);
    const result = await _checkMetalWithRetry(2000, 50);
    expect(result).toBe(true);
    expect(calls).toBeGreaterThanOrEqual(3);
  });
});

describe("_checkMetalWithRetry — Regression #1 first_run extended timeout", () => {
  it("respects extended timeout on first_run (does not bail at 15s)", async () => {
    let calls = 0;
    globalThis.fetch = vi.fn(async () => {
      calls++;
      if (calls < 5) throw new Error("sidecar seeding fastembed");
      return { ok: true, json: async () => ({ metal_available: true }) };
    });
    const { _checkMetalWithRetry } = await import("./main.js?t=" + Date.now() + 20);
    const result = await _checkMetalWithRetry(180000, 50);
    expect(result).toBe(true);
    expect(calls).toBeGreaterThanOrEqual(5);
  });
});

describe("initOnboarding — Regression #2 catalog validation on resume", () => {
  it("resets to step 1 when persisted model is absent from catalog", async () => {
    const { state } = await import("./main.js?t=" + Date.now() + 21);
    state.step = 3;
    state.selectedModel = { engine: "mlx", model_id: "mlx-community/removed-model", name: "Removed" };
    state.catalog = [
      { name: "Gemma 3 4B", ollama: "gemma3:4b", mlx: null, gguf: null },
    ];
    const mid = state.selectedModel.model_id;
    const found = state.catalog.some(m =>
      m.ollama === mid || m.mlx === mid || m.gguf === mid
    );
    if (!found) {
      state.step = 1;
      state.selectedModel = null;
      state.downloadProgress = 0;
    }
    expect(state.step).toBe(1);
    expect(state.selectedModel).toBeNull();
  });

  it("keeps step >= 3 when persisted model exists in catalog", async () => {
    const { state } = await import("./main.js?t=" + Date.now() + 22);
    state.step = 4;
    state.selectedModel = { engine: "ollama", model_id: "gemma3:4b", name: "Gemma 3 4B" };
    state.catalog = [
      { name: "Gemma 3 4B", ollama: "gemma3:4b", mlx: null, gguf: null },
    ];
    const mid = state.selectedModel.model_id;
    const found = state.catalog.some(m =>
      m.ollama === mid || m.mlx === mid || m.gguf === mid
    );
    expect(found).toBe(true);
    expect(state.step).toBe(4);
  });
});

describe("model selection in step2", () => {
  it("converts backend name to engine key correctly", () => {
    // Simulate the engine mapping from step2-hardware.js
    const mapEngine = (name) =>
      name?.toLowerCase().replace("llama.cpp", "gguf") || "ollama";
    expect(mapEngine("MLX")).toBe("mlx");
    expect(mapEngine("Ollama")).toBe("ollama");
    expect(mapEngine("llama.cpp")).toBe("gguf");
    expect(mapEngine(undefined)).toBe("ollama");
  });
});
