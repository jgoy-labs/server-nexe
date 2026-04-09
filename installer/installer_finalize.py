"""
────────────────────────────────────
Server Nexe
Location: installer/installer_finalize.py
Description: Final installation summary, COMMANDS.md generation, and disclaimer.
────────────────────────────────────
"""

from .installer_display import (
    APP_LOGO, clear,
    GREEN, YELLOW, CYAN, BOLD, DIM, RESET,
    print_warn,
)
from .installer_i18n import t


def show_final_summary(model_config, project_root, global_symlink_created, lang):
    """Display installation success screen, write COMMANDS.md, show disclaimer."""
    input(f"\n{DIM}[{t('press_enter')}]{RESET}")
    clear()
    print(APP_LOGO)
    print(f"{GREEN}✅ {t('install_complete')}{RESET}")

    print(f"\n{BOLD}🤖 Model: {CYAN}{model_config['name']}{RESET}")

    # Show API key once at end of installation
    env_file = project_root / ".env"
    api_key = ""
    try:
        for line in env_file.read_text().splitlines():
            if line.startswith("NEXE_PRIMARY_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break
    except Exception:
        pass
    if api_key:
        print(f"\n{'─'*65}")
        if lang == 'ca':
            print(f"  {YELLOW}⚠️  GUARDA AQUESTA CLAU API — la necessitaràs per connectar-te{RESET}")
        elif lang == 'es':
            print(f"  {YELLOW}⚠️  GUARDA ESTA CLAVE API — la necesitarás para conectarte{RESET}")
        else:
            print(f"  {YELLOW}⚠️  SAVE THIS API KEY — you'll need it to connect{RESET}")
        print(f"\n  🔑 {BOLD}{CYAN}{api_key}{RESET}\n")
        if lang == 'ca':
            print(f"  {DIM}Si la perds o la vols canviar, edita l'arxiu ocult .env{RESET}")
        elif lang == 'es':
            print(f"  {DIM}Si la pierdes o la quieres cambiar, edita el archivo oculto .env{RESET}")
        else:
            print(f"  {DIM}If you lose it or want to change it, edit the hidden file .env{RESET}")
        print(f"{'─'*65}")

    nexe_cmd = "nexe" if global_symlink_created else "./nexe"

    print(f"\n{BOLD}🚀 {t('how_to_start')}{RESET}")
    print(f"  {CYAN}{t('step')} 1:{RESET} {nexe_cmd} go")
    print(f"         {DIM}{t('step_start_server')}{RESET}")
    print(f"  {CYAN}{t('step')} 2:{RESET} {t('step_new_terminal')}")
    print(f"  {CYAN}{t('step')} 3:{RESET} {nexe_cmd} chat")
    print(f"         {DIM}{t('step_chat')}{RESET}")

    if not global_symlink_created:
        print(f"\n{YELLOW}📌 {t('optional_global_command') if lang != 'en' else 'OPTIONAL: Global command'}{RESET}")
        if lang == 'ca':
            print(f"  {DIM}Per executar 'nexe' des de qualsevol lloc (sense ./), executa:{RESET}")
        elif lang == 'es':
            print(f"  {DIM}Para ejecutar 'nexe' desde cualquier lugar (sin ./), ejecuta:{RESET}")
        else:
            print(f"  {DIM}To run 'nexe' from anywhere (without ./), execute:{RESET}")
        print(f"  {CYAN}sudo ln -sf {project_root}/nexe /usr/local/bin/nexe{RESET}")

    print(f"\n  {YELLOW}💡 {t('save_memory_tip')}{RESET}")
    print(f"  {DIM}💡 {t('venv_automatic')}{RESET}")

    _write_commands_file(project_root, nexe_cmd, model_config)

    print(f"\n{DIM}{'─'*65}{RESET}")
    print(f"\n{BOLD}{t('disclaimer_title')}{RESET}")
    print(f"  · {t('disclaimer_bugs')}")
    print(f"  · {t('disclaimer_tested')}")
    print(f"    {t('disclaimer_contribute')}")
    print(f"  · {t('disclaimer_thanks')}")
    print(f"  · {t('disclaimer_docs')}")
    print("\n" + "═"*65 + "\n")


def _write_commands_file(project_root, nexe_cmd, model_config):
    """Generate COMMANDS.md reference file."""
    commands_content = f"""# Nexe - Comandes / Commands

## 🚀 Ús bàsic / Basic usage

### Iniciar servidor / Start server
```bash
{nexe_cmd} go
```

### Xat interactiu / Interactive chat
```bash
{nexe_cmd} chat
```

### Xat amb motor específic / Chat with specific engine
```bash
{nexe_cmd} chat --engine mlx
{nexe_cmd} chat --engine ollama
{nexe_cmd} chat --engine llama_cpp
```

## 📊 Comandes de sistema / System commands

```bash
{nexe_cmd} status          # Estat del sistema / System status
{nexe_cmd} logs            # Veure logs / View logs
{nexe_cmd} health          # Health check
```

## 🧠 Gestió de memòria / Memory management

```bash
{nexe_cmd} memory store "text"     # Guardar a memòria / Save to memory
{nexe_cmd} memory recall "query"   # Cercar a memòria / Search memory
```

## 📚 Gestió de coneixement / Knowledge management

```bash
{nexe_cmd} knowledge ingest        # Processar documents / Process documents
{nexe_cmd} knowledge list          # Llistar documents / List documents
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

📝 **Model actual / Current model**: {model_config['name'] if model_config else 'Cap (afegeix-ne un amb nexe model pull)'}
🔧 **Motor / Engine**: {model_config['engine'] if model_config else 'ollama'}
💾 **Ubicació / Location**: {project_root}

*Personal project by Jordi Goy · www.jgoy.net · https://server-nexe.org*
"""
    try:
        commands_file = project_root / "COMMANDS.md"
        with open(commands_file, 'w', encoding='utf-8') as f:
            f.write(commands_content)
        print(f"\n  {DIM}📄 Comandes disponibles a: COMMANDS.md{RESET}")
    except Exception as e:
        print_warn(f"No s'ha pogut escriure COMMANDS.md: {e}")
