"""
────────────────────────────────────
Server Nexe
Location: installer/installer_display.py
Description: UI constants, logo, and print helpers for the installer.
────────────────────────────────────
"""

import os
import subprocess
import sys

# ═══════════════════════════════════════════════════════════════════════════
# UI CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
# Bug 4 (2026-04-06): codis ANSI crus apareixien al log GUI quan stdout no és
# un terminal. Detecció runtime: si no és TTY (mode headless invocat per la
# GUI o redirigit a fitxer), totes les constants de color queden buides per
# evitar que els codis `\033[...m` arribin literals al consumidor.
#
# ⚠️ Dev D (Consultor passada 1): aquesta detecció és un SNAPSHOT al load del
# mòdul. Si el codi client redirigeix `sys.stdout` DESPRÉS d'importar aquest
# mòdul (per exemple un test amb `capsys`), les constants queden bloquejades
# al valor inicial. En producció real (CLI vs GUI headless) cada procés és
# nou i no és problema, però si cal una solució 100% correcta caldria
# convertir les constants a una funció `_color(name)` lazy. v0.9.1+.
_USE_COLOR = sys.stdout.isatty()

if _USE_COLOR:
    BLUE = "\033[1;34m"
    GREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[1;31m"
    CYAN = "\033[1;36m"
    MAGENTA = "\033[1;35m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
else:
    BLUE = GREEN = YELLOW = RED = CYAN = MAGENTA = BOLD = DIM = RESET = ""

APP_LOGO = f"""{RED}
    -
   ####           :#########.   :#######*   .###-  *##+   =#######+
     ####=        :###.   ###  *##+    ###    ###* ##:   ###+   .###
       *###*      :##*     ##.:###########*    ####.    +###########+
       .####      :##+     ##..###:.           #####.   =###:.
     =####        :##+     ##. =###+  =##    :###-###=   *###=  +##
   ####=          :##+     ##.   =######-   *###   -###    +######.
   .#.
{RESET}
      {DIM}Projecte personal de Jordi Goy, aprenent fent-ho
           assistit per IA · www.jgoy.net · https://server-nexe.org{RESET}
"""


def clear():
    """Clear terminal screen safely (no shell injection risk)."""
    cmd = ['cls'] if os.name == 'nt' else ['clear']
    subprocess.run(cmd, shell=False, check=False)


def print_step(msg):
    print(f"\n{BLUE}[STEP]{RESET} {msg}")


def print_success(msg):
    print(f"{GREEN}[OK]{RESET} {msg}")


def print_warn(msg):
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def print_error(msg):
    print(f"{RED}[ERROR]{RESET} {msg}")
