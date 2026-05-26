// F5.3 Step 2 — Model selection.
// Normal mode: custom dropdown of compatible models + download.
// Advanced mode: local models folder + selector.

import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { goToStep, state, saveState } from "./main.js";
import { t } from "./i18n.js";

// F5.4 Fase 4b: HF tokens page. The wizard does NOT auto-open the browser
// (Tauri 2 needs a plugin or custom Rust command for that, and we want to
// avoid new dependencies in F5.4 — see ADR-pending). Instead, the "Get
// token" button copies the URL to the clipboard so the user can paste it
// into their browser. Lower-friction than asking the user to type it.
const HF_TOKENS_URL = "https://huggingface.co/settings/tokens";

// ── Helpers ───────────────────────────────────────────────────

function originFlag(origin) {
  const o = (origin || "").toLowerCase();
  if (o.includes("alibaba") || o.includes("deepseek") || o.includes("xina") || o.includes("china")) return "🇨🇳";
  if (o.includes("bsc") || o.includes("aina") || o.includes("mistral") || o.includes("catalunya") || o.includes("europa")) return "🇪🇺";
  return "🇺🇸";
}

function inferFlags(model) {
  const n = (model.name || "").toLowerCase();
  const flags = [];
  if (n.includes("-vl") || n.includes("vision")) flags.push("vision");
  if (n.includes("r1") || n.includes("qwen3") || n.includes("thinking")) flags.push("thinking");
  if (n.includes("e4b") || n.includes("a3b") || n.includes("moe") || n.includes("distill")) flags.push("moe");
  return flags;
}

// ── Main ──────────────────────────────────────────────────────

export async function step2() {
  const app = document.getElementById("onboarding-app");
  app.replaceChildren();

  if (!state.hardware.ram_gb) state.hardware = await invoke("get_hardware");
  if (!state.catalog.length)  state.catalog  = await invoke("fetch_catalog");

  const wrapper = document.createElement("div");
  wrapper.className = "step step2";

  const logo = document.createElement("img");
  logo.src = "/onboarding-logo.png";
  logo.alt = "server-nexe";
  logo.className = "nexe-logo";
  wrapper.appendChild(logo);

  wrapper.appendChild(_buildHwBadges());

  const expl = document.createElement("p");
  expl.className = "step2-explainer";
  expl.textContent = t("step2_explainer", state.lang);
  wrapper.appendChild(expl);

  if (state.hardware.ram_gb < 12) {
    const warn = document.createElement("p");
    warn.className = "step2-tier-warning";
    warn.textContent = t("step2_8gb_warning", state.lang);
    wrapper.appendChild(warn);
  }

  const zone = document.createElement("div");
  zone.id = "step2-zone";
  wrapper.appendChild(zone);

  _renderZone(zone);
  app.appendChild(wrapper);
}

function _renderZone(zone) {
  zone.replaceChildren();
  state.advanced ? _renderAdvancedZone(zone) : _renderNormalZone(zone);
}

// ── Mode normal ───────────────────────────────────────────────

// F5.6 Block 5 (F12): helper to derive model_id based on the chosen engine.
// Extracted from the original inline code (_buildCustomDropdown) because the
// user can now switch engine via the clickable badge — re-derivation needed.
function _deriveModelId(model, engine) {
  const e = engine.toLowerCase().replace("llama.cpp", "gguf");
  if (e === "mlx") return model.mlx || model.ollama || "";
  if (e === "gguf") return model.gguf || "";
  return model.ollama || model.mlx || "";
}

// F5.6 Block 5 (F07 + F12): filter backends by Metal availability.
// If Metal is unavailable (Intel, Linux), hide MLX from the list.
function _filterBackendsByMetal(backends) {
  const metalOK = state.metalAvailable !== false;
  return (backends || []).filter((b) => metalOK || b.toLowerCase() !== "mlx");
}

