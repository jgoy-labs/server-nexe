# Nexe - Comandes / Commands

## 🚀 Ús bàsic / Basic usage

### Iniciar servidor / Start server
```bash
./nexe go
```

### Xat interactiu / Interactive chat
```bash
./nexe chat
```

### Xat amb motor específic / Chat with specific engine
```bash
./nexe chat --engine mlx
./nexe chat --engine ollama
./nexe chat --engine llama_cpp
```

## 📊 Comandes de sistema / System commands

```bash
./nexe status          # Estat del sistema / System status
./nexe logs            # Veure logs / View logs
./nexe health          # Health check
```

## 🧠 Gestió de memòria / Memory management

```bash
./nexe memory store "text"     # Guardar a memòria / Save to memory
./nexe memory recall "query"   # Cercar a memòria / Search memory
```

## 📚 Gestió de coneixement / Knowledge management

```bash
./nexe knowledge ingest        # Processar documents / Process documents
./nexe knowledge list          # Llistar documents / List documents
```

## ⚙️ Configuració / Configuration

- **Fitxer principal / Main file**: `.env`
- **Personalitat / Personality**: `personality/server.toml`
- **Models**: `storage/models/`
- **Logs**: `storage/logs/`

## 🔧 Troubleshooting

### Verificar MLX / Check MLX
```bash
./venv/bin/python -c "import mlx.core as mx; print('MLX:', mx.metal.is_available())"
```

### Reinstal·lar dependències / Reinstall dependencies
```bash
./venv/bin/pip install -r requirements.txt
```

---

📝 **Model actual / Current model**: Gemma 3 4B
🔧 **Motor / Engine**: mlx
💾 **Ubicació / Location**: `~/server-nexe` (o on l'hagis instal·lat / or wherever you installed it)

*Personal project by Jordi Goy · www.jgoy.net · https://server-nexe.org*
