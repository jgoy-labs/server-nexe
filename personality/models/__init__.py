"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/models/__init__.py
Description: Gestió i recomanació de models LLM segons maquinari.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .selector import ModelSelector, HardwareProfile

__all__ = ["ModelSelector", "HardwareProfile"]
