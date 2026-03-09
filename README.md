# Server Nexe

[![CI](https://github.com/jgoy-labs/server-nexe/actions/workflows/ci.yml/badge.svg)](https://github.com/jgoy-labs/server-nexe/actions/workflows/ci.yml)
![Coverage](.github/badges/coverage.svg)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector--db-dc244c?logo=qdrant&logoColor=white)](https://qdrant.tech)
[![MLX](https://img.shields.io/badge/MLX-Apple%20Silicon-000000?logo=apple&logoColor=white)](https://github.com/ml-explore/mlx)
[![Ollama](https://img.shields.io/badge/Ollama-compatible-black?logo=ollama&logoColor=white)](https://ollama.com)
[![llama.cpp](https://img.shields.io/badge/llama.cpp-GGUF-8B5CF6)](https://github.com/ggerganov/llama.cpp)
[![RAG](https://img.shields.io/badge/RAG-local%20%7C%20private-22c55e)](https://github.com/jgoy-labs/server-nexe)

**Version:** 0.8 — **Author:** Jordi Goy · [www.jgoy.net](https://www.jgoy.net)

Local AI server with persistent memory, RAG, and multi-backend inference (MLX / llama.cpp / Ollama).
Runs entirely on your machine — zero data sent to external services.

## Quick start

```bash
python3 install_nexe.py   # guided installation
./nexe go                 # start server (port 9119)
./nexe chat               # interactive chat
./nexe chat --rag         # chat with RAG memory
```

## Testing (Linux)

CI runs on Ubuntu and executes the unit suite with coverage.

```bash
pip install -r requirements.txt
pytest core memory personality plugins -m "not integration and not e2e and not slow" \
  --cov=core --cov=memory --cov=personality --cov=plugins \
  --cov-report=term --cov-report=xml:coverage.xml --tb=short -q
```

To run the same suite on Linux via Docker:

```bash
./dev-tools/run_linux_ci.sh
```

## Documentation

Full documentation is in the `knowledge/` directory:

- [English](knowledge/en/README.md)
- [Català](knowledge/ca/README.md)
- [Español](knowledge/es/README.md)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md).
