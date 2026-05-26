// F5.3 Step 3 — Download progress via fetch + ReadableStream.
// 2026-05-23: embedder fetch removed (sidecar resolves it lazily on the first
// RAG query). Stall watchdog + visible Cancel/Retry added so a silent
// backend doesn't leave the wizard hanging forever.
//
// EventSource does not work reliably from tauri://localhost to http://127.0.0.1
// (WebKit silently drops the connection). Using fetch with a readable stream
// instead — same SSE wire format, no CORS issues with the custom scheme.

import { invoke } from "@tauri-apps/api/core";
import { goToStep, state } from "./main.js";
import { t } from "./i18n.js";

// If we go this long without any SSE event (progress/keepalive/done/error)
// from the backend, treat the download as stalled and surface a Retry button.
// Real Hugging Face downloads emit a progress event every ~1–2 s, and the
// sidecar sends a keepalive at least every 15 s, so 90 s is a safe margin
// even on slow links.
const STALL_TIMEOUT_MS = 90_000;


/** Build a labelled progress block (label + <progress> + info paragraph). */
function _buildProgressBlock(parent, labelText) {
  const block = document.createElement("div");
  block.className = "download-block";

  const label = document.createElement("p");
  label.className = "download-label";
  label.textContent = labelText;
  block.appendChild(label);

  const bar = document.createElement("progress");
  bar.className = "download-bar";
  bar.max = 100;
  bar.value = 0;
  block.appendChild(bar);

  const info = document.createElement("p");
  info.className = "download-info";
  info.textContent = "0%";
  block.appendChild(info);

  parent.appendChild(block);
  return { bar, info };
}

/**
 * Consume a single /installer/download SSE stream and update the given
 * progress widgets. Returns when the server emits `done` or `error`.
 *
 * @param {string} url        — full SSE endpoint URL with query params.
 * @param {HTMLProgressElement} bar
 * @param {HTMLElement} info
 * @param {AbortController} abortCtrl
 * @returns {Promise<{ok: true} | {ok: false, message: string}>}
 */
