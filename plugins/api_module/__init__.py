"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/api_module/__init__.py
Description: External API engine (OpenAI-compatible providers such as
             DeepSeek and OpenAI). Opt-in only: never in the engine cascade,
             never a fallback of a local engine.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .module import ApiModule

__all__ = ["ApiModule"]
