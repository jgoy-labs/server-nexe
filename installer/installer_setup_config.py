"""
────────────────────────────────────
Server Nexe
Location: installer/installer_setup_config.py
Description: .env file generation and model configuration update.
────────────────────────────────────
"""

from .installer_display import (
    CYAN, DIM, BOLD, YELLOW, RESET,
    print_step, print_success,
)
from .installer_i18n import t, get_lang


def generate_env_file(project_root, model_config=None):
    """Generate .env file with security and model config.

    Security: API key is NOT printed to stdout to prevent exposure
    in CI/CD logs or shared terminal sessions.
    """
    print_step(f"{BOLD}{t('generating_security')}{RESET}")
    print(f"  {DIM}{t('security_explanation')}{RESET}")
    import os
    import secrets
    import stat
    secure_key = secrets.token_hex(32)
    env_file = project_root / ".env"

    if not env_file.exists():
        csrf_secret = secrets.token_hex(32)
        lang = get_lang()
        env_tmp = env_file.parent / f".env.tmp.{os.getpid()}"
        try:
            with open(env_tmp, "w") as f:
                f.write(f"NEXE_PRIMARY_API_KEY={secure_key}\n")
                f.write(f"NEXE_CSRF_SECRET={csrf_secret}\n")
                f.write(f"NEXE_ENV=production\n")
                f.write(f"NEXE_LOG_LEVEL=INFO\n")
                # Only include modules for the selected engine (avoids MLX errors on Ollama installs)
                engine = model_config.get('engine', 'ollama') if model_config else 'ollama'
                base_modules = "security,web_ui_module"
                if engine == 'ollama':
                    approved_modules = f"{base_modules},ollama_module"
                elif engine == 'mlx':
                    approved_modules = f"{base_modules},mlx_module,ollama_module"
                elif engine == 'llama_cpp':
                    approved_modules = f"{base_modules},llama_cpp_module,ollama_module"
                else:
                    approved_modules = f"{base_modules},ollama_module,mlx_module,llama_cpp_module"
                f.write(f"NEXE_APPROVED_MODULES={approved_modules}\n")
                f.write(f"NEXE_LANG={lang}\n")
                f.write(f"# Model configuration\n")
                if model_config:
                    f.write(f"NEXE_DEFAULT_MODEL={model_config['id']}\n")
                    f.write(f"NEXE_MODEL_ENGINE={model_config['engine']}\n")
                    f.write(f"NEXE_PROMPT_TIER={model_config.get('prompt_tier', 'full')}\n")
                    # Engine-specific model paths (using relative paths for portability)
                    if model_config['engine'] == 'mlx':
                        model_name = model_config['id'].split('/')[-1]
                        f.write(f"NEXE_MLX_MODEL=storage/models/{model_name}\n")
                    elif model_config['engine'] == 'llama_cpp':
                        # GGUF models are downloaded as single files
                        filename = model_config['id'].split('/')[-1]
                        f.write(f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n")
                        f.write(f"NEXE_LLAMA_CPP_CHAT_FORMAT={model_config.get('chat_format', 'chatml')}\n")
                    elif model_config['engine'] == 'ollama':
                        f.write(f"NEXE_OLLAMA_MODEL={model_config['id']}\n")
                else:
                    # No model selected — instal·la sense model, l'usuari afegirà un model manualment
                    f.write(f"# NEXE_DEFAULT_MODEL=  (configura via 'nexe model pull <name>')\n")
                    f.write(f"NEXE_MODEL_ENGINE=ollama\n")
                    f.write(f"NEXE_PROMPT_TIER=small\n")
                f.write("NEXE_QDRANT_PATH=storage/vectors\n")
                f.write("# Optional: external Qdrant (Docker, cluster)\n")
                f.write("# NEXE_QDRANT_URL=http://localhost:6333\n")
                f.write("# Configurable timeouts (seconds)\n")
                f.write("NEXE_QDRANT_TIMEOUT=5.0\n")
                f.write("NEXE_SQLITE_PRELOAD_TIMEOUT=10.0\n")
                f.write("NEXE_OLLAMA_HEALTH_TIMEOUT=5.0\n")
                f.write("NEXE_OLLAMA_UNLOAD_TIMEOUT=10.0\n")
            env_tmp.rename(env_file)
        except Exception:
            env_tmp.unlink(missing_ok=True)
            raise
        # Set restrictive permissions (owner read/write only)
        env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # chmod 600

        print_success(t('env_created'))
        print(f"  🔑 {t('api_key')}:")
        print()
        print(f"  {CYAN}{secure_key}{RESET}")
        print()
        print(f"  {YELLOW}{t('copy_api_key')}{RESET}")
        print(f"  {DIM}⚠️  No comparteixis aquesta clau (screenshots, logs, xats){RESET}")
        print(f"  {DIM}({t('saved_at')} {env_file} · chmod 600){RESET}")
    else:
        # Update existing .env with model configuration
        _update_env_model_config(env_file, model_config)
        print_success(t('env_exists'))


def _update_env_model_config(env_file, model_config):
    """Update model configuration in existing .env file."""
    if model_config is None:
        # No model selected — keep existing .env as-is
        return

    import os
    import secrets

    # Read existing content
    with open(env_file, 'r') as f:
        lines = f.readlines()

    # Track which keys we need to update/add
    model_id = model_config['id']
    model_engine = model_config['engine']
    found_model = False
    found_engine = False
    found_csrf = False
    found_mlx_model = False
    found_llama_cpp_model = False
    found_llama_cpp_chat_format = False
    found_prompt_tier = False
    found_ollama_model = False
    found_approved_modules = False
    new_lines = []

    for line in lines:
        if line.startswith('NEXE_DEFAULT_MODEL='):
            new_lines.append(f"NEXE_DEFAULT_MODEL={model_id}\n")
            found_model = True
        elif line.startswith('NEXE_MODEL_ENGINE='):
            new_lines.append(f"NEXE_MODEL_ENGINE={model_engine}\n")
            found_engine = True
        elif line.startswith('NEXE_CSRF_SECRET='):
            found_csrf = True
            new_lines.append(line)
        elif line.startswith('NEXE_MLX_MODEL='):
            found_mlx_model = True
            if model_engine == 'mlx':
                model_name = model_id.split('/')[-1]
                new_lines.append(f"NEXE_MLX_MODEL=storage/models/{model_name}\n")
            else:
                new_lines.append(line)
        elif line.startswith('NEXE_LLAMA_CPP_MODEL='):
            found_llama_cpp_model = True
            if model_engine == 'llama_cpp':
                filename = model_id.split('/')[-1]
                new_lines.append(f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n")
            else:
                new_lines.append(line)
        elif line.startswith('NEXE_LLAMA_CPP_CHAT_FORMAT='):
            found_llama_cpp_chat_format = True
            if model_engine == 'llama_cpp':
                chat_fmt = model_config.get('chat_format', 'chatml')
                new_lines.append(f"NEXE_LLAMA_CPP_CHAT_FORMAT={chat_fmt}\n")
            else:
                new_lines.append(line)
        elif line.startswith('NEXE_PROMPT_TIER='):
            found_prompt_tier = True
            new_lines.append(f"NEXE_PROMPT_TIER={model_config.get('prompt_tier', 'full')}\n")
        elif line.startswith('NEXE_APPROVED_MODULES='):
            engine = model_config.get('engine', 'ollama')
            base_modules = "security,web_ui_module"
            if engine == 'ollama':
                approved_modules = f"{base_modules},ollama_module"
            elif engine == 'mlx':
                approved_modules = f"{base_modules},mlx_module,ollama_module"
            elif engine == 'llama_cpp':
                approved_modules = f"{base_modules},llama_cpp_module,ollama_module"
            else:
                approved_modules = f"{base_modules},ollama_module,mlx_module,llama_cpp_module"
            new_lines.append(f"NEXE_APPROVED_MODULES={approved_modules}\n")
            found_approved_modules = True
        elif line.startswith('NEXE_OLLAMA_MODEL='):
            found_ollama_model = True
            if model_engine == 'ollama':
                new_lines.append(f"NEXE_OLLAMA_MODEL={model_id}\n")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Add missing keys at the end
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines.append('\n')

    if not found_csrf:
        new_lines.append(f"NEXE_CSRF_SECRET={secrets.token_hex(32)}\n")

    if not any('# Model configuration' in l for l in new_lines):
        new_lines.append("# Model configuration\n")
    if not found_model:
        new_lines.append(f"NEXE_DEFAULT_MODEL={model_id}\n")
    if not found_engine:
        new_lines.append(f"NEXE_MODEL_ENGINE={model_engine}\n")
    if not found_mlx_model and model_engine == 'mlx':
        model_name = model_id.split('/')[-1]
        new_lines.append(f"NEXE_MLX_MODEL=storage/models/{model_name}\n")
    if not found_llama_cpp_model and model_engine == 'llama_cpp':
        filename = model_id.split('/')[-1]
        new_lines.append(f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n")
    if not found_llama_cpp_chat_format and model_engine == 'llama_cpp':
        chat_fmt = model_config.get('chat_format', 'chatml')
        new_lines.append(f"NEXE_LLAMA_CPP_CHAT_FORMAT={chat_fmt}\n")
    if not found_prompt_tier:
        new_lines.append(f"NEXE_PROMPT_TIER={model_config.get('prompt_tier', 'full')}\n")
    if not found_approved_modules:
        engine = model_config.get('engine', 'ollama')
        base_modules = "security,web_ui_module"
        if engine == 'ollama':
            approved_modules = f"{base_modules},ollama_module"
        elif engine == 'mlx':
            approved_modules = f"{base_modules},mlx_module,ollama_module"
        elif engine == 'llama_cpp':
            approved_modules = f"{base_modules},llama_cpp_module,ollama_module"
        else:
            approved_modules = f"{base_modules},ollama_module,mlx_module,llama_cpp_module"
        new_lines.append(f"NEXE_APPROVED_MODULES={approved_modules}\n")
    if not found_ollama_model and model_engine == 'ollama':
        new_lines.append(f"NEXE_OLLAMA_MODEL={model_id}\n")

    # Write back — atomic write with cleanup on failure
    env_tmp = env_file.parent / f".env.tmp.{os.getpid()}"
    try:
        with open(env_tmp, 'w') as f:
            f.writelines(new_lines)
        env_tmp.rename(env_file)
    except Exception:
        env_tmp.unlink(missing_ok=True)
        raise

    print(f"  📝 {t('model_selected')}: {model_id} ({model_engine})")
