"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/health.py
Description: Facade get_health() per al modul security.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from typing import Dict, Any


def get_health() -> Dict[str, Any]:
    """
    Facade sincrona per obtenir health del modul security.

    Retorna dict amb status, message, details, checks.
    Delega a SecurityModule.health_check() (async).
    """
    from .manifest import get_module_instance

    module = get_module_instance()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Ja dins event loop (ex: FastAPI) — no podem fer asyncio.run()
        # Retornem un resultat basic sincron
        return {
            "status": "healthy" if module._initialized else "unknown",
            "module": module.metadata.name,
            "version": module.metadata.version,
            "initialized": module._initialized,
        }

    # Fora event loop — podem executar l'async health_check
    result = asyncio.run(module.health_check())
    return result.to_dict()