function _renderNormalZone(zone) {
  const usable = state.hardware.ram_gb * 0.55;
  // F5.6 Block 5 (F11): map instead of filter — show ALL models but flag
  // those that don't fit in available RAM as _disabled.
  // Clearer UX, aligned with the original CLI which shows
  // fits_tight rather than hiding.
  const shown = state.catalog.map((m) => ({
    ...m,
    _disabled: usable < m.ram_gb,
    _availableBackends: _filterBackendsByMetal(m.backends),
  }));

  const dropLabel = document.createElement("span");
  dropLabel.className = "field-label-prominent";
  dropLabel.textContent = t("select_model_title", state.lang);
  zone.appendChild(dropLabel);

  // Dropdown custom
  const dropdown = _buildCustomDropdown(shown);
  zone.appendChild(dropdown);

  const dlBtn = document.createElement("button");
  dlBtn.className = "btn-primary btn-full";
  dlBtn.textContent = t("btn_start_download", state.lang);
  dlBtn.disabled = !state.selectedModel;
  dlBtn.id = "dl-btn";
  dlBtn.addEventListener("click", () => { if (state.selectedModel) goToStep(3); });
  zone.appendChild(dlBtn);

  const advLink = document.createElement("button");
  advLink.className = "btn-subtle";
  advLink.textContent = "⚙  " + t("btn_advanced", state.lang);
  advLink.addEventListener("click", () => {
    state.advanced = true;
    state.selectedModel = null;
    saveState();
    _renderZone(document.getElementById("step2-zone"));
  });
  zone.appendChild(advLink);
}

