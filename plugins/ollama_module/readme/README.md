# Ollama Module — Server Nexe

Integracio amb Ollama per executar models LLM locals sense dependencies de cloud.
Chat amb streaming, gestio de models, download, embeddings locals.

## Endpoints

| Metode | Ruta | Auth | Descripcio |
|--------|------|------|------------|
| GET | /ollama/health | No | Health check |
| GET | /ollama/info | No | Info del modul |
| GET | /ollama/api/models | No | Llistar models |
| POST | /ollama/api/chat | Si | Chat streaming |
| POST | /ollama/api/pull | Si | Descarregar model |
| DELETE | /ollama/api/models/{name} | Si | Eliminar model |
| GET | /ollama/ui | No | Status page |

## CLI

```bash
python -m plugins.ollama_module
# O via nexe:
nexe ollama status
nexe ollama models
nexe ollama chat
```
