# ADR-0009: Protocol `plugin://` per servir assets de plugins

**Data:** 2026-04-17
**Estat:** Accepted (spike validat)
**Decidit per:** Jordi Goy

## Context

ADR-0007 estableix 3 nivells de plugins (core / first-party / third-party) on els first/third-party renderitzen UI via iframe. Cal decidir com es serveixen els assets (HTML/CSS/JS) al webview:

- **Opció A:** via HTTP de server-nexe (ruta dedicada `/v1/plugins/:id/ui/*`)
- **Opció B:** via protocol custom `plugin://` registrat pel Rust core de Tauri

El pla de Fase 0 marca aquest dilema com a **spike** per validar empíricament l'opció B abans de comprometre-s'hi per Fase 4.

## Decisió

**Opció B — protocol `plugin://` via `register_uri_scheme_protocol`.**

Implementació validada el 2026-04-17 amb un plugin fictici (`plugins-dev/rag/`) i iframe carregat des de `plugin://rag/index.html`. Funciona tal qual en dev, sense necessitat de modificar CSP (CSP null per defecte al scaffold).

### Handler (resum)

```rust
fn plugin_protocol_handler<R: tauri::Runtime>(
    _ctx: UriSchemeContext<'_, R>,
    request: Request<Vec<u8>>,
) -> Response<Vec<u8>> {
    let plugin_id = request.uri().host().unwrap_or("");
    let path = request.uri().path();
    let file_path = plugins_root()
        .join(plugin_id)
        .join("ui")
        .join(path.trim_start_matches('/'));

    // Anti path traversal via canonicalize
    // Content-Type per extensió
    // 403 si fora scope, 404 si no existeix, 200 amb bytes si OK
}
```

Registrat al builder:
```rust
tauri::Builder::default()
    .register_uri_scheme_protocol("plugin", plugin_protocol_handler)
```

## Alternatives considerades

| Opció | Motiu descart |
|---|---|
| **A. HTTP via server-nexe** | Latència HTTP per a fitxers estàtics, backend ha d'estar corrent per servir UI, acoblament innecessari |
| **C. Servir via file://** | Tauri restringeix file:// al webview, no gestionable per plugin |
| **D. Bundle UI de cada plugin com a assets Tauri** | Perdem hot-reload de plugins, trenca modularitat |

## Conseqüències

**Positives:**
- **Zero acoblament amb server-nexe** per servir UI (Rust serveix directament del FS)
- Latència quasi nul·la (no passa per HTTP)
- Scope limitat al FS de plugins (path traversal bloquejat per canonicalize)
- Hot-reload natural del FS via notify crate (Fase 4)
- Funciona en dev amb CSP null, probable fine-tune CSP a Fase 4

**Negatives / riscos:**
- Cal paritat macOS/Linux (WKWebView vs WebKitGTK respecten `plugin://` diferent?) — **validat només macOS a v0, pendent Linux**
- En release el `plugins-dev/` path apunta a `app_data_dir()/plugins-user/` + `resources/plugins/` — cal abstracció
- Quan afegim CSP estricta (Fase 5), caldrà `connect-src 'self' plugin:` i `frame-src 'self' plugin:`

**Mitigacions:**
- Test a Linux (UTM) abans de Fase 4 tancar
- Plugin root abstracció via funció `plugin_root_for(id)` que escull dev/release/user segons mode
- CSP estricta passa al pas de hardening de Fase 5 amb testing explícit

## Resultat del spike

| Check | Resultat |
|---|---|
| Compilat sense warnings | ✅ (`cargo check` 1.10s) |
| Iframe carrega UI plugin | ✅ (fons fosc, h1 verd, path/origin mostrats) |
| `window.location.origin` correcte | `plugin://rag` ✅ |
| Path traversal bloquejat | ✅ (canonicalize check) |
| Content-Type per extensió | ✅ (html/css/js/json/svg/png) |
| macOS Apple Silicon | ✅ |
| Linux x86_64 | 🔜 pendent (probablement funciona, WKWebView i WebKitGTK comparteixen API scheme) |

## Referències

- original plan (not in template)
- [ADR-0007 Plugins 3 nivells](ADR-0007-plugins-tres-nivells.md)
- Implementació: `src-tauri/src/lib.rs` → `plugin_protocol_handler`
- Test fixtures: `plugins-dev/rag/`
- [Tauri docs — register_uri_scheme_protocol](https://docs.rs/tauri/latest/tauri/)
