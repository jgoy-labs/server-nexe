# Contributing

Thanks for helping improve **Server Nexe**.

## Local dev setup

- Python **3.11+** (CI uses 3.11)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Tests

Fast unit suite (no external services):

```bash
pytest core memory personality plugins -m "not integration and not e2e and not slow" -q
```

Integration tests may require local services (e.g. Ollama) and/or model downloads:

```bash
NEXE_AUTOSTART_OLLAMA=true pytest -m "integration" -q
```

## Pull requests

- Keep changes focused and documented.
- Include tests when behavior changes.
- Avoid adding new cloud/infrastructure assumptions (this is a local-first project).