async function _streamDownload(url, bar, info, abortCtrl) {
  // Stall watchdog: fires abortCtrl with a sentinel reason when too long
  // passes between SSE events, so a silent backend triggers a user-visible
  // error instead of leaving the wizard hanging.
  let stallTimer = null;
  const armStall = () => {
    if (stallTimer) clearTimeout(stallTimer);
    stallTimer = setTimeout(() => {
      abortCtrl.abort(new DOMException("stalled", "AbortError"));
    }, STALL_TIMEOUT_MS);
  };
  const disarmStall = () => {
    if (stallTimer) clearTimeout(stallTimer);
    stallTimer = null;
  };
  const isUserCancel = () =>
    abortCtrl.signal.aborted && abortCtrl.signal.reason?.message !== "stalled";
  const isStall = () =>
    abortCtrl.signal.aborted && abortCtrl.signal.reason?.message === "stalled";
  const wrapAbortError = () => {
    if (isStall()) return { ok: false, message: t("step3_stalled", state.lang), stalled: true };
    if (isUserCancel()) return { ok: false, message: t("step3_cancelled", state.lang), cancelled: true };
    return null;
  };

  let response;
  armStall();
  try {
    response = await fetch(url, {
      method: "GET",
      headers: { "Accept": "text/event-stream" },
      signal: abortCtrl.signal,
    });
  } catch (err) {
    disarmStall();
    const aborted = wrapAbortError();
    if (aborted) return aborted;
    return { ok: false, message: t("step3_connection_lost", state.lang) + ": " + err.message };
  }

  if (!response.ok) {
    disarmStall();
    return { ok: false, message: `HTTP ${response.status}` };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  try {
    while (true) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch (err) {
        const aborted = wrapAbortError();
        if (aborted) return aborted;
        return { ok: false, message: t("step3_connection_lost", state.lang) + ": " + err.message };
      }
      const { done, value } = chunk;
      if (done) break;
      armStall();

      buf += decoder.decode(value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop() ?? "";

      for (const frame of frames) {
        const dataLine = frame.split("\n").find(l => l.startsWith("data: "));
        if (!dataLine) continue;
        let data;
        try { data = JSON.parse(dataLine.slice(6)); } catch (_) { continue; }

        if (data.type === "keepalive") continue;

        if (data.type === "progress") {
          const pct = Math.round(data.percent ?? 0);
          bar.value = pct;
          const parts = [pct + "%"];
          if (data.cached) parts.push(t("step3_cached", state.lang) || "(cache)");
          if (data.speed && data.speed !== "—") parts.push(t("step3_speed", state.lang) + ": " + data.speed);
          if (data.eta   && data.eta   !== "—") parts.push(t("step3_eta",   state.lang) + ": " + data.eta);
          info.textContent = parts.join(" — ");
        }

        if (data.type === "done") {
          try { reader.cancel(); } catch (_) { /* noop */ }
          bar.value = 100;
          return { ok: true };
        }

        if (data.type === "error") {
          try { reader.cancel(); } catch (_) { /* noop */ }
          return { ok: false, message: data.message || t("step3_error", state.lang) };
        }
      }
    }
    return bar.value >= 100 ? { ok: true } : { ok: false, message: t("step3_error", state.lang) };
  } finally {
    disarmStall();
  }
}

export async function step3() {
  const app = document.getElementById("onboarding-app");
  app.replaceChildren();

  const wrapper = document.createElement("div");
  wrapper.className = "step step3";

  const title = document.createElement("h2");
  title.textContent =
    t("step3_downloading", state.lang) + ": " + (state.selectedModel?.name || "");
  wrapper.appendChild(title);

  // LLM model progress block. The embedder (semantic memory) is no longer
  // downloaded from the wizard — the sidecar resolves it on demand on the
  // first RAG query, so the user sees a single progress bar here.
  const llmLabel = (state.selectedModel?.name || t("step3_llm_label", state.lang) || "Model");
  const { bar: llmBar, info: llmInfo } = _buildProgressBlock(wrapper, llmLabel);

  const waitHint = document.createElement("p");
  waitHint.className = "step3-wait-hint";
  waitHint.textContent = t("step3_wait_hint", state.lang) || "";
  wrapper.appendChild(waitHint);

  const errorEl = document.createElement("p");
  errorEl.className = "error-msg";
  wrapper.appendChild(errorEl);

  // Action row: visible Cancel while the download runs, swapped for Retry
  // when the stream errors out (network, stall watchdog, backend error).
  const actions = document.createElement("div");
  actions.className = "step3-actions";
  const cancelBtn = document.createElement("button");
  cancelBtn.className = "btn-secondary";
  cancelBtn.textContent = t("btn_cancel", state.lang) || "Cancel";
  const retryBtn = document.createElement("button");
  retryBtn.className = "btn-primary";
  retryBtn.textContent = t("btn_retry", state.lang) || "Retry";
  retryBtn.style.display = "none";
  retryBtn.addEventListener("click", () => step3());
  actions.appendChild(cancelBtn);
  actions.appendChild(retryBtn);
  wrapper.appendChild(actions);

  app.appendChild(wrapper);

  if (!state.selectedModel) {
    errorEl.textContent = t("step3_error", state.lang);
    cancelBtn.style.display = "none";
    retryBtn.style.display = "";
    return;
  }

  const port = await invoke("get_sidecar_port");
  const { engine, model_id } = state.selectedModel;

  // Single AbortController shared by the fetch + the stall watchdog. The
  // backend ThreadPoolExecutor is max_workers=1 so serial downloads here
  // match that contract.
  const abortCtrl = new AbortController();
  cancelBtn.addEventListener("click", () => {
    cancelBtn.disabled = true;
    abortCtrl.abort();
  });

  // Download the chosen LLM model. Embedder fetch deferred to the sidecar.
  const llmUrl = new URL(`http://127.0.0.1:${port}/installer/download`);
  llmUrl.searchParams.set("engine", engine);
  llmUrl.searchParams.set("model_id", model_id);
  const llmResult = await _streamDownload(llmUrl.toString(), llmBar, llmInfo, abortCtrl);
  if (!llmResult.ok) {
    errorEl.textContent = llmResult.message;
    waitHint.style.display = "none";
    cancelBtn.style.display = "none";
    retryBtn.style.display = "";
    return;
  }

  state.downloadProgress = 100;
  goToStep(4);
}
