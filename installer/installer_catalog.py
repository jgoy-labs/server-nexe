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
from .installer_hardware import get_recommended_size
from .installer_catalog_data import MODEL_CATALOG  # noqa: F401 (re-exported)


def select_model(hw):
    """Interactive model selection with multiple options per category."""
    clear()
    print(APP_LOGO)

    lang = get_lang()
    ram = hw["ram"]
    usable_ram = int(ram * 0.55)
    recommended_size = get_recommended_size(ram)
    has_metal = hw["has_metal"]

    # Didactic explanation
    print(f"\n{BOLD}🤖 {t('model_selection_title')}{RESET}\n")
    print(f"  {CYAN}{t('your_ram')}:{RESET} {ram} GB")
    print(f"  {CYAN}{t('ram_for_ai')}:{RESET} ~{usable_ram} GB {DIM}(50-60%){RESET}")
    print(f"  {DIM}{t('ram_reserved_note')}{RESET}")

    # Determine recommended category based on RAM
    if usable_ram < 5:
        recommended = "1"
        rec_label = t('size_small')
    elif usable_ram < 20:
        recommended = "2"
        rec_label = t('size_medium')
    else:
        recommended = "3"
        rec_label = t('size_large')

    # Let user choose category regardless of RAM
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"\n{BOLD}{t('model_sizes_title')}{RESET}\n")
    print(f"  {CYAN}1.{RESET} {t('model_small_desc')}")
    print(f"  {CYAN}2.{RESET} {t('model_medium_desc')}")
    print(f"  {CYAN}3.{RESET} {t('model_large_desc')}")
    print()
    print(f"  {DIM}{t('model_recommended_label').format(label=rec_label)}{RESET}")
    print()
    size_choice = input(f"{BOLD}{t('select_size_prompt').format(default=recommended)}{RESET} ").strip() or recommended

    category_map = {"1": ("small", t('category_small')),
                    "2": ("medium", t('category_medium')),
                    "3": ("large", t('category_large'))}
    category, category_name = category_map.get(size_choice, category_map[recommended])

    models = MODEL_CATALOG[category]

    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"\n{BOLD}{category_name}{RESET}\n")

    # Show available models in this category
    for i, model in enumerate(models, 1):
        fits = usable_ram >= model["ram_gb"]

        # Check available engines
        engines = []
        if model.get("mlx"):
            engines.append("MLX")
        if model.get("ollama"):
            engines.append("Ollama")
        if model.get("gguf"):
            engines.append("GGUF")
        engine_info = " / ".join(engines) if engines else t('no')

        # Catalan model highlight
        is_catalan = "AINA" in model["origin"] or "BSC" in model["origin"]
        catalan_tag = f" {MAGENTA}🏠 CATALÀ{RESET}" if is_catalan else ""

        # Status based on RAM
        if fits:
            status = f"{GREEN}✓ {t('compatible')}{RESET}"
        else:
            status = f"{RED}{t('fits_tight')}{RESET}"

        lang_str = model['lang'].get(lang, model['lang']['ca']) if isinstance(model['lang'], dict) else model['lang']
        desc_str = model['description'].get(lang, model['description']['ca']) if isinstance(model['description'], dict) else model['description']

        print(f"  {CYAN}{i}.{RESET} {BOLD}{model['name']}{RESET} {DIM}({model['params']}){RESET}{catalan_tag}")
        print(f"     {model['origin']} | {t('engines_label')}: {engine_info}")
        print(f"     {CYAN}💾 {t('disk_label')}:{RESET} {model['disk_gb']} GB | {CYAN}🧠 RAM:{RESET} {model['ram_gb']} GB")
        print(f"     {DIM}{lang_str}{RESET}")
        print(f"     {desc_str} | {status}")
        print()

    # Model selection
    default = "1"
    choice = input(f"{BOLD}{t('select_model_prompt').format(n=len(models), default=default)}{RESET} ").strip()
    if not choice:
        choice = default

    try:
        selected_model = models[int(choice) - 1]
    except (ValueError, IndexError):
        selected_model = models[0]

    # Engine selection - show all available options
    available_engines = []
    if has_metal and selected_model.get("mlx"):
        available_engines.append(("mlx", "MLX", t('engine_mlx_desc'), True))
    if selected_model.get("ollama"):
        available_engines.append(("ollama", "Ollama", t('engine_ollama_desc'), not has_metal))
    if selected_model.get("gguf"):
        available_engines.append(("llama_cpp", "llama.cpp (GGUF)", t('engine_gguf_desc'), False))

    engine = "ollama"  # Default fallback

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
            engine = available_engines[idx][0]
        except (ValueError, IndexError):
            engine = available_engines[default_idx - 1][0]
    elif len(available_engines) == 1:
        engine = available_engines[0][0]
        print(f"\n  {DIM}ℹ️  {t('will_run_with').format(name=selected_model['name'], engine=available_engines[0][1])}{RESET}")

    # Get model ID based on engine
    if engine == "mlx":
        model_id = selected_model["mlx"]
    elif engine == "llama_cpp":
        model_id = selected_model["gguf"]
    else:
        model_id = selected_model["ollama"]

    return {
        "size": category,
        "engine": engine,
        "id": model_id,
        "name": selected_model["name"],
        "disk_size": f"~{selected_model['disk_gb']} GB",
        "ram": selected_model["ram_gb"],
    }
