// F5.3: Onboarding wizard — state machine + routing.
//
// Called from src/main.js when check_first_run() returns true.
// Six steps (0-5). State is persisted to localStorage so the wizard
// can resume if the window is closed mid-flow.

import { invoke } from "@tauri-apps/api/core";
import { step0 } from "./step0-splash.js";
import { step1 } from "./step1-welcome.js";
import { step2 } from "./step2-hardware.js";
import { step3 } from "./step3-download.js";
import { step4 } from "./step4-done.js";
import { step5 } from "./step5-apikey.js";
import onboardingCss from "./styles.css?inline";

const STORAGE_KEY = "nexe_onboarding_state";

/** Mutable wizard state — shared across step modules via export. */
export const state = {
  step: 0,
  lang: (navigator.language || "ca").substring(0, 2),
  hardware: {},
  catalog: [],
  /** @type {{name: string, engine: string, model_id: string, disk_gb: number}|null} */
  selectedModel: null,
  modelsPath: "",
  downloadProgress: 0,
  advanced: false,
  apiKey: "",
  /** F5.4 Fase 4b: optional Hugging Face token. Held in memory only here;
   *  the wizard sends it once to /installer/finalize where the backend
   *  forwards it to the macOS Keychain. We never persist it in
   *  localStorage. */
  hfToken: "",
};

/** Persist state to localStorage.
 *
 * F5.4 Fase 4b: the optional HF token is INTENTIONALLY excluded — it is
 * forwarded to the Keychain at finalize time and never lands on disk in
 * cleartext. localStorage is per-origin disk storage; not the right place
 * for a token. */
export function saveState() {
  try {
    // F5.4: omit hfToken from disk persistence. Build a shallow copy
    // without the token via a literal rest-spread so eslint doesn't flag
    // it as an unused variable.
    const persistable = { ...state };
    delete persistable.hfToken;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persistable));
  } catch (_) {
    // localStorage may be unavailable in some sandboxed contexts — ignore.
  }
}

/** Load previously saved state (resume after window close). */
function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) Object.assign(state, JSON.parse(raw));
  } catch (_) {
    // Corrupt or missing — start fresh.
  }
}

const STEP_RENDERERS = [step0, step1, step2, step3, step4, step5];

/** Render the current step inside #onboarding-app. */
function renderCurrentStep() {
  const app = document.getElementById("onboarding-app");
  if (!app) return;
  app.replaceChildren();
  STEP_RENDERERS[state.step]?.();
}

/** Advance to step `n`, save state, re-render. */
export function goToStep(n) {
  state.step = n;
  saveState();
  renderCurrentStep();
}

/**
 * Entry point called from src/main.js when first_run is true.
 *
 * Injects the onboarding container into the page (replacing whatever was
 * there), loads persisted state, and renders the current step.
 */
/**
 * Normalize `state` after loadState() — pure function (no DOM, no Tauri).
 * Exported so unit tests can validate the resume guards without rendering.
 *
 * Bloc 6 (F13) + Bloc 7b: bounds check, shape validation, cross-field
 * inconsistency guard.
 */
export function normalizeStateOnLoad() {
  // F5.6 Block 6 (F13): wizard resumes the step if valid (1..MAX_STEPS),
  // instead of always overwriting. UX: a user who closed mid-flow returns
  // where they were (e.g. Step 2 with a model chosen) instead of bouncing
  // back to Welcome every time. MAX_STEPS derived dynamically from
  // STEP_RENDERERS.length to adapt to future steps without touching guard.
  const MAX_STEPS = STEP_RENDERERS.length - 1;
  if (!state.step || state.step < 1 || state.step > MAX_STEPS) {
    state.step = 1;
    state.selectedModel = null;
    state.downloadProgress = 0;
  }
  // Validate persisted selectedModel shape (post-Block 5 has engine + model_id + name).
  // If the object comes from an older version without these fields, reset (UX safe:
  // the user sees a placeholder and can pick again; without reset the dropdown would
  // show "undefined").
  if (state.selectedModel) {
    const valid =
      state.selectedModel.engine &&
      state.selectedModel.model_id &&
      state.selectedModel.name;
    if (!valid) {
      state.selectedModel = null;
      state.downloadProgress = 0;
    }
  }
  // F5.6 Bloc 7b: cross-field inconsistency guard. Steps 3..5 (download /
  // done / finalize) ALL require selectedModel. If localStorage carries a
  // step >= 3 from a previous session that crashed before completing the
  // wizard (or that pre-dated the selectedModel shape validation above),
  // the resumed flow would POST /installer/finalize with engine=undefined,
  // get a Pydantic 422 back, and the user would face an opaque error from
  // the server with no way to recover. Reset to Welcome so the user can
  // pick a model again. Step 2 without a model is legal (user is choosing).
  if (state.step >= 3 && !state.selectedModel) {
    state.step = 1;
    state.downloadProgress = 0;
  }
  // state.advanced does NOT persist across launches — always reset (per-session toggle).
  state.advanced = false;
}

