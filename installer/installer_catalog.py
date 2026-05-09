"""
────────────────────────────────────
Server Nexe
Location: installer/installer_catalog.py
Description: Interactive model selection wizard.
────────────────────────────────────
"""

from .installer_display import (
    APP_LOGO, clear,
    CYAN, MAGENTA, GREEN, RED, YELLOW, BOLD, DIM, RESET,
)
from .installer_i18n import t, get_lang
from .installer_catalog_data import MODEL_CATALOG  # noqa: F401 (re-exported)


def _determine_recommended_category(usable_ram: int) -> tuple:
    """Return (rec_choice, rec_label) based on available RAM."""
    if usable_ram < 5:
        return "1", t('size_small')
    elif usable_ram < 20:
        return "2", t('size_medium')
    else:
        return "3", t('size_large')


def _resolve_category(size_choice: str, recommended: str) -> tuple:
    """Convert the size choice to (category, category_name)."""
    category_map = {
        "1": ("small", t('category_small')),
        "2": ("medium", t('category_medium')),
        "3": ("large", t('category_large')),
    }
    return category_map.get(size_choice, category_map[recommended])


def _get_model_engines(model: dict) -> list:
    """Return the list of available engine names for a model."""
    engines = []
    if model.get("mlx"):
        engines.append("MLX")
    if model.get("ollama"):
        engines.append("Ollama")
    if model.get("gguf"):
        engines.append("GGUF")
    return engines


def _get_model_status(fits: bool, fits_disk: bool, disk_free_gb: float) -> str:
    """Return the RAM/disk status string for a model."""
    if fits:
        return f"{GREEN}✓ {t('compatible')}{RESET}"
    elif not fits_disk and disk_free_gb > 0:
        return f"{RED}{t('fits_tight')} (disk){RESET}"
    else:
        return f"{RED}{t('fits_tight')}{RESET}"


def _localize(field: "str | dict[str, str]", lang: str) -> str:
    """Return the localised field if it is a dict; otherwise return the value directly."""
    if isinstance(field, dict):
        return field.get(lang, field['ca'])
    return field


def _print_model_entry(
    i: int, model: dict, usable_ram: int, disk_free_gb: float, lang: str
) -> None:
    """Print a model entry in the selection list."""
    fits_ram = usable_ram >= model["ram_gb"]
    fits_disk = disk_free_gb >= model.get("disk_gb", 0) * 1.2
    fits = fits_ram and fits_disk

    engines = _get_model_engines(model)
    engine_info = " / ".join(engines) if engines else t('no')

    is_catalan = "AINA" in model["origin"] or "BSC" in model["origin"]
    catalan_tag = f" {MAGENTA}🏠 CATALÀ{RESET}" if is_catalan else ""

    status = _get_model_status(fits, fits_disk, disk_free_gb)
    lang_str = _localize(model['lang'], lang)
    desc_str = _localize(model['description'], lang)

    print(f"  {CYAN}{i}.{RESET} {BOLD}{model['name']}{RESET} {DIM}({model['params']}){RESET}{catalan_tag}")
    print(f"     {model['origin']} | {t('engines_label')}: {engine_info}")
    print(f"     {CYAN}💾 {t('disk_label')}:{RESET} {model['disk_gb']} GB | {CYAN}🧠 RAM:{RESET} {model['ram_gb']} GB")
    print(f"     {DIM}{lang_str}{RESET}")
    print(f"     {desc_str} | {status}")
    print()


def _print_model_list(
    models: list, usable_ram: int, disk_free_gb: float, lang: str
) -> None:
    """Print the full list of models for a category."""
    for i, model in enumerate(models, 1):
        _print_model_entry(i, model, usable_ram, disk_free_gb, lang)


def _select_category(recommended: str, rec_label: str) -> str:
    """Show the size menu and return the user's choice."""
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"\n{BOLD}{t('model_sizes_title')}{RESET}\n")
    print(f"  {CYAN}1.{RESET} {t('model_small_desc')}")
    print(f"  {CYAN}2.{RESET} {t('model_medium_desc')}")
    print(f"  {CYAN}3.{RESET} {t('model_large_desc')}")
    print()
    print(f"  {DIM}{t('model_recommended_label').format(label=rec_label)}{RESET}")
    print()
    return input(f"{BOLD}{t('select_size_prompt').format(default=recommended)}{RESET} ").strip() or recommended


def _select_model_from_list(models: list) -> dict:
    """Ask the user to choose a model. Return the selected model."""
    default = "1"
    choice = input(f"{BOLD}{t('select_model_prompt').format(n=len(models), default=default)}{RESET} ").strip()
    if not choice:
        choice = default
    try:
        return models[int(choice) - 1]
    except (ValueError, IndexError):
        return models[0]


