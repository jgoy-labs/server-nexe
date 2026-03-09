"""
────────────────────────────────────
Server Nexe
Location: installer/installer_translations.py
Description: Assembles per-language translation dicts into TRANSLATIONS.
────────────────────────────────────
"""

from .installer_translations_ca import CA
from .installer_translations_es import ES
from .installer_translations_en import EN

TRANSLATIONS = {
    "ca": CA,
    "es": ES,
    "en": EN,
}
