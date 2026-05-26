# nexe-app

**App Desktop OSS per server-nexe.**

Shell Tauri v2 que empaqueta server-nexe (sidecar Python amb venv relocatable) i la UI web existent. Afegeix agent navegador (Playwright+Chromium), sistema visual de plugins i distribució DMG/AppImage.

## Principis

- **Thin shell / thick backend:** Tauri = finestra + permisos + lifecycle. Tota la lògica a server-nexe.
- **Sidecar empaquetada:** Release → server-nexe dins l'app. Dev → server-nexe extern.
- **Navegador desacoblat:** Chromium gestionat per Playwright al backend, MAI al webview de Tauri.
- **IPC híbrid:** HTTP/WS per dades IA, Tauri Commands per funcions natives.
- **Zero cloud:** Tot local, zero dependències externes obligatòries.

## Stack

| Capa | Tecnologia |
|---|---|
| Shell | Tauri v2 (Rust stable 1.88+) |
| Frontend | HTML/CSS/JS vanilla existent |
| Node tooling | Node.js 24 LTS + pnpm 10 |
| Backend | Python 3.11+ + FastAPI + Uvicorn |
| Empaquetament | venv relocatable via `build-python-bundle.sh` |
| Vector DB | Qdrant |
| LLM | Ollama |
| Agent browser | Playwright Python + Chromium |
| Packaging | DMG signat/notaritzat · AppImage |

## Plataformes

- macOS Apple Silicon (principal)
- Linux x86_64 (CI + UTM/OrbStack per dev)

## Estat

**Fase 0 ✅ COMPLETA** (2026-04-17) + **Sprint 0.15** (sanejament pre-Fase 1, 2026-04-18).

Següent: Fase 1 — Shell + UI empaquetada.

## Prerequisits (macOS + Linux)

| Eina | Versió | Instal·lació |
|---|---|---|
| Rust | stable ≥ 1.88 | `rustup update stable` |
| Node.js | 24 LTS o 25.x | `nvm install 24 --lts` |
| pnpm | 10.x | `npm i -g pnpm@10` |
| tauri-cli | ^2.10 | `cargo install tauri-cli --version "^2.10"` |
| macOS | 13+ Ventura | WKWebView requirement |
| Linux | WebKitGTK 4.1+ | `apt install libwebkit2gtk-4.1-dev` |

## Quickstart

```bash
git clone <repo>
cd nexe-app
pnpm install
cd src-tauri && cargo check
cargo tauri dev   # obre finestra 800x600 + iframe plugin://rag
```

## Estimació

- MVP (Fases 0-2): 5-7 setmanes
- v1 complet (Fases 0-5): 14-18 setmanes (1 dev + IA)
- v2 multimèdia (Fase 6): +4-6 setmanes

## Documentació

- ADRs arquitectònics: `docs/adr/` (16 fitxers amb decisions fonamentals, ADRs 0001-0016)
- Contracte API v0 (exemple sidecar): `docs/api-contract-v0.md`
- TEMPLATE.md — guia per clonar aquest starter a una nova app

## Repos relacionats

| Repo | Rol |
|---|---|
| `server-nexe` | Core API (sidecar empaquetada) |
| `plugins-nexe` | Plugins comunitaris (obert a PRs) |
| **`nexe-app`** | Shell Tauri + distribució |
