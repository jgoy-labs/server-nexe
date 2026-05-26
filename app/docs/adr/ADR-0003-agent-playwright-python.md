# ADR-0003: Agent navegador amb Playwright Python

**Data:** 2026-04-17
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

L'agent IA de nexe-app ha de poder controlar un navegador real (clics, formularis, screenshots, DOM summary). Això requereix **CDP (Chrome DevTools Protocol)**. Els webviews natius de Tauri (WKWebView/WebKitGTK) NO suporten CDP.

## Decisió

**Playwright Python + Chromium com a procés fill gestionat pel backend** (server-nexe).

- Plugin `browser-runner` (a `plugins-nexe`) encapsula l'agent
- Chromium viu FORA del webview Tauri, com a procés independent
- Visualització a la UI: HTML5 canvas + screenshots base64 via WebSocket
- Finestra secundària Tauri opcional per "mode headed" (usuari activable)

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **CEF (Chromium Embedded Framework)** dins Tauri | Experimental a Tauri v2, destrueix la lleugeresa del shell, complexitat binding Rust↔C++ |
| **Qt WebEngine** | Implica canviar de shell (descartat a ADR-0001) |
| **browser-use cloud** | No sobirà (trenca principi bàsic) |
| **Selenium** | Menys precís que Playwright, més lent |
| **Puppeteer (Node)** | Duplicació de runtime — ja tenim Python al backend |

## Conseqüències

**Positives:**
- CDP complet i oficial — control total del navegador
- Cross-platform (macOS + Linux) amb `playwright install chromium`
- Integració natural amb stack Python existent
- Zero impacte al bundle Tauri (Chromium viu fora)
- Audit trail integrable amb l'audit log existent de server-nexe

**Negatives / riscos:**
- Afegeix dependència Chromium (~200MB) → canals `lite`/`full` gestionen
- Playwright requereix versió concreta de Chromium (gestionada per `playwright install`)
- Perfils Chromium persistents poden créixer → per defecte efímers per tasca

**Mitigacions:**
- Canal `lite` fa `playwright install chromium` al primer arrencat (progress bar UI)
- Perfils efímers per defecte, persistents opcional per l'usuari
- CI valida ambdues arquitectures (arm64 + x86_64)

## Referències

- original plan (not in template)
- [Playwright Python docs](https://playwright.dev/python/)
