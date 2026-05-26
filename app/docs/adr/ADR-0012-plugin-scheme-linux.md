# ADR-0012: `plugin://` scheme a Linux WebKitGTK — VERIFICAT ✅

**Data:** 2026-04-18
**Estat:** Accepted — **Empirically verified 2026-04-18** (Sprint 0.15 #6)
**Decidit per:** Jordi Goy
**Entorn de validació:** Holodeck (UTM + Ubuntu 24.04 ARM64 + WebKitGTK 2.50.4)

## Context

ADR-0009 va validar el scheme `plugin://` via `register_asynchronous_uri_scheme_protocol` a **macOS WKWebView**. Tauri v2 usa WRY, que abstreu darrere WKWebView (macOS) o WebKitGTK (Linux). Els dos motors no són idèntics i cada custom URI scheme pot tenir diferències:

- Polítiques de CSP diferents per schemes custom
- Propagació d'`Origin` headers diferent (WebKitGTK pot ometre)
- Cache behavior diferent
- Gestió d'errors diferent

Calia **validar empíricament** que `plugin://rag/index.html` carrega correctament dins un iframe sandboxed a Linux abans de comprometre's amb `plugin://` per Fase 4.

## Resultat empíric — 2026-04-18

**Entorn de test:**
- Màquina: Mac Studio M4 Max + UTM + VM anomenada **Holodeck**.
- OS VM: Ubuntu **24.04** Desktop ARM64 (més modern que el 22.04 del runner CI).
- Web engine: WebKitGTK **2.50.4**.
- Stack: Tauri v2.10.3, Rust stable, pnpm 10, Node 22.
- Build: `pnpm tauri dev` des del repo clonat a la VM.

**Verificat:**

- ✅ L'app nexe-app arrenca dins Ubuntu, mostra finestra Tauri nativa (títol "nexe-app").
- ✅ UI principal carrega correctament (sense errors).
- ✅ **Iframe `plugin://rag/index.html` carrega el plugin RAG spike** — visible secció "RAG plugin (spike)" amb el contingut servit pel handler Rust (`plugin_protocol_handler` a `lib.rs`).
- ✅ CSP `frame-src 'self' plugin:` respectada.
- ✅ Isolation Pattern (ADR-0013) operatiu — command `greet` passa pel filtre i executa correctament.
- ✅ **41 tests Rust + 13 tests vitest verds** a la VM Linux (mateix resultat que a macOS).

Veure diari de la sessió: [internal dev diary, not exposed in OSS repo].

## Decisió

**`plugin://` scheme cross-platform verificat.** Fase 4 pot construir-se amb `plugin://` com a estàndard per a macOS + Linux amb **un sol codi path**. No és necessari cap fallback ni branca per sistema operatiu.

Observació: la validació s'ha fet a Ubuntu 24.04 (WebKitGTK 2.50.4). El runner CI (`ubuntu-22.04`) té WebKitGTK 4.1 (sense salt major). Al no detectar regressions a un WebKitGTK més modern, es considera que el CI actual (22.04) tampoc les tindrà. Si en un futur apareix alguna diferència entre 22.04 i 24.04, es pot rerun la validació amb una segona VM.

## Conseqüències confirmades

- ✅ Fase 4 es pot construir amb `plugin://` com a estàndard cross-platform
- ✅ Un sol codi path per macOS + Linux
- ✅ ADR-0009 confirmat sense errata
- ✅ El pla de consultoria externa (2026-04-17) identificava aquest com a "risc P1 probabilitat mitjana" — **risc descartat**

## Alternatives descartades (ja no necessàries)

| Si `plugin://` no hagués funcionat | Decisió |
|---|---|
| ~~`custom-protocol://` prefix Tauri-específic~~ | No cal — `plugin://` OK |
| ~~HTTP via server-nexe (ruta `/plugins/:id/ui/`)~~ | No cal |
| ~~Data URLs amb base64~~ | No cal |

## Infraestructura de test

La VM **Holodeck** (Ubuntu 24.04 ARM64) queda instal·lada com a **recurs permanent** al Mac Studio per a futurs tests cross-platform de nexe-app, server-nexe i altres projectes Tauri/Rust/Node.

## Referències

- [ADR-0009 Protocol plugin://](ADR-0009-plugin-uri-scheme.md)
- [Tauri v2 custom protocols docs](https://tauri.app/develop/protocols/)
- Consultoria 2026-04-17 (risc identificat com a P1 probabilitat mitjana — **resolt**)
- Prompt sessió Linux: [internal dev diary, not exposed in OSS repo]
- Sessió Linux: [internal dev diary, not exposed in OSS repo]
- Sprint 0.15 #6 tracking: [internal dev diary, not exposed in OSS repo]
