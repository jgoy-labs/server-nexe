# ADR-0001: Shell Tauri v2

**Data:** 2026-04-17
**Estat:** Accepted
**Decidit per:** Jordi Goy

## Context

Cal una finestra nativa multi-plataforma (macOS + Linux) per a nexe-app que:
- Embegui UI web existent de server-nexe (220K línies)
- Sigui lleugera (prioritat per Apple Silicon + Linux x86_64)
- Permeti distribució OSS amb CI/CD manejable
- Tingui bona seguretat i sandboxing

## Decisió

**Tauri v2** com a shell natiu (Rust backend + webview del sistema).

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **Electron** | 150-350MB, alt RAM, superfície d'atac gran, reputació negativa comunitat OSS |
| **Flutter Desktop** | Control de navegador difícil, Dart no encaixa amb Python/Rust |
| **Qt WebEngine** | Més pesat i complex, llicència LGPL/GPL complicada per OSS |
| **Fork de navegador** | Inviable de mantenir per un sol dev |
| **Sciter / Ultralight** | No prou madurs per l'abast |

## Conseqüències

**Positives:**
- Bundle ~10MB (shell Rust) + assets
- WRY (Tauri webview) aprofita WKWebView (macOS) i WebKitGTK (Linux)
- Seguretat per defecte (capabilities, CSP, shell scopes)
- Ecosistema de plugins oficials (Store, Stronghold, Single Instance, etc.)
- Suport multi-webview nadiu

**Negatives / riscos:**
- WKWebView i WebKitGTK no són idèntics: risc de divergència de comportament
- Webviews natius NO suporten CDP (per això l'agent usa Chromium separat — veure ADR-0003)
- Comunitat més petita que Electron

**Mitigacions:**
- Testing específic per plataforma (XCTest/XCUITest a macOS, tauri-driver a Linux)
- UTM + OrbStack per validació local Linux

## Referències

- original plan (not in template)
- [Tauri v2 docs](https://tauri.app/)
