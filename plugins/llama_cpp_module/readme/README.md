# Llama.cpp Module — Server Nexe

Motor d'inferencia universal Llama.cpp (GGUF) per server-nexe.
Suport GPU (Metal/CUDA) i CPU amb gestio de sessions via ModelPool i prefix caching.

## Endpoints

| Metode | Ruta | Descripcio |
|--------|------|------------|
| GET | /llama-cpp/info | Info del modul |
| POST | /llama-cpp/chat | Chat amb model GGUF |

## CLI

```bash
python -m plugins.llama_cpp_module info
python -m plugins.llama_cpp_module health
```
