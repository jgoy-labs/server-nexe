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
                f.write("NEXE_ENV=production\n")
                f.write("NEXE_LOG_LEVEL=INFO\n")
                # Approve all 3 inference backends so users can switch engines
                # from the UI (Motor dropdown) without re-running the installer.
                # Previously gated on wizard choice — left the dropdown with
                # options that failed silently because the module was skipped.
                # Non-Apple-Silicon Macs get mlx_module anyway; the module
                # itself checks for mlx-lm availability and self-disables if
                # missing (same defensive init as llama_cpp_module).
                approved_modules = "security,web_ui_module,ollama_module,mlx_module,llama_cpp_module"
                f.write(f"NEXE_APPROVED_MODULES={approved_modules}\n")
                f.write(f"NEXE_LANG={lang}\n")
                f.write("# Model configuration\n")
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
                    # No model selected — install without a model, user will add one manually
                    f.write("# NEXE_DEFAULT_MODEL=  (configure via 'nexe model pull <name>')\n")
                    f.write("NEXE_MODEL_ENGINE=ollama\n")
                    f.write("NEXE_PROMPT_TIER=small\n")
                f.write("NEXE_QDRANT_PATH=storage/vectors\n")
                f.write("# Optional: external Qdrant (Docker, cluster)\n")
                f.write("# NEXE_QDRANT_URL=http://localhost:6333\n")
                f.write("# Configurable timeouts (seconds)\n")
                f.write("NEXE_QDRANT_TIMEOUT=5.0\n")
                f.write("NEXE_SQLITE_PRELOAD_TIMEOUT=10.0\n")
                f.write("NEXE_OLLAMA_HEALTH_TIMEOUT=5.0\n")
                f.write("NEXE_OLLAMA_UNLOAD_TIMEOUT=10.0\n")
                # fsync before rename so a power cut cannot leave a
                # zero-byte .env behind (the api_key would be lost and the
                # next boot would either fail or generate a fresh key).
                f.flush()
                os.fsync(f.fileno())
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


# ═══════════════════════════════════════════════════════════════════════════
# FAÇADE HELPERS — each absorbs one logical block of _update_env_model_config
# ═══════════════════════════════════════════════════════════════════════════

def _compute_approved_modules(engine):
    """Return the NEXE_APPROVED_MODULES value for a given engine."""
    base = "security,web_ui_module"
    if engine == 'ollama':
        return f"{base},ollama_module"
    if engine == 'mlx':
        return f"{base},mlx_module,ollama_module"
    if engine == 'llama_cpp':
        return f"{base},llama_cpp_module,ollama_module"
    return f"{base},ollama_module,mlx_module,llama_cpp_module"


def _rewrite_mlx_line(line, model_id, model_engine):
    """Return the rewritten NEXE_MLX_MODEL line (update only when engine is mlx)."""
    if model_engine == 'mlx':
        model_name = model_id.split('/')[-1]
        return f"NEXE_MLX_MODEL=storage/models/{model_name}\n"
    return line


def _rewrite_llama_cpp_lines(line, model_id, model_engine, model_config, found_keys):
    """Rewrite NEXE_LLAMA_CPP_MODEL or NEXE_LLAMA_CPP_CHAT_FORMAT. Updates found_keys in place."""
    if line.startswith('NEXE_LLAMA_CPP_MODEL='):
        found_keys['llama_cpp_model'] = True
        if model_engine == 'llama_cpp':
            filename = model_id.split('/')[-1]
            return f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n"
        return line
    if line.startswith('NEXE_LLAMA_CPP_CHAT_FORMAT='):
        found_keys['llama_cpp_chat_format'] = True
        if model_engine == 'llama_cpp':
            return f"NEXE_LLAMA_CPP_CHAT_FORMAT={model_config.get('chat_format', 'chatml')}\n"
        return line
    return line  # unknown NEXE_LLAMA_CPP_ key — preserve as-is


def _rewrite_ollama_line(line, model_id, model_engine):
    """Return the rewritten NEXE_OLLAMA_MODEL line (update only when engine is ollama)."""
    if model_engine == 'ollama':
        return f"NEXE_OLLAMA_MODEL={model_id}\n"
    return line


