"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/models/__init__.py
Description: LLM model management and recommendation based on hardware.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .selector import ModelSelector, HardwareProfile

__all__ = ["ModelSelector", "HardwareProfile"]
