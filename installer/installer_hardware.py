"""
────────────────────────────────────
Server Nexe
Location: installer/installer_hardware.py
Description: Hardware detection and model size recommendation.
────────────────────────────────────
"""

import os
import platform
import re
import subprocess
from pathlib import Path

from .installer_display import (
    CYAN, GREEN, YELLOW, DIM, BOLD, RESET,
    print_step,
)
from .installer_i18n import t

# Global hardware info cache
HW_INFO = {}


def get_sysctl(key):
    try:
        return subprocess.check_output(["sysctl", "-n", key]).decode().strip()
    except Exception:
        return None


def detect_hardware():
    global HW_INFO
    print_step(f"{BOLD}{t('analyzing_hardware')}{RESET}")
    sys_type = platform.system()
    ram_gb = 0
    hw_type = "Generic Computer"
    is_rpi = False
    is_apple_silicon = False
    has_metal = False
    disk_total_gb = 0
    disk_free_gb = 0

    if sys_type == "Darwin":
        mem_bytes = int(get_sysctl("hw.memsize") or 0)
        ram_gb = round(mem_bytes / (1024**3))
        cpu_brand = get_sysctl("machdep.cpu.brand_string") or "Apple Processor"
        if "Apple" in cpu_brand or os.uname().machine == "arm64":
            hw_type = f"Apple Silicon ({os.uname().machine})"
            is_apple_silicon = True
            has_metal = True  # All Apple Silicon has Metal
        else:
            hw_type = "Apple Intel"
    elif sys_type == "Linux":
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if "MemTotal" in line:
                        ram_kb = int(re.search(r'\d+', line).group())
                        ram_gb = round(ram_kb / (1024*1024))
                        break
            model_path = Path('/proc/device-tree/model')
            if model_path.exists():
                with open(model_path, 'r') as f:
                    hw_type = f.read().strip().replace('\x00', '')
                if "Raspberry Pi" in hw_type:
                    is_rpi = True
            else:
                hw_type = f"Linux ({platform.machine()})"
        except Exception:
            ram_gb = 4

    # Detect disk space
    try:
        import shutil
        total, used, free = shutil.disk_usage(Path.home())
        disk_total_gb = round(total / (1024**3))
        disk_free_gb = round(free / (1024**3))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not detect disk space: %s", e)
        disk_total_gb = 0
        disk_free_gb = 0

    print(f"  {CYAN}🖥️  {t('platform')}:{RESET} {hw_type}")
    print(f"  {CYAN}🧠 {t('ram_available')}:{RESET}  {ram_gb} GB")
    if disk_total_gb > 0:
        disk_text = t('disk_free_of_total').format(total=disk_total_gb)
        print(f"  {CYAN}💾 {t('disk_space')}:{RESET} {disk_free_gb} GB {DIM}{disk_text}{RESET}")
    if disk_free_gb == 0:
        print(f"  {YELLOW}[WARN]{RESET} Could not detect available disk space. Verify manually.")
    if is_apple_silicon:
        print(f"  {CYAN}⚡ {t('metal_support')}:{RESET} {GREEN}{t('yes')}{RESET}")

    # Compatibility warning
    print(f"\n  {YELLOW}⚠️  {t('tested_warning')}{RESET}")

    HW_INFO = {
        "ram": ram_gb,
        "type": hw_type,
        "is_rpi": is_rpi,
        "is_apple_silicon": is_apple_silicon,
        "has_metal": has_metal,
        "machine": platform.machine(),
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb
    }
    return HW_INFO


def get_recommended_size(ram_gb):
    """
    Get recommended model size based on RAM.

    IMPORTANT: Models should use max 50-60% of total RAM to leave
    space for OS, browser, and other apps.

    RAM Total → RAM for Model → Recommended
    8 GB      → 4-5 GB        → small (2.4 GB) ✅ or medium (4 GB) ⚠️
    16 GB     → 8-10 GB       → medium (4 GB) ✅ or large (4.5 GB) ✅
    32 GB     → 16-20 GB      → large (4.5 GB) ✅
    64 GB+    → 32+ GB        → xl (26 GB) ✅
    """
    usable_ram = ram_gb * 0.55  # 55% of RAM for model

    if usable_ram >= 28:
        return "xl"
    elif usable_ram >= 8:
        return "large"
    elif usable_ram >= 5:
        return "medium"
    else:
        return "small"
