"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/models/__init__.py
Description: LLM model management and recommendations based on hardware.

www.jgoy.net
────────────────────────────────────
"""

from .selector import ModelSelector, HardwareProfile

__all__ = ["ModelSelector", "HardwareProfile"]
