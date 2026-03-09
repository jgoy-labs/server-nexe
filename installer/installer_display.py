"""
────────────────────────────────────
Server Nexe
Location: installer/installer_display.py
Description: UI constants, logo, and print helpers for the installer.
────────────────────────────────────
"""

import os
import subprocess

# ═══════════════════════════════════════════════════════════════════════════
# UI CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
CYAN = "\033[1;36m"
MAGENTA = "\033[1;35m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

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
           assistit per IA · www.jgoy.net{RESET}
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