function _buildCustomDropdown(models) {
  const wrap = document.createElement("div");
  wrap.className = "custom-dropdown";
  wrap.setAttribute("tabindex", "0");

  const trigger = document.createElement("div");
  trigger.className = "custom-dropdown-trigger";
  trigger.id = "dropdown-trigger";

  const triggerText = document.createElement("span");
  triggerText.className = "dropdown-placeholder";
  triggerText.textContent = state.selectedModel
    ? state.selectedModel.name
    : t("select_model_placeholder", state.lang);
  trigger.appendChild(triggerText);

  const arrow = document.createElement("span");
  arrow.className = "dropdown-arrow";
  arrow.textContent = "▾";
  trigger.appendChild(arrow);

  const listWrap = document.createElement("div");
  listWrap.className = "custom-dropdown-list";
  listWrap.style.display = "none";

  models.forEach((model) => {
    // F5.6 Block 5 (F12): backends filtered by Metal availability + helper
    // to derive model_id. If no backend is available (e.g. Intel with an
    // MLX-only model), skip the model.
    const availableBackends = model._availableBackends || _filterBackendsByMetal(model.backends);
    if (availableBackends.length === 0) return;
    // Active engine: if the user has cycled it for this model, respect
    // _currentEngine (in-memory inside the item, not persisted across models).
    const currentEngineRaw = model._currentEngine || availableBackends[0];
    const primaryEngine = currentEngineRaw.toLowerCase().replace("llama.cpp", "gguf");
    const modelId = _deriveModelId(model, primaryEngine);
    const flags = inferFlags(model);
    const flag = originFlag(model.origin);

    const item = document.createElement("div");
    // F5.6 Block 5 (F11): `disabled` class if the model does not fit in RAM.
    const isDisabled = model._disabled === true;
    item.className = "dropdown-item"
      + (state.selectedModel?.model_id === modelId ? " selected" : "")
      + (isDisabled ? " disabled" : "");
    if (isDisabled) {
      item.title = `Requires ${model.ram_gb} GB RAM`;
    }

    // Origin flag
    const flagEl = document.createElement("span");
    flagEl.className = "dropdown-flag";
    flagEl.textContent = flag;
    item.appendChild(flagEl);

    // Name + params
    const nameWrap = document.createElement("div");
    nameWrap.className = "dropdown-name-wrap";
    const nameEl = document.createElement("span");
    nameEl.className = "dropdown-name";
    nameEl.textContent = model.name;
    const paramsEl = document.createElement("span");
    paramsEl.className = "dropdown-params";
    paramsEl.textContent = model.params;
    nameWrap.appendChild(nameEl);
    nameWrap.appendChild(paramsEl);
    item.appendChild(nameWrap);

    // Right-side badges
    const meta = document.createElement("div");
    meta.className = "dropdown-meta";

    const ramBadge = document.createElement("span");
    ramBadge.className = "badge badge-ram";
    ramBadge.textContent = model.ram_gb + " GB";
    meta.appendChild(ramBadge);

    // F5.6 Block 5 (F12): engine badge. Shows the active engine (e.g. "MLX").
    // If availableBackends.length > 1, it's clickable with cycle behavior
    // (1 click = switch to next available engine). Re-derives model_id if
    // this model is selected.
    const engineBadge = document.createElement("span");
    engineBadge.className = "badge badge-engine";
    engineBadge.textContent = primaryEngine.toUpperCase();
    if (availableBackends.length > 1 && !isDisabled) {
      engineBadge.classList.add("badge-clickable");
      engineBadge.title = `Click: cycle engine (${availableBackends.join(" / ")})`;
      engineBadge.addEventListener("click", (e) => {
        e.stopPropagation();  // don't trigger model selection
        const norm = (b) => b.toLowerCase().replace("llama.cpp", "gguf");
        const idx = availableBackends.findIndex((b) => norm(b) === primaryEngine);
        const nextRaw = availableBackends[(idx + 1) % availableBackends.length];
        model._currentEngine = nextRaw;
        const newEngine = norm(nextRaw);
        const newModelId = _deriveModelId(model, newEngine);
        engineBadge.textContent = newEngine.toUpperCase();
        // If this model was selected, re-derive state
        if (state.selectedModel?.name === model.name) {
          state.selectedModel = {
            name: model.name,
            engine: newEngine,
            model_id: newModelId,
            disk_gb: model.disk_gb,
          };
          saveState();
        }
      });
    } else {
      engineBadge.title = `Engine: ${primaryEngine}`;
    }
    meta.appendChild(engineBadge);

    if (flags.includes("thinking")) {
      const b = document.createElement("span");
      b.className = "badge badge-thinking";
      b.textContent = "🤔";
      b.title = "Thinking";
      meta.appendChild(b);
    }
    if (flags.includes("vision")) {
      const b = document.createElement("span");
      b.className = "badge badge-vision";
      b.textContent = "👁";
      b.title = "Vision";
      meta.appendChild(b);
    }
    if (flags.includes("moe")) {
      const b = document.createElement("span");
      b.className = "badge badge-moe";
      b.textContent = "⚡";
      b.title = "MoE";
      meta.appendChild(b);
    }
    if (model.gated) {
      const b = document.createElement("span");
      b.className = "badge badge-gated";
      b.textContent = "🔒";
      b.title = "Requires Hugging Face token";
      meta.appendChild(b);
    }

    item.appendChild(meta);

    // F5.6 Block 5 (F11): disabled models cannot be selected.
    if (!isDisabled) {
      item.addEventListener("click", () => {
        state.selectedModel = {
          name: model.name,
          engine: primaryEngine,
          model_id: modelId,
          disk_gb: model.disk_gb,
        };
        saveState();
        triggerText.textContent = model.name;
        triggerText.className = "dropdown-selected-text";
        listWrap.style.display = "none";
        arrow.textContent = "▾";
        listWrap.querySelectorAll(".dropdown-item").forEach((el) => el.classList.remove("selected"));
        item.classList.add("selected");
        const btn = document.getElementById("dl-btn");
        if (btn) btn.disabled = false;
      });
    }

    listWrap.appendChild(item);
  });

  trigger.addEventListener("click", () => {
    const open = listWrap.style.display !== "none";
    listWrap.style.display = open ? "none" : "block";
    arrow.textContent = open ? "▾" : "▴";
  });

  // Close when clicking outside
  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) {
      listWrap.style.display = "none";
      arrow.textContent = "▾";
    }
  }, { once: false });

  wrap.appendChild(trigger);
  wrap.appendChild(listWrap);
  return wrap;
}

// ── Advanced mode ─────────────────────────────────────────────

