"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/cli/health.py
Description: Health check interface for Central Nexe CLI. Facade that prevents imports

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

def get_health(i18n=None):
    """
    Get health status for the CLI Central Nexe module.

    Args:
        i18n: Internationalization manager (optional)

    Returns:
        dict: Health check results in standardized format
    """
    return {
        "name": "cli",
        "status": "HEALTHY",
        "checks": [],
        "details": [],
    }