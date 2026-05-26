// F5.3 Step 4 — Download complete confirmation.

import { goToStep, state } from "./main.js";
import { t } from "./i18n.js";

export function step4() {
  const app = document.getElementById("onboarding-app");
  app.replaceChildren();

  const wrapper = document.createElement("div");
  wrapper.className = "step step4";

  const icon = document.createElement("div");
  icon.className = "success-icon";
  icon.textContent = "✓";
  wrapper.appendChild(icon);

  const title = document.createElement("h2");
  title.textContent = t("step4_title", state.lang);
  wrapper.appendChild(title);

  const body = document.createElement("p");
  body.textContent = t("step4_body", state.lang);
  wrapper.appendChild(body);

  const trayHint = document.createElement("p");
  trayHint.className = "step4-tray-hint";
  trayHint.textContent = t("step4_tray_hint", state.lang);
  wrapper.appendChild(trayHint);

  const btn = document.createElement("button");
  btn.className = "btn-primary";
  btn.textContent = t("btn_next", state.lang);
  btn.addEventListener("click", () => goToStep(5));
  wrapper.appendChild(btn);

  app.appendChild(wrapper);
}