/**
 * Poll the sidecar `/installer/check-metal` endpoint until it responds OK
 * or the deadline elapses. Bloc 7c: covers the race between DOMContentLoaded
 * (which fires initOnboarding immediately) and `splash: sidecar ready`
 * (which can take 5-15 s on first-run because the PBS+venv tarball must be
 * extracted and lifespan startup must complete). Returns the endpoint's
 * boolean, or `false` on timeout — conservative degradation so we don't
 * silently offer MLX models on a host where Metal isn't confirmed.
 *
 * Exported so unit tests can validate the retry semantics without DOM.
 */
export async function _checkMetalWithRetry(maxMs = 15000, delayMs = 250) {
  const deadline = Date.now() + maxMs;
  let port;
  try {
    port = await invoke("get_sidecar_port");
  } catch (_) {
    return false;
  }
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(`http://127.0.0.1:${port}/installer/check-metal`);
      if (resp.ok) {
        const data = await resp.json();
        return !!data.metal_available;
      }
    } catch (_) {
      // sidecar not ready yet — keep polling
    }
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return false;
}

export async function initOnboarding() {
  loadState();
  normalizeStateOnLoad();

  // F5.6 Block 7c + Regression #1 2026-05-25: on first_run the sidecar seeds
  // fastembed (~76-90s) before responding to /installer/check-metal. The
  // default 15s timeout expires → metalAvailable=false → MLX filtered →
  // Ollama-only → error if Ollama not installed. Fix: 180s on first_run.
  const isFirstRun = await invoke("check_first_run");
  if (isFirstRun) {
    const hint = document.createElement("p");
    hint.id = "first-run-hint";
    hint.textContent = "Configurant el sistema…";
    hint.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);font:1rem system-ui;opacity:.7";
    document.body.appendChild(hint);
  }
  state.metalAvailable = await _checkMetalWithRetry(isFirstRun ? 180000 : 15000);
  document.getElementById("first-run-hint")?.remove();

  // Regression #2 2026-05-25: if resuming at step >= 3, validate that the
  // persisted selectedModel still exists in the current catalog. Models can be
  // removed between versions — proceeding to download with a stale model_id
  // would fail opaquely.
  if (state.step >= 3 && state.selectedModel) {
    try {
      if (!state.catalog.length) state.catalog = await invoke("fetch_catalog");
      const mid = state.selectedModel.model_id;
      const found = state.catalog.some(m =>
        m.ollama === mid || m.mlx === mid || m.gguf === mid
      );
      if (!found) {
        state.step = 1;
        state.selectedModel = null;
        state.downloadProgress = 0;
        saveState();
      }
    } catch (_) {
      state.step = 1;
      state.selectedModel = null;
      state.downloadProgress = 0;
      saveState();
    }
  }

  document.body.replaceChildren();

  const styleEl = document.createElement("style");
  styleEl.textContent = onboardingCss;
  document.head.appendChild(styleEl);

  // Theme: follows the system by default; saved preference takes precedence.
  const savedTheme = localStorage.getItem("nexe_theme");
  const systemDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true;
  const useDark = savedTheme ? savedTheme === "dark" : systemDark;
  if (!useDark) document.documentElement.classList.add("light");

  // Listen for system changes in real time (only if no manual preference is set)
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (!localStorage.getItem("nexe_theme")) {
      document.documentElement.classList.toggle("light", !e.matches);
      themeBtn.textContent = e.matches ? "◑ dark" : "☀ light";
    }
  });

  const themeBtn = document.createElement("button");
  themeBtn.className = "theme-toggle";
  themeBtn.textContent = savedTheme ? (useDark ? "◑ dark" : "☀ light") : "◑ auto";
  themeBtn.addEventListener("click", () => {
    const isLight = document.documentElement.classList.toggle("light");
    localStorage.setItem("nexe_theme", isLight ? "light" : "dark");
    themeBtn.textContent = isLight ? "☀ light" : "◑ dark";
  });
  document.body.appendChild(themeBtn);

  const container = document.createElement("div");
  container.id = "onboarding-app";
  document.body.appendChild(container);

  renderCurrentStep();
}
