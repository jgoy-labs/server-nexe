# MLX Module — Server Nexe

Motor d'inferencia ultra-optimitzat per Apple Silicon (M1/M2/M3/M4) usant MLX.
Inclou prefix caching real amb TTFT instantani en converses llargues.

## Endpoints

| Metode | Ruta | Descripcio |
|--------|------|------------|
| GET | /mlx/info | Info del modul |
| ~~POST~~ | ~~/mlx/chat~~ | **Removed v1.0.3-beta** — returns 403 via `RemovedDirectRoutesGuard`. Use `POST /v1/chat/completions` (OpenAI-compatible). |

## CLI

```bash
python -m plugins.mlx_module info
python -m plugins.mlx_module health
```