function _renderAdvancedZone(zone) {
  const expl = document.createElement("p");
  expl.className = "step2-advanced-expl";
  expl.textContent = t("step2_advanced_explainer", state.lang);
  zone.appendChild(expl);

  const folderLabel = document.createElement("span");
  folderLabel.className = "field-label";
  folderLabel.textContent = t("models_folder_label", state.lang);
  zone.appendChild(folderLabel);

  const folderRow = document.createElement("div");
  folderRow.className = "folder-row";

  const pathInput = document.createElement("input");
  pathInput.type = "text";
  pathInput.readOnly = true;
  pathInput.value = state.modelsPath;
  pathInput.placeholder = "~/models";

  const folderBtn = document.createElement("button");
  folderBtn.className = "btn-secondary";
  folderBtn.textContent = t("models_folder_btn", state.lang);
  folderBtn.addEventListener("click", async () => {
    const result = await open({ directory: true, multiple: false });
    if (result && typeof result === "string") {
      state.modelsPath = result;
      pathInput.value = result;
      saveState();
      selBtn.disabled = false;
    }
  });

  folderRow.appendChild(pathInput);
  folderRow.appendChild(folderBtn);
  zone.appendChild(folderRow);

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = t("models_folder_hint", state.lang);
  zone.appendChild(hint);

  const selBtn = document.createElement("button");
  selBtn.className = "btn-primary btn-full";
  selBtn.textContent = t("btn_select_local", state.lang);
  selBtn.disabled = !state.modelsPath;
  selBtn.addEventListener("click", () => {
    if (state.modelsPath) {
      state.selectedModel = { name: "local", engine: "local", model_id: state.modelsPath, disk_gb: 0 };
      saveState();
      goToStep(5);
    }
  });
  zone.appendChild(selBtn);

  // F5.4 Fase 4b: optional Hugging Face token block. Only in Advanced —
  // basic users should not see this. Hidden behind a collapsed details
  // element so it does not visually clutter the step.
  zone.appendChild(_buildHfTokenBlock());

  const backLink = document.createElement("button");
  backLink.className = "btn-subtle";
  backLink.textContent = "← " + t("btn_back_normal", state.lang);
  backLink.addEventListener("click", () => {
    state.advanced = false;
    saveState();
    _renderZone(document.getElementById("step2-zone"));
  });
  zone.appendChild(backLink);
}

// ── F5.4 Fase 4b: HF Token block ──────────────────────────────────────

function _buildHfTokenBlock() {
  const details = document.createElement("details");
  details.className = "hf-token-block";

  const summary = document.createElement("summary");
  summary.textContent = t("hf_section_label", state.lang);
  details.appendChild(summary);

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = t("hf_token_hint", state.lang);
  details.appendChild(hint);

  const row = document.createElement("div");
  row.className = "folder-row";  // reuse existing flex row style

  const tokenInput = document.createElement("input");
  tokenInput.type = "password";
  tokenInput.placeholder = t("hf_token_placeholder", state.lang);
  tokenInput.value = state.hfToken || "";
  tokenInput.autocomplete = "off";
  tokenInput.spellcheck = false;
  tokenInput.addEventListener("input", () => {
    // Trim whitespace pasted from token UIs.
    state.hfToken = tokenInput.value.trim();
    // NOTE: we intentionally do NOT call saveState() here — the token
    // stays in memory only (see main.js::saveState filter).
  });
  row.appendChild(tokenInput);

  const copyBtn = document.createElement("button");
  copyBtn.className = "btn-secondary";
  copyBtn.type = "button";
  copyBtn.textContent = t("hf_get_token_btn", state.lang);
  copyBtn.addEventListener("click", async () => {
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(HF_TOKENS_URL);
        copied = true;
      }
    } catch (_) {
      copied = false;
    }
    copyBtn.textContent = copied
      ? t("hf_get_token_btn_copied", state.lang)
      : HF_TOKENS_URL;
    setTimeout(() => {
      copyBtn.textContent = t("hf_get_token_btn", state.lang);
    }, 2500);
  });
  row.appendChild(copyBtn);

  details.appendChild(row);
  return details;
}

// ── HW badges ─────────────────────────────────────────────────

function _buildHwBadges() {
  const hw = state.hardware;
  const wrap = document.createElement("div");
  wrap.className = "hw-badges";
  [
    { label: "RAM", value: hw.ram_gb + " GB" },
    { label: t("hw_os", state.lang), value: (hw.os || "—").split(" ").slice(0, 2).join(" ") },
    { label: t("hw_disk", state.lang), value: hw.disk_free_gb + " GB" },
  ].forEach(({ label, value }) => {
    const badge = document.createElement("div");
    badge.className = "hw-badge";
    const l = document.createElement("span");
    l.className = "hw-badge-label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "hw-badge-value";
    v.textContent = value;
    badge.appendChild(l);
    badge.appendChild(v);
    wrap.appendChild(badge);
  });
  return wrap;
}
