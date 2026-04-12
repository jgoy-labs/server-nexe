# Nexe — Commands / Comandes

**Version:** 0.9.3

## Server

```bash
./nexe go                          # Start server → http://127.0.0.1:9119
```

## Chat

```bash
./nexe chat                        # Interactive CLI chat
./nexe chat --rag                  # Chat with RAG memory
./nexe chat --verbose              # Chat with RAG weight details per source
./nexe chat --engine mlx           # Chat with specific engine
./nexe chat --engine ollama
./nexe chat --engine llama_cpp
./nexe chat --rag-threshold 0.50   # Set RAG score threshold (0.20-0.70)
./nexe chat -c memory,docs         # Only use specific collections (memory, knowledge, docs)
./nexe chat -c knowledge           # Only search user knowledge
```

## System

```bash
./nexe status                      # System status
./nexe health                      # Health check
./nexe modules                     # List loaded modules and CLIs
```

## Memory

```bash
./nexe memory store "text"         # Save text to memory
./nexe memory recall "query"       # Search memory
./nexe memory stats                # Memory statistics
```

## Knowledge

```bash
./nexe knowledge ingest            # Index documents from knowledge/ folder
./nexe knowledge list              # List indexed documents
```

## Encryption (new in v0.9.0)

```bash
./nexe encryption status           # Show encryption status of all storage
./nexe encryption encrypt-all      # Migrate existing data to encrypted format
./nexe encryption export-key       # Export master key (hex/base64, for backup)
```

Enable encryption: `export NEXE_ENCRYPTION_ENABLED=true`

## Configuration

| Setting | Location |
|---------|----------|
| Main config | `personality/server.toml` |
| API keys, env | `.env` |
| Models | `storage/models/` |
| Logs | `storage/system-logs/` |

## Web UI

```
http://127.0.0.1:9119/ui          # Web interface
http://127.0.0.1:9119/docs        # Swagger API docs
http://127.0.0.1:9119/health      # Health check
```

## Installer

```bash
# Add Nexe to macOS login items (auto-start at login)
python -m installer.install --add-login-item --app-path /Applications/Nexe.app
```

## Troubleshooting

```bash
# Check MLX availability
./venv/bin/python -c "import mlx.core as mx; print('MLX:', mx.metal.is_available())"

# Reinstall dependencies
./venv/bin/pip install -r requirements.txt

# Check what's on port 9119
lsof -i :9119

# Kill orphaned server (Quit from tray doesn't work)
pkill -f "core.app"
lsof -iTCP:9119 -sTCP:LISTEN
```

---

*server-nexe 0.9.3 · Apache 2.0 · Jordi Goy · https://server-nexe.org*
