// F5.3 Step 0 — Splash / extraction progress.
//
// Shown while the sidecar bundle is being extracted on first launch.
// Listens for "extract-progress" Tauri events emitted by lib.rs.
// If no event arrives within 600 ms (bundle already extracted) transitions
// directly to Step 1.

import { listen } from "@tauri-apps/api/event";
import { goToStep, state } from "./main.js";
import { t } from "./i18n.js";

export async function step0() {
  const app = document.getElementById("onboarding-app");
  app.replaceChildren();

  const wrapper = document.createElement("div");
  wrapper.className = "step step0";

  const msg = document.createElement("p");
  msg.className = "splash-msg";
  msg.textContent = t("step0_extracting", state.lang);
  wrapper.appendChild(msg);

  const bar = document.createElement("progress");
  bar.className = "splash-bar";
  bar.max = 100;
  bar.value = 0;
  wrapper.appendChild(bar);

  app.appendChild(wrapper);

  let received = false;

  const unlisten = await listen("extract-progress", (event) => {
    received = true;
    const pct = event.payload?.percent ?? 0;
    const stage = event.payload?.stage;
    bar.value = pct;
    if (stage) msg.textContent = stage;
    if (pct >= 100) {
      unlisten();
      goToStep(1);
    }
  });

  // If bundle was already extracted no event will arrive — skip after 600 ms.
  setTimeout(() => {
    if (!received) {
      unlisten();
      goToStep(1);
    }
  }, 600);
}
