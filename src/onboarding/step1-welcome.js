// F5.3 Step 1 — Welcome screen with language selector.

import { invoke } from "@tauri-apps/api/core";
import { goToStep, state, saveState } from "./main.js";
import { t } from "./i18n.js";

export function step1() {
  const app = document.getElementById("onboarding-app");
  app.replaceChildren();

  const wrapper = document.createElement("div");
  wrapper.className = "step step1";

  // Official server-nexe logo
  const logo = document.createElement("img");
  logo.src = "/onboarding-logo.png";
  logo.alt = "server-nexe";
  logo.className = "nexe-logo";
  wrapper.appendChild(logo);

  // Language selector
  const langRow = document.createElement("div");
  langRow.className = "lang-row";

  const langLabel = document.createElement("label");
  langLabel.textContent = t("language_label", state.lang);
  langLabel.htmlFor = "lang-select";

  const langSelect = document.createElement("select");
  langSelect.id = "lang-select";
  [
    { code: "ca", label: "Català" },
    { code: "es", label: "Español" },
    { code: "en", label: "English" },
  ].forEach(({ code, label }) => {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = label;
    if (code === state.lang) opt.selected = true;
    langSelect.appendChild(opt);
  });
  langSelect.addEventListener("change", () => {
    state.lang = langSelect.value;
    saveState();
    step1();
  });

  langRow.appendChild(langLabel);
  langRow.appendChild(langSelect);
  wrapper.appendChild(langRow);

  // Title
  const title = document.createElement("h1");
  title.textContent = t("welcome_title", state.lang);
  wrapper.appendChild(title);

  // Body text
  const body = document.createElement("p");
  body.textContent = t("welcome_body", state.lang);
  wrapper.appendChild(body);

  // Next button
  const btn = document.createElement("button");
  btn.className = "btn-primary";
  btn.textContent = t("btn_next", state.lang);
  btn.addEventListener("click", () => goToStep(2));
  wrapper.appendChild(btn);

  // Partial-install banner — injected async after render if applicable.
  invoke("check_partial_install")
    .then((partial) => {
      if (!partial) return;
      const banner = document.createElement("div");
      banner.className = "partial-install-banner";

      const notice = document.createElement("p");
      notice.textContent = t("partial_install_notice", state.lang);
      banner.appendChild(notice);

      const resetBtn = document.createElement("button");
      resetBtn.className = "btn-secondary btn-reset-install";
      resetBtn.textContent = t("btn_reset_install", state.lang);
      resetBtn.addEventListener("click", () => {
        if (!window.confirm(t("reset_install_confirm", state.lang))) return;
        invoke("reset_installation").finally(() => location.reload());
      });
      banner.appendChild(resetBtn);

      wrapper.insertBefore(banner, btn);
    })
    .catch(() => {});

  // Footer
  const footer = document.createElement("div");
  footer.className = "onboarding-footer";
  const link = document.createElement("a");
  link.textContent = "server-nexe.com";
  link.href = "#";
  link.className = "footer-link";
  link.addEventListener("click", (e) => {
    e.preventDefault();
    invoke("open_external_url", { url: "https://server-nexe.com" });
  });
  footer.appendChild(link);
  wrapper.appendChild(footer);

  app.appendChild(wrapper);
}
