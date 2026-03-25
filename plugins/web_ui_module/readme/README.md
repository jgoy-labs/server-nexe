# Web UI Module — Server Nexe

Interficie web estil Ollama per demostrar sistema modular de Nexe.
Chat amb streaming, sessions, upload de fitxers amb RAG, multi-engine.

## Endpoints

| Metode | Ruta | Auth | Descripcio |
|--------|------|------|------------|
| GET | /ui/ | No | Pagina principal |
| POST | /ui/chat | Si | Chat amb LLM |
| POST | /ui/upload | Si | Upload fitxer |
| GET | /ui/backends | Si | Llistar backends |
| POST | /ui/backend | Si | Canviar backend |

## CLI

```bash
python -m plugins.web_ui_module info
python -m plugins.web_ui_module health
```
