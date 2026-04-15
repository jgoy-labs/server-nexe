---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "1.0"
data: 2026-04-15
id: 20260415-b2-sync-dmg-notaritzat
abstract: "Sessió sync intensa: 6 tags gitoss (b→f), notarització Apple desbloqueada (403 acord caducat signat), fix installer backends, Finder crash macOS independent."
tags: [server-nexe, sync, gitoss, dmg, notaritzat, installer, finder, macos]
chunk_size: 800
priority: P1
project: server-nexe
area: dev
type: sessio
estat: published
lang: ca
author: "Jordi Goy"
---

# 2026-04-15 B.2 — Sync massiu + notarització desbloqueada

#diari #server-nexe

↑ [[nat/dev/server-nexe/diari/INDEX_DIARI|Diari server-nexe]]

## Què s'ha fet

- **6 syncs gitoss** en una sola tarda (tags `20260415b` → `20260415f`)
- **Notarització Apple desbloqueada** — estava fallant amb 403 (acord Developer Program caducat). Jordi l'ha signat a developer.apple.com i ara funciona
- **Fix installer backends** (`5d72a92`) — l'installer ara aprova sempre els 3 backends (ollama, mlx, llama_cpp). Cada mòdul té init defensiu i es desactiva sol si la dep falta
- **Fix readiness** (`e1dc628`) — engines d'inferència marcats com opcionals al check de readiness
- **Fix auto-discover models** (`46eae5a`) — models a `storage/models/` detectats automàticament al boot
- Detectat i resolt bug timing de `ship-nexe.sh`: commits no commitejats al moment del dry-run no es detecten (usar `/gitoss` per forçar sync manual en aquests casos)
- **Finder crash** — Finder peta repetidament. Aparentment problema macOS independent (no relacionat amb Nexe). DMG estava muntat (`/Volumes/Install Nexe`) quan Finder va petar; expulsat, però Finder seguia sense arrencar. Jordi ha reiniciat per resoldre. **Cal investigar** si passa sovint.

## Commits sincronitzats avui

| Tag | Commit gitoss | Fitxers | Contingut |
|-----|--------------|---------|-----------|
| `20260415b` | `ecfc2ef` | 3 | web_ui_module UI (app.js, index.html, style.css) |
| `20260415c` | `b81371d` | 1 | web_ui_module UI (app.js) |
| `20260415d` | `35d453f` | 2 | installer: tots 3 backends sempre (via `/gitoss` manual) |
| `20260415e` | `3cecfa9` | 3 | install.py, llama_cpp/config.py, mlx/config.py |
| `20260415f` | (ship-nexe) | 1 | core/endpoints/root.py (readiness opcional) |

## Problemes

- **Notarització 403** — `xcrun notarytool` retornava 403 perquè l'acord Developer Program havia caducat. El script confonia error 403 amb "credencials no trobades" (missatge enganyós). Fix: signar acord a developer.apple.com. **Millora proposada a ship-nexe.sh/build_dmg.sh**: distingir 403 de "no credentials".
- **Bug timing ship-nexe.sh** — commits fets DESPRÉS del dry-run no es detecten si el dry-run i el `--go` es fan amb gap de temps. En aquest cas, `installer_setup_config.py` i `installer_setup_env.py` estaven commitejats però el dry-run previ ja havia dit "0 fitxers". Solució: `/gitoss` manual.
- **Finder crash** — `/Volumes/Install Nexe` muntat deixat per build_dmg.sh. Pot interferir amb Finder si el DMG queda muntat. **Investigar freqüència** — Jordi diu que passa sovint i interfereix. Possible que el build DMG deixi volums penjats amb macOS 26 (Tahoe beta).

## Decisions

- Notarització sempre activada (ara que l'acord funciona). No usar `--test` per DMGs de distribució.
- `/sincro-nexe` és el happy path; `/gitoss` per casos amb commits uncommitted o timing issues.

## Canvis per gitoss

Tots els canvis d'avui ja estan sincronitzats (tags b→f). Cap fitxer pendent.

## Estat i pròxims passos

- [ ] Investigar Finder crash — vol dir que passa sovint. Possible relació amb DMG muntat (`/Volumes/Install Nexe`) que el build deixa penjat. Afegir `hdiutil detach` explícit a `build_dmg.sh` al final?
- [ ] Proposar a `/governanca`: millorar missatge 403 de `build_dmg.sh` (distingir "acord caducat" de "credencials no trobades")
- [ ] Proposar a `/governanca`: millorar `ship-nexe.sh` per detectar commits uncommitted (ara usa `git diff tag..HEAD`, no veu working tree)
- [ ] Push a GitHub pendent (múltiples commits acumulats)
- [ ] Test install neta amb DMG `20260415f` per verificar fix readiness + backends