def _build_available_engines(selected_model: dict, has_metal: bool) -> list:
    """Build the list of available engines for the selected model."""
    available = []
    if has_metal and selected_model.get("mlx"):
        available.append(("mlx", "MLX", t('engine_mlx_desc'), True))
    if selected_model.get("ollama"):
        available.append(("ollama", "Ollama", t('engine_ollama_desc'), not has_metal))
    if selected_model.get("gguf"):
        available.append(("llama_cpp", "llama.cpp (GGUF)", t('engine_gguf_desc'), False))
    return available


def _select_engine_interactive(selected_model: dict, available_engines: list) -> str:
    """Show the engine menu and return the engine chosen by the user."""
    if len(available_engines) > 1:
        clear()
        print(APP_LOGO)
        print(f"\n{BOLD}⚡ {t('select_engine')}{RESET}")
        print(f"{BOLD}   {selected_model['name']}{RESET}\n")
        print(f"{DIM}{t('engine_explanation')}{RESET}\n")
        for i, (eng_key, eng_name, eng_desc, is_rec) in enumerate(available_engines, 1):
            rec_tag = f" {GREEN}← {t('recommended').upper()}{RESET}" if is_rec else ""
            print(f"  {CYAN}{i}.{RESET} {BOLD}{eng_name}{RESET}{rec_tag}")
            print(f"     {DIM}{eng_desc}{RESET}\n")
        default_idx = next((i for i, (_, _, _, rec) in enumerate(available_engines, 1) if rec), 1)
        engine_choice = input(f"{BOLD}{t('select_engine_prompt').format(n=len(available_engines), default=default_idx)}{RESET} ").strip()
        try:
            idx = int(engine_choice) - 1 if engine_choice else default_idx - 1
            return available_engines[idx][0]
        except (ValueError, IndexError):
            return available_engines[default_idx - 1][0]
    elif len(available_engines) == 1:
        print(f"\n  {DIM}ℹ️  {t('will_run_with').format(name=selected_model['name'], engine=available_engines[0][1])}{RESET}")
        return available_engines[0][0]
    return "ollama"


def _warn_qwen35_mlx(engine: str, selected_model: dict) -> None:
    """Warn about pip dependency conflict for Qwen3.5 + MLX."""
    if engine == "mlx" and selected_model.get("mlx") and "Qwen3.5" in selected_model.get("mlx", ""):
        print(f"\n{YELLOW}{'─'*60}{RESET}")
        print(f"{YELLOW}{BOLD}{t('mlx_dep_warning_title')}{RESET}")
        print(f"{DIM}{t('mlx_dep_warning_body')}{RESET}")
        print(f"{YELLOW}{'─'*60}{RESET}\n")
        input(f"{DIM}[{t('press_enter')}]{RESET}")


def _get_model_id(engine: str, selected_model: dict) -> str:
    """Return the model ID for the selected engine."""
    if engine == "mlx":
        return selected_model["mlx"]
    elif engine == "llama_cpp":
        return selected_model["gguf"]
    else:
        return selected_model["ollama"]


def select_model(hw):
    """Interactive model selection with multiple options per category."""
    clear()
    print(APP_LOGO)

    lang = get_lang()
    ram = hw["ram"]
    usable_ram = int(ram * 0.55)
    has_metal = hw["has_metal"]
    disk_free_gb = hw.get("disk_free_gb", 0)

    print(f"\n{BOLD}🤖 {t('model_selection_title')}{RESET}\n")
    print(f"  {CYAN}{t('your_ram')}:{RESET} {ram} GB")
    print(f"  {CYAN}{t('ram_for_ai')}:{RESET} ~{usable_ram} GB {DIM}(50-60%){RESET}")
    print(f"  {DIM}{t('ram_reserved_note')}{RESET}")

    recommended, rec_label = _determine_recommended_category(usable_ram)
    size_choice = _select_category(recommended, rec_label)
    category, category_name = _resolve_category(size_choice, recommended)
    models = MODEL_CATALOG[category]

    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"\n{BOLD}{category_name}{RESET}\n")
    _print_model_list(models, usable_ram, disk_free_gb, lang)

    selected_model = _select_model_from_list(models)
    available_engines = _build_available_engines(selected_model, has_metal)
    engine = _select_engine_interactive(selected_model, available_engines)

    _warn_qwen35_mlx(engine, selected_model)

    model_id = _get_model_id(engine, selected_model)

    return {
        "size": category,
        "engine": engine,
        "id": model_id,
        "name": selected_model["name"],
        "disk_size": f"~{selected_model['disk_gb']} GB",
        "ram": selected_model["ram_gb"],
        "prompt_tier": selected_model.get("prompt_tier", "full"),
        "chat_format": selected_model.get("chat_format", "chatml"),
    }
