"""
────────────────────────────────────
Server Nexe
Location: installer/installer_i18n.py
Description: Language state, t() helper, and language selection wizard.
────────────────────────────────────
"""

from .installer_display import APP_LOGO, clear, BOLD, DIM, CYAN, RESET
from .installer_translations import TRANSLATIONS

# Global language state
LANG = "ca"


def t(key: str) -> str:
    """Get translation for current language."""
    return TRANSLATIONS.get(LANG, TRANSLATIONS["en"]).get(key, key)


def get_lang() -> str:
    """Return the current language code."""
    return LANG


def select_language():
    """Interactive language selection."""
    global LANG
    clear()
    print(APP_LOGO)

    descriptions = {
        "ca": "Nexe és un servidor d'IA local, sobirà i persistent.\nNo es connecta al núvol. Memòria de conversa i personalitat configurable.",
        "es": "Nexe es un servidor de IA local, soberano y persistente.\nNo se conecta a la nube. Memoria de conversación y personalidad configurable.",
        "en": "Nexe is a local, sovereign and persistent AI server.\nDoes not connect to the cloud. Conversation memory and configurable personality."
    }

    print(f"\n{BOLD}Selecciona idioma / Select language / Selecciona idioma:{RESET}\n")
    print(f"  {CYAN}1.{RESET} Català")
    print(f"  {CYAN}2.{RESET} Español")
    print(f"  {CYAN}3.{RESET} English")

    choice = input(f"\n{BOLD}[1/2/3]:{RESET} ").strip()

    if choice == "2":
        LANG = "es"
    elif choice == "3":
        LANG = "en"
    else:
        LANG = "ca"

    clear()
    print(APP_LOGO)
    print(f"\n{DIM}{descriptions[LANG]}{RESET}\n")
    input(f"{DIM}{t('press_enter')}{RESET}")

    return LANG
