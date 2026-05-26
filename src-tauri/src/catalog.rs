//! F5.3: Model catalog Tauri command for the onboarding wizard.
//!
//! Fetches the model catalog from the remote manifest URL (5 s timeout)
//! and falls back to the embedded JSON when the network is unavailable.
//! All parsing happens in Rust — the HTML frontend never sees raw JSON from
//! an untrusted source.

use serde::{Deserialize, Serialize};

/// A single model entry returned to the onboarding frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogModel {
    pub name: String,
    pub params: String,
    /// RAM requirement in GB (f64 to match JSON export from Python catalog).
    pub ram_gb: f64,
    pub disk_gb: f64,
    /// Available backends, e.g. ["MLX", "Ollama", "llama.cpp"].
    pub backends: Vec<String>,
    /// Feature flags, e.g. ["vision", "thinking", "catalan"].
    pub flags: Vec<String>,
    /// Origin string, e.g. "Google DeepMind".
    pub origin: String,
    pub ollama: Option<String>,
    pub mlx: Option<String>,
    pub gguf: Option<String>,
    /// Gated model indicator from HuggingFace ("manual", "auto", or None).
    /// F5.5 G7: exposed so the frontend can show a 🔒 badge in Step 2.
    #[serde(default)]
    pub gated: Option<String>,
    /// Optional license URL for gated models.
    #[serde(default)]
    pub license_url: Option<String>,
}

/// Embedded fallback catalog (built into the binary at compile time).
const FALLBACK_CATALOG: &str =
    include_str!("../resources/catalog_fallback.json");

/// Remote manifest URL. Fetched with a 5 s timeout; falls back to embedded on any error.
///
/// F5.7 bootstrap (2026-05-20 nit): points to the `catalog-bootstrap` branch of
/// the public `server-nexe` repo. The earlier URL (`jgoy-labs/nexe-app/main/public/`)
/// was unreachable because `nexe-app` is still PRIVATE — every fetch 404'd and
/// fell through to the embedded fallback. With this URL the remote manifest is
/// actually consumed.
///
/// Migration to `main` branch happens when the Factoria push lands at GitHub
/// (see TODO-factoria-nexe.md §F5.7a).
const MANIFEST_URL: &str =
    "https://raw.githubusercontent.com/jgoy-labs/server-nexe/catalog-bootstrap/docs/catalog.json";

/// Return the model catalog for the onboarding wizard.
///
/// Called via `invoke("fetch_catalog")` from the frontend (Step 2).
/// Uses the remote manifest when available; falls back to the embedded JSON silently.
/// Does not require the sidecar.
#[tauri::command]
pub async fn fetch_catalog() -> Vec<CatalogModel> {
    // Attempt remote fetch with timeout.
    if let Ok(client) = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
    {
        match client.get(MANIFEST_URL).send().await {
            Ok(resp) => {
                let status = resp.status();
                match resp.json::<Vec<CatalogModel>>().await {
                    Ok(models) if !models.is_empty() => {
                        tracing::info!(
                            url = %MANIFEST_URL,
                            count = models.len(),
                            "catalog: remote manifest consumed",
                        );
                        return models;
                    }
                    Ok(_) => {
                        tracing::warn!(
                            url = %MANIFEST_URL,
                            status = %status,
                            "catalog: remote manifest empty — falling back to embedded",
                        );
                    }
                    Err(e) => {
                        tracing::warn!(
                            url = %MANIFEST_URL,
                            status = %status,
                            error = %e,
                            "catalog: remote manifest deserialise failed — falling back to embedded",
                        );
                    }
                }
            }
            Err(e) => {
                tracing::warn!(
                    url = %MANIFEST_URL,
                    error = %e,
                    "catalog: remote manifest fetch failed — falling back to embedded",
                );
            }
        }
    }
    // Silent fallback to embedded catalog.
    tracing::info!("catalog: using embedded fallback");
    serde_json::from_str(FALLBACK_CATALOG).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fallback_catalog_is_valid_json() {
        let models: Vec<CatalogModel> =
            serde_json::from_str(FALLBACK_CATALOG).expect("embedded catalog must be valid JSON");
        assert!(!models.is_empty(), "embedded catalog must have at least one model");
    }

    #[test]
    fn fallback_catalog_models_have_required_fields() {
        let models: Vec<CatalogModel> =
            serde_json::from_str(FALLBACK_CATALOG).unwrap();
        for m in &models {
            assert!(!m.name.is_empty(), "model name must not be empty");
            assert!(m.ram_gb > 0.0, "model ram_gb must be > 0 for {}", m.name);
            assert!(m.disk_gb > 0.0, "model disk_gb must be > 0 for {}", m.name);
            assert!(
                !m.backends.is_empty(),
                "model {} must have at least one backend",
                m.name
            );
        }
    }

    #[test]
    fn fallback_catalog_has_minimum_models() {
        let models: Vec<CatalogModel> =
            serde_json::from_str(FALLBACK_CATALOG).unwrap();
        assert!(
            models.len() >= 3,
            "fallback catalog must have >= 3 models, got {}",
            models.len()
        );
    }

    #[test]
    fn gated_field_preserved_through_deserialization() {
        // F5.5 G7: verify gated field survives Rust deserialization (Serde
        // used to silently drop it because CatalogModel lacked the field).
        // Uses a synthetic JSON literal so the test does not depend on any
        // specific entry of the fallback catalog (which may shrink/grow).
        let json = r#"[{
            "name": "Test Model",
            "params": "4B",
            "ram_gb": 4.0,
            "disk_gb": 3.3,
            "backends": ["MLX", "Ollama"],
            "flags": [],
            "origin": "Test",
            "ollama": "test:4b",
            "mlx": null,
            "gguf": null,
            "gated": "manual",
            "license_url": "https://example.test/license"
        }]"#;
        let models: Vec<CatalogModel> = serde_json::from_str(json).unwrap();
        assert_eq!(models[0].gated.as_deref(), Some("manual"));
        assert_eq!(
            models[0].license_url.as_deref(),
            Some("https://example.test/license"),
        );
    }

    #[test]
    fn fallback_catalog_non_gated_models_have_none() {
        let models: Vec<CatalogModel> =
            serde_json::from_str(FALLBACK_CATALOG).unwrap();
        // Non-gated models (e.g. Qwen3.5 4B) must deserialize with gated=None
        let non_gated = models.iter().find(|m| m.name == "Qwen3.5 4B");
        if let Some(m) = non_gated {
            assert!(
                m.gated.is_none(),
                "Qwen3.5 4B must not be gated, got {:?}",
                m.gated
            );
        }
    }
}