def _rewrite_env_lines(lines, model_config):
    """Iterate existing .env lines and update model-related keys in place.

    Returns (new_lines, found_keys) where found_keys tracks which keys existed.
    """
    model_id = model_config['id']
    model_engine = model_config['engine']
    found_keys = {
        'model': False,
        'engine': False,
        'csrf': False,
        'mlx_model': False,
        'llama_cpp_model': False,
        'llama_cpp_chat_format': False,
        'prompt_tier': False,
        'ollama_model': False,
        'approved_modules': False,
    }
    new_lines = []

    for line in lines:
        if line.startswith('NEXE_DEFAULT_MODEL='):
            new_lines.append(f"NEXE_DEFAULT_MODEL={model_id}\n")
            found_keys['model'] = True
        elif line.startswith('NEXE_MODEL_ENGINE='):
            new_lines.append(f"NEXE_MODEL_ENGINE={model_engine}\n")
            found_keys['engine'] = True
        elif line.startswith('NEXE_CSRF_SECRET='):
            found_keys['csrf'] = True
            new_lines.append(line)
        elif line.startswith('NEXE_MLX_MODEL='):
            found_keys['mlx_model'] = True
            new_lines.append(_rewrite_mlx_line(line, model_id, model_engine))
        elif line.startswith('NEXE_LLAMA_CPP_'):
            new_lines.append(_rewrite_llama_cpp_lines(line, model_id, model_engine, model_config, found_keys))
        elif line.startswith('NEXE_PROMPT_TIER='):
            found_keys['prompt_tier'] = True
            new_lines.append(f"NEXE_PROMPT_TIER={model_config.get('prompt_tier', 'full')}\n")
        elif line.startswith('NEXE_APPROVED_MODULES='):
            new_lines.append(f"NEXE_APPROVED_MODULES={_compute_approved_modules(model_engine)}\n")
            found_keys['approved_modules'] = True
        elif line.startswith('NEXE_OLLAMA_MODEL='):
            found_keys['ollama_model'] = True
            new_lines.append(_rewrite_ollama_line(line, model_id, model_engine))
        else:
            new_lines.append(line)

    return new_lines, found_keys


def _append_engine_specific_keys(new_lines, found_keys, model_config, model_id, model_engine):
    """Append engine-specific model path keys absent from the existing .env."""
    if not found_keys['mlx_model'] and model_engine == 'mlx':
        model_name = model_id.split('/')[-1]
        new_lines.append(f"NEXE_MLX_MODEL=storage/models/{model_name}\n")
    if not found_keys['llama_cpp_model'] and model_engine == 'llama_cpp':
        filename = model_id.split('/')[-1]
        new_lines.append(f"NEXE_LLAMA_CPP_MODEL=storage/models/{filename}\n")
    if not found_keys['llama_cpp_chat_format'] and model_engine == 'llama_cpp':
        chat_fmt = model_config.get('chat_format', 'chatml')
        new_lines.append(f"NEXE_LLAMA_CPP_CHAT_FORMAT={chat_fmt}\n")
    if not found_keys['ollama_model'] and model_engine == 'ollama':
        new_lines.append(f"NEXE_OLLAMA_MODEL={model_id}\n")


def _append_missing_env_keys(new_lines, found_keys, model_config):
    """Append keys absent from the existing .env to the end of new_lines."""
    import secrets as _secrets

    model_id = model_config['id']
    model_engine = model_config['engine']

    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines.append('\n')

    if not found_keys['csrf']:
        new_lines.append(f"NEXE_CSRF_SECRET={_secrets.token_hex(32)}\n")

    if not any('# Model configuration' in line for line in new_lines):
        new_lines.append("# Model configuration\n")
    if not found_keys['model']:
        new_lines.append(f"NEXE_DEFAULT_MODEL={model_id}\n")
    if not found_keys['engine']:
        new_lines.append(f"NEXE_MODEL_ENGINE={model_engine}\n")
    _append_engine_specific_keys(new_lines, found_keys, model_config, model_id, model_engine)
    if not found_keys['prompt_tier']:
        new_lines.append(f"NEXE_PROMPT_TIER={model_config.get('prompt_tier', 'full')}\n")
    if not found_keys['approved_modules']:
        new_lines.append(f"NEXE_APPROVED_MODULES={_compute_approved_modules(model_engine)}\n")


def _atomic_write_env(env_file, new_lines):
    """Write new_lines to env_file atomically using a tmp file + rename."""
    import os as _os
    env_tmp = env_file.parent / f".env.tmp.{_os.getpid()}"
    try:
        with open(env_tmp, 'w') as f:
            f.writelines(new_lines)
            # fsync before rename so a crash here cannot leave a zero-byte
            # .env. See _generate_env_file() for the same defence.
            f.flush()
            _os.fsync(f.fileno())
        env_tmp.rename(env_file)
    except Exception:
        env_tmp.unlink(missing_ok=True)
        raise


def _update_env_model_config(env_file, model_config):
    """Update model configuration in existing .env file."""
    if model_config is None:
        # No model selected — keep existing .env as-is
        return

    with open(env_file, 'r') as f:
        lines = f.readlines()

    new_lines, found_keys = _rewrite_env_lines(lines, model_config)
    _append_missing_env_keys(new_lines, found_keys, model_config)
    _atomic_write_env(env_file, new_lines)

    print(f"  📝 {t('model_selected')}: {model_config['id']} ({model_config['engine']})")
